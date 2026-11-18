#!/usr/bin/env python3
"""Evaluate Cantonese call-centre transcriptions (.docx) against human ground truth (.docx).

Both sides are Word documents:
  * reference : "Transcription-<recording filename>.docx" with "<speaker>: <text>" paragraphs
  * hypothesis: model output .docx (header lines Status/Model/Accuracy review, "[mm:ss]" tags)

A docx may contain several calls; each call starts at a line that names the recording
(path/filename containing the recording uuid). Calls are paired by recording uuid
(fallback: agent name + date/time). Mismatched calls are never paired.

Usage:
    python eval_cantonese_asr.py --hyp-dir HYP --ref-dir REF --out OUT [--map-colloquial]
        [--drop-fillers] [--gt-verified] [--repeat-min-tokens N] [--strip-speakers-hyp]
(--hyp-dir / --ref-dir accept a directory of .docx files or a single .docx file.)
Run with --list-mappings to print every normalization mapping. See README.md for details.
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import jiwer
from docx import Document
from opencc import OpenCC

log = logging.getLogger("eval_cantonese_asr")

# --------------------------------------------------------------------------- constants
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
TAILX_RE = re.compile(r"-([^\s\-_.]{12})(?=\.(?:mp4|wav|m4a|mp3|flac)\b)", re.I)
TAIL_RE = re.compile(r"([0-9a-f]{12})(?=\.(?:mp4|wav|m4a|mp3|flac)\b)", re.I)
AGENT_DT_RE = re.compile(r"recording[_ ](.+?)_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})", re.I)
MEDIA_RE = re.compile(r"\.(?:mp4|wav|m4a|mp3|flac)\b", re.I)
TS_RE = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\]")
META_RE = re.compile(r"^\s*(Status|Model|Accuracy review)\s*[:：]", re.I)
BACKCHANNEL_RE = re.compile(r"[（(]\s*[^\s:：()（）]{1,10}\s*[:：]\s*([^()（）]*)[）)]")
SPEAKER_RE = re.compile(r"^\s*[^\s:：()（）]{1,10}\s*[:：]\s*")
TOKEN_RE = re.compile(r"[a-z0-9]+|[㐀-䶿一-鿿豈-﫿]")
ID_PREFIX_RE = re.compile(r"[a-z]+(\d{4,}[a-z0-9]*)$")
ENTITY_RE = re.compile(r"[a-z]*\d+[a-z0-9]*")

VARIANTS = {"爲": "為", "着": "著", "裏": "裡", "衞": "衛", "啓": "啟", "峯": "峰", "羣": "群", "户": "戶",
            "賬": "帳", "紀錄": "記錄"}

# multi-char keys are applied first (longest-first)
COLLOQUIAL = {
    "佢哋": "他們", "呢個": "這個", "係": "是", "嘅": "的", "咗": "了", "唔": "不",
    "冇": "沒有", "佢": "他", "喺": "在", "畀": "給", "俾": "給", "啲": "些",
    "嚟": "來", "睇": "看", "嗰": "那", "哋": "們",
    # particle spellings unified (阿/啊/呀 are the same sentence-final particle); 須/需 same word
    "啊": "阿", "呀": "阿", "須": "需",
    # lexical swaps (section A)
    "跟住": "接著", "呢度": "這裡", "乜嘢": "什麼", "而家": "現在", "仲": "還",
    "同埋": "和", "直情": "直接", "撳": "按", "裡邊": "裡面",
    "係咪": "是不是", "嘢": "東西",
}
# English code-switch -> Chinese, whole-token match only (section B)
ENGLISH = {
    "reply": "回覆", "email": "電郵", "check": "查", "send": "發",
    "reconfirm": "重新確認",
}
_DO_NOT_REPLY_RE = re.compile(r"do[\s\-_]*not[\s\-_]*reply")  # kept in English, always spaced
_ENGLISH_RE = re.compile(
    r"(?<![a-z0-9])(?<!do not )(" + "|".join(sorted(ENGLISH, key=len, reverse=True)) + r")(?![a-z0-9])")
# filler particles deleted on both sides with --drop-fillers (section E)
FILLERS = "嗯哦咦阿啊呀啦囉㗎啫吖喇喎咯嘛咧咁"
_FILLER_RE = re.compile("[" + FILLERS + "]")
# context rules (regex -> replacement), applied after the dictionary above
CONTEXT_RULES = [
    (re.compile(r"(?<=\d)\s*號"), "日", "號 -> 日 only right after a digit (dates: 3號 -> 3日)"),
    (re.compile(r"同(?=[你我他])"), "跟", "同 -> 跟 only before 你/我/他 (同你確認 -> 跟你確認)"),
    (re.compile(r"呢一"), "這一", "呢一 -> 這一 (plain 呢 is not mapped)"),
]
_COLLOQ_RE = re.compile("|".join(map(re.escape, sorted(COLLOQUIAL, key=len, reverse=True))))

_OPENCC = OpenCC("s2hk")

CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "两": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
CN_UNIT = {"十": 10, "百": 100, "千": 1000}
CN_BIG = {"萬": 10_000, "万": 10_000}
CN_RUN_RE = re.compile("[" + "".join(list(CN_DIGIT) + list(CN_UNIT) + list(CN_BIG)) + "]+")


# --------------------------------------------------------------------------- normalize
_SPELLED_RE = re.compile(r"(?<![a-z0-9])(?:[a-z0-9] ){2,}[a-z0-9](?![a-z0-9])")
_LETTER_DIGIT_RE = re.compile(r"(?<![a-z0-9])([a-z]{1,6}) (?=\d{4})")  # prefix + long number


def join_ids(text: str) -> str:
    """Make IDs spacing-insensitive: 'abcd 12345678' / 'a b c d 0 0 2' -> 'abcd12345678' / 'abcd002'.

    Joins (a) runs of >=3 single Latin letters/digits spelled one by one and
    (b) a short Latin prefix (<=6 letters) followed by a number of >=4 digits.
    Short numbers ("sorry 8", "card 12") are left alone. Applied to both sides.
    """
    text = _SPELLED_RE.sub(lambda m: m.group(0).replace(" ", ""), text)
    return _LETTER_DIGIT_RE.sub(r"\1", text)


def normalize(text: str, map_colloquial: bool = False, drop_fillers: bool = False) -> str:
    """Normalize text identically for reference and hypothesis.

    Steps: strip [mm:ss] tags, NFKC, lowercase, OpenCC s2hk, variant unification,
    optional filler deletion (drop_fillers), optional colloquial/English->written mapping,
    punctuation -> space, collapse whitespace.
    Thousands separators inside numbers ("1,000") are removed, not split.
    """
    text = unicodedata.normalize("NFKC", text).lower()
    text = TS_RE.sub(" ", text)  # after NFKC so full-width ［00:00］ tags are caught
    text = _OPENCC.convert(text)
    for src, dst in VARIANTS.items():
        text = text.replace(src, dst)
    text = chinese_numerals_to_arabic(text)
    text = _DO_NOT_REPLY_RE.sub("do not reply", text)
    if drop_fillers:
        text = _FILLER_RE.sub("", text)
    if map_colloquial:
        text = _COLLOQ_RE.sub(lambda m: COLLOQUIAL[m.group(0)], text)
        text = _ENGLISH_RE.sub(lambda m: ENGLISH[m.group(1)], text)
        for pattern, repl, _ in CONTEXT_RULES:
            text = pattern.sub(repl, text)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    text = "".join(
        " " if unicodedata.category(c)[0] in ("P", "S", "Z", "C") else c for c in text
    )
    return join_ids(re.sub(r"\s+", " ", text).strip())


def tokenize(text: str) -> list[str]:
    """Mixed-script tokens: each CJK char is a token; each [a-z0-9]+ run is a token."""
    return TOKEN_RE.findall(text)


# --------------------------------------------------------------------------- entities
def _cn_to_int(s: str) -> int | None:
    """Convert a Chinese numeral run (e.g. 三百三十三, 一九七三) to int, else None."""
    if all(c in CN_DIGIT for c in s):  # positional: 一九七三
        return int("".join(str(CN_DIGIT[c]) for c in s))
    total, section, num = 0, 0, None
    for c in s:
        if c in CN_DIGIT:
            num = CN_DIGIT[c]
        elif c in CN_UNIT:
            section += (1 if num is None else num) * CN_UNIT[c]
            num = None
        elif c in CN_BIG:
            section += num or 0
            total += (section or 1) * CN_BIG[c]
            section, num = 0, None
    return total + section + (num or 0)


def chinese_numerals_to_arabic(text: str) -> str:
    """Replace unambiguous Chinese numeral runs with Arabic digits.

    Single characters ("十", "一起") are left alone unless followed by a date unit or
    measure word (八月, 十月, 二十九號, 四位, 一個, 兩次, 三蚊); otherwise runs need >=2 chars and, if all plain digits,
    >=3 chars (一九七三), or contain a unit (三百三十三).
    """
    def repl(m: re.Match) -> str:
        run = m.group(0)
        has_unit = any(c in CN_UNIT or c in CN_BIG for c in run)
        date_unit = m.string[m.end():m.end() + 1] in ("月", "日", "號", "号", "年", "位", "個", "次", "蚊")
        if not date_unit and (len(run) < 2 or (not has_unit and len(run) < 3)):
            return run
        val = _cn_to_int(run)
        return f" {val} " if val is not None else run
    return CN_RUN_RE.sub(repl, text)


def extract_entities(normalized: str) -> list[str]:
    """Digit-bearing tokens (phone/policy no., amounts, dates) after numeral conversion."""
    ents = ENTITY_RE.findall(chinese_numerals_to_arabic(normalized))
    # ID-like tokens (letters + >=4 digits): compare the number only, so "abcd 係 12345678"
    # (ground truth) and "abcd12345678" (hypothesis) agree; the letters are scored by CER.
    return [m.group(1) if (m := ID_PREFIX_RE.match(e)) else e for e in ents]


def entity_scores(ref_ents: list[str], hyp_ents: list[str]) -> tuple[float | None, float | None]:
    """(precision, recall) of exact entity matches as multisets; None if undefined."""
    common = sum((Counter(ref_ents) & Counter(hyp_ents)).values())
    p = common / len(hyp_ents) if hyp_ents else None
    r = common / len(ref_ents) if ref_ents else None
    return p, r


# --------------------------------------------------------------------------- docx loading
@dataclass
class Call:
    """One call's text taken from a docx."""
    source: str
    keys: set[str]
    lines: list[str] = field(default_factory=list)


def _canon(tail: str) -> str:
    """Lowercase; any non-hex char (e.g. a Cyrillic look-alike from copy/paste) becomes '?'."""
    return "".join(c if c in "0123456789abcdef" else "?" for c in tail.lower())


def _key_eq(a: str, b: str) -> bool:
    """Keys are equal if same length and every position matches or is a '?' wildcard."""
    return len(a) == len(b) and all(x == y or "?" in (x, y) for x, y in zip(a, b))


def keys_from_text(text: str) -> set[str]:
    """Pairing keys: 'uuid:<last 12 hex>' and/or 'dt:<agent>|<date>_<hhmm>'."""
    keys: set[str] = set()
    t = TAILX_RE.search(text)
    m = UUID_RE.search(text)
    if t:
        keys.add("uuid:" + _canon(t.group(1)))
    elif m:
        keys.add("uuid:" + _canon(m.group(0)[-12:]))
    a = AGENT_DT_RE.search(text)
    if a:
        agent = re.sub(r"\s+", "", a.group(1)).lower()
        keys.add(f"dt:{agent}|{a.group(2)}_{a.group(3)}{a.group(4)}")
    return keys


def merge_wrapped_headers(paras: list[str]) -> list[str]:
    """Join a recording-filename header that Word wrapped over two paragraphs."""
    out, i = [], 0
    while i < len(paras):
        line = paras[i]
        cue = re.search(r"recording|audio clip|data/audio", line, re.I)
        if (cue and not MEDIA_RE.search(line) and i + 1 < len(paras)
                and MEDIA_RE.search(paras[i + 1]) and len(paras[i + 1]) < 80
                and not re.search(r"[:：]", paras[i + 1])):
            out.append(line + paras[i + 1])
            i += 2
        else:
            out.append(line)
            i += 1
    return out


def load_calls(path: Path) -> list[Call]:
    """Split a docx into calls at lines naming a recording; filename keys apply if only one."""
    paras = [p.text for p in Document(str(path)).paragraphs if p.text.strip()]
    paras = merge_wrapped_headers(paras)
    calls: list[Call] = []
    cur: Call | None = None
    for line in paras:
        keys = keys_from_text(line) if (MEDIA_RE.search(line) or UUID_RE.search(line)) else set()
        if keys:
            if cur is not None and not cur.lines and not cur.keys:
                cur.keys = keys  # header wrapped over two paragraphs: reuse the empty call
                cur.source = f"{path.name}#{len(calls)}"
            else:
                cur = Call(f"{path.name}#{len(calls) + 1}", keys)
                calls.append(cur)
            continue
        if cur is None:
            cur = Call(path.name, set())
            calls.append(cur)
        cur.lines.append(line)
    if not calls:
        calls.append(Call(path.name, set()))
    if any(c.keys for c in calls):  # drop stray header fragments (wrapped filename line)
        calls = [c for c in calls if c.keys or len(c.lines) > 2]
    name_keys = keys_from_text(path.name)
    if len(calls) == 1:
        calls[0].keys |= name_keys
    return calls


AGENT_LABELS = {"CS"}
_LABEL_RE = re.compile(r"^\s*([^\s:：()（）]{1,10})\s*[:：]\s*")
_BACKCHANNEL_FULL_RE = re.compile(r"[（(]\s*([^\s:：()（）]{1,10})\s*[:：]\s*([^()（）]*)[）)]")


def role_of(label: str) -> str:
    """'agent' for the call-centre agent label (CS), else 'customer'."""
    return "agent" if label.strip().upper() in AGENT_LABELS else "customer"


def reference_segments(lines: list[str]) -> list[tuple[str, str]]:
    """Split ground truth into (role, text) segments; inline '(黃: 係。)' back-channels become
    their own segment with the inner speaker's role. Labels and the audio-link line are dropped."""
    segs: list[tuple[str, str]] = []
    role = "customer"
    for line in lines:
        if line.lstrip().lower().startswith("audio clip"):
            continue
        m = _LABEL_RE.match(line)
        if m:
            role = role_of(m.group(1))
            line = line[m.end():]
        pos = 0
        for b in _BACKCHANNEL_FULL_RE.finditer(line):
            segs.append((role, line[pos:b.start()]))
            segs.append((role_of(b.group(1)), b.group(2)))
            pos = b.end()
        segs.append((role, line[pos:]))
    return segs


def reference_text(lines: list[str]) -> str:
    """Drop labels and the audio-link line; keep words of '(CS: 係。)' back-channels."""
    return " ".join(text for _, text in reference_segments(lines))


def hypothesis_text(lines: list[str], strip_speakers: bool = False) -> str:
    """Drop Status/Model/Accuracy lines (timestamps are removed in normalize)."""
    out = [l for l in lines if not META_RE.match(l)]
    if strip_speakers:
        out = [SPEAKER_RE.sub("", l) for l in out]
    return " ".join(out)


def collect(path: Path) -> list[Call]:
    files = [path] if path.is_file() else sorted(path.glob("*.docx"))
    calls: list[Call] = []
    for f in files:
        if f.name.startswith("~$"):
            continue
        calls.extend(load_calls(f))
    return calls


def pair_calls(hyps: list[Call], refs: list[Call]) -> tuple[list[tuple[Call, Call]], list[Call], list[Call]]:
    """Pair by shared key (uuid preferred). Returns (pairs, unmatched_hyps, unmatched_refs)."""
    pairs, used = [], set()
    unmatched_h = []
    for h in hyps:
        match = None
        for prefix in ("uuid:", "dt:"):
            hk = {k for k in h.keys if k.startswith(prefix)}
            for i, r in enumerate(refs):
                if i not in used and any(_key_eq(a[len(prefix):], b[len(prefix):]) if prefix == "uuid:" else a == b
                                         for a in hk for b in r.keys if b.startswith(prefix)):
                    match = i
                    break
            if match is not None:
                break
        if match is None:
            unmatched_h.append(h)
        else:
            used.add(match)
            pairs.append((h, refs[match]))
    return pairs, unmatched_h, [r for i, r in enumerate(refs) if i not in used]


# --------------------------------------------------------------------------- scoring
@dataclass
class Score:
    ref_len: int
    hyp_len: int
    sub: int
    dele: int
    ins: int
    longest_del: int
    longest_del_pos: float | None
    alignment: str
    chunks: list = field(default_factory=list)  # (type, ref_start, ref_end, hyp_start, hyp_end)

    @property
    def errors(self) -> int:
        return self.sub + self.dele + self.ins

    @property
    def cer(self) -> float:
        return self.errors / self.ref_len if self.ref_len else float("nan")


def score_tokens(ref_tokens: list[str], hyp_tokens: list[str]) -> Score:
    """Score with jiwer on space-joined tokens (mixed-script MER-style CER)."""
    if not ref_tokens:
        return Score(0, len(hyp_tokens), 0, 0, len(hyp_tokens), 0, None, "")
    ref_s = " ".join(ref_tokens)
    hyp_s = " ".join(hyp_tokens) if hyp_tokens else ""
    out = jiwer.process_words(ref_s, hyp_s)
    longest, pos = 0, None
    for chunk in out.alignments[0]:
        if chunk.type == "delete":
            n = chunk.ref_end_idx - chunk.ref_start_idx
            if n > longest:
                longest, pos = n, chunk.ref_start_idx / len(ref_tokens)
    chunks = [(c.type, c.ref_start_idx, c.ref_end_idx, c.hyp_start_idx, c.hyp_end_idx)
              for c in out.alignments[0]]
    return Score(len(ref_tokens), len(hyp_tokens), out.substitutions, out.deletions,
                 out.insertions, longest, pos, jiwer.visualize_alignment(out), chunks)


# --------------------------------------------------------------------------- diagnostics
def token_outcomes(score: Score, n_ref: int) -> tuple[list[str], list[int]]:
    """Per reference token: 'ok'/'sub'/'del', plus insertions attributed to the nearest token."""
    status, ins = ["ok"] * n_ref, [0] * n_ref
    for typ, rs, re_, hs, he in score.chunks:
        if typ == "substitute":
            for i in range(rs, re_):
                status[i] = "sub"
        elif typ == "delete":
            for i in range(rs, re_):
                status[i] = "del"
        elif typ == "insert" and n_ref:
            ins[min(rs, n_ref - 1)] += he - hs
    return status, ins


def token_class(tok: str) -> str:
    """'english' (contains a-z), 'number' (digits only) or 'cjk'."""
    if any("a" <= c <= "z" for c in tok):
        return "english"
    return "number" if tok.isdigit() else "cjk"


def diagnostics(score: Score, ref_tokens: list[str], roles: list[str], bins: int = 10) -> dict:
    """Error profile by call position, by speaker role and by token class (all on ref tokens)."""
    n = len(ref_tokens)
    status, ins = token_outcomes(score, n)
    d_err, d_tok = [0] * bins, [0] * bins
    role = {r: {"tok": 0, "sub": 0, "del": 0, "ins": 0} for r in ("agent", "customer")}
    cls = {c: {"tok": 0, "sub": 0, "del": 0} for c in ("english", "number", "cjk")}
    for i, tok in enumerate(ref_tokens):
        b = min(bins - 1, i * bins // n)
        d_tok[b] += 1
        d_err[b] += (status[i] != "ok") + ins[i]
        r = role[roles[i]]
        r["tok"] += 1
        r["sub"] += status[i] == "sub"
        r["del"] += status[i] == "del"
        r["ins"] += ins[i]
        c = cls[token_class(tok)]
        c["tok"] += 1
        c["sub"] += status[i] == "sub"
        c["del"] += status[i] == "del"
    return {"decile_err": d_err, "decile_tok": d_tok, "role": role, "cls": cls}


_WIDE = re.compile(r"[a-z0-9]")


def _join_pieces(pieces: list[str]) -> str:
    """Join tokens: no space between CJK, a space around Latin/digit tokens."""
    out = ""
    for p in pieces:
        if out and (_WIDE.match(p[-1:]) or _WIDE.match(out[-1:])) and (_WIDE.match(p[:1]) or _WIDE.match(out[-1:])):
            out += " "
        out += p
    return out


def render_diff(score: Score, ref_tokens: list[str], hyp_tokens: list[str],
                roles: list[str], width: int = 60) -> str:
    """Readable inline diff: [ref→hyp] substitution, [-ref] deletion, [+hyp] insertion,
    one block per speaker turn (AGENT / CUSTOMER), wrapped at ~width characters."""
    lines: list[tuple[str, list[str]]] = []

    def add(role: str, piece: str) -> None:
        if not lines or lines[-1][0] != role:
            lines.append((role, []))
        lines[-1][1].append(piece)

    cur = roles[0] if roles else "customer"
    for typ, rs, re_, hs, he in score.chunks:
        if typ == "equal":
            for i in range(rs, re_):
                cur = roles[i]
                add(cur, ref_tokens[i])
        elif typ == "substitute":
            for k, i in enumerate(range(rs, re_)):
                cur = roles[i]
                add(cur, f"[{ref_tokens[i]}→{hyp_tokens[hs + k]}]")
        elif typ == "delete":
            for i in range(rs, re_):
                cur = roles[i]
                add(cur, f"[-{ref_tokens[i]}]")
        elif typ == "insert":
            for j in range(hs, he):
                add(cur, f"[+{hyp_tokens[j]}]")
    out = []
    for role, pieces in lines:
        label, cont = f"{role.upper():<9}| ", " " * 9 + "| "
        buf, first = [], True
        for p in pieces:
            if buf and len(_join_pieces(buf + [p])) > width:
                out.append((label if first else cont) + _join_pieces(buf))
                buf, first = [], False
            buf.append(p)
        if buf:
            out.append((label if first else cont) + _join_pieces(buf))
    return "\n".join(out) + "\n"


def _bigrams(tokens: list[str]) -> set[str]:
    cjk = [t for t in tokens if "\u3400" <= t[:1] <= "\u9fff"]
    return {a + b for a, b in zip(cjk, cjk[1:])}


def pair_sanity(ref_tokens: list[str], hyp_tokens: list[str]) -> tuple[float, str]:
    """(ref bigram coverage, warning). On the 5 known-good pairs coverage was 0.38-0.63 and on
    deliberately mismatched calls <= 0.22, so < 0.30 flags a suspect pairing; a hypothesis under
    half or over 1.6x the reference length is flagged too."""
    rb = _bigrams(ref_tokens)
    cov = len(rb & _bigrams(hyp_tokens)) / len(rb) if rb else 0.0
    ratio = len(hyp_tokens) / len(ref_tokens) if ref_tokens else 0.0
    warns = []
    if cov < 0.30:
        warns.append(f"low text overlap ({cov:.0%} of reference bigrams found)")
    if ratio < 0.5 or ratio > 1.6:
        warns.append(f"length ratio {ratio:.2f}")
    return cov, "; ".join(warns)


def pairs_from_csv(path: Path, hyps: list["Call"], refs: list["Call"]):
    """Manual pairing: CSV with columns hyp,ref (file names, or 'file#N' for multi-call docx).
    Returns (pairs, error messages). Overrides ID-based pairing for the listed files."""
    def find(calls, name):
        hits = [c for c in calls if c.source == name or c.source.split("#")[0] == name
                or c.source == f"{name}#1"]
        return hits[0] if len(hits) == 1 else None
    pairs, errors = [], []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, rec in enumerate(csv.DictReader(f), start=2):
            h, r = find(hyps, rec.get("hyp", "").strip()), find(refs, rec.get("ref", "").strip())
            if h is None or r is None:
                errors.append(f"{path.name} line {n}: cannot find unique call for {rec}")
            else:
                pairs.append((h, r))
    return pairs, errors


@dataclass
class Repeat:
    """A passage the hypothesis says twice: the later copy is the suspected loop."""
    first_start: int
    start: int          # token index of the later copy
    length: int         # tokens
    text: str


def find_repeats(tokens: list[str], min_len: int = 10) -> list[Repeat]:
    """Find maximal repeated token runs (>= min_len tokens, non-overlapping copies).

    O(n^2) longest-common-extension DP. Longest runs win; a token is flagged as an
    "extra" copy at most once, so repeated-three-times passages yield two Repeats.
    """
    n = len(tokens)
    found: list[tuple[int, int, int]] = []
    nxt = [0] * (n + 2)  # L[i+1][*]
    for i in range(n - 1, -1, -1):
        cur = [0] * (n + 2)
        for j in range(n - 1, i, -1):
            if tokens[i] == tokens[j]:
                cur[j] = nxt[j + 1] + 1
        for j in range(i + 1, n):
            ln = cur[j]
            if ln >= min_len and (i == 0 or tokens[i - 1] != tokens[j - 1]):
                found.append((i, j, min(ln, j - i)))
        nxt = cur
    found.sort(key=lambda t: -t[2])
    taken = [False] * n
    out: list[Repeat] = []
    for i, j, ln in found:
        if ln >= min_len and not any(taken[j:j + ln]):
            for k in range(j, j + ln):
                taken[k] = True
            out.append(Repeat(i, j, ln, "".join(tokens[j:j + ln])))
    return sorted(out, key=lambda r: r.start)


def remove_repeats(tokens: list[str], repeats: list[Repeat]) -> list[str]:
    drop = {k for r in repeats for k in range(r.start, r.start + r.length)}
    return [t for k, t in enumerate(tokens) if k not in drop]


@dataclass
class Row:
    name: str
    raw: Score
    mapped: Score
    nofill: Score
    primary: Score
    ent_p: float | None
    ent_r: float | None
    repeats: list = field(default_factory=list)
    hyp_len_tokens: int = 0
    dedup: Score | None = None
    ref_repeats: int = 0
    norm_ref: str = ""
    norm_hyp: str = ""
    variant: str = ""
    diag: dict = field(default_factory=dict)
    diff: str = ""
    coverage: float = 0.0
    pair_warning: str = ""


def norm_ref(segments: list[tuple[str, str]], **opts) -> tuple[str, list[str], list[str]]:
    """Normalize the reference segment by segment. Returns (text, tokens, role per token)."""
    parts, tokens, roles = [], [], []
    for role, text in segments:
        n = normalize(text, **opts)
        if n:
            parts.append(n)
            t = tokenize(n)
            tokens += t
            roles += [role] * len(t)
    return " ".join(parts), tokens, roles


def evaluate_pair(h: Call, r: Call, map_colloquial: bool, strip_hyp_speakers: bool,
                  drop_fillers: bool = False, repeat_min_tokens: int = 10) -> Row:
    segs = reference_segments(r.lines)
    hyp_in = hypothesis_text(h.lines, strip_hyp_speakers)
    variants = {
        "raw": {},
        "mapped": {"map_colloquial": True},
        "mapped_nofillers": {"map_colloquial": True, "drop_fillers": True},
    }
    data = {}
    for name, opts in variants.items():
        ref_s, ref_t, ref_roles = norm_ref(segs, **opts)
        hyp_s = normalize(hyp_in, **opts)
        hyp_t = tokenize(hyp_s)
        data[name] = (ref_s, ref_t, ref_roles, hyp_s, hyp_t, score_tokens(ref_t, hyp_t))
    variant = "mapped_nofillers" if drop_fillers else "mapped" if map_colloquial else "raw"
    p_ref, ref_tokens, ref_roles, p_hyp, hyp_tokens, primary = data[variant]
    raw, mapped, nofill = data["raw"][5], data["mapped"][5], data["mapped_nofillers"][5]
    ep, er = entity_scores(extract_entities(p_ref), extract_entities(p_hyp))
    repeats = find_repeats(hyp_tokens, repeat_min_tokens)
    dedup = score_tokens(ref_tokens, remove_repeats(hyp_tokens, repeats)) if repeats else None
    ref_reps = find_repeats(ref_tokens, repeat_min_tokens)
    # hypothesis repeats that the ground truth also repeats (at least half as long)
    ref_repeats = sum(any(x.length >= 0.5 * rp.length for x in ref_reps) for rp in repeats)
    cov, warn = pair_sanity(ref_tokens, hyp_tokens)
    return Row(r.source, raw, mapped, nofill, primary, ep, er, repeats, len(hyp_tokens), dedup,
               ref_repeats, p_ref, p_hyp, variant,
               diagnostics(primary, ref_tokens, ref_roles),
               render_diff(primary, ref_tokens, hyp_tokens, ref_roles), cov, warn)


def _num(x: float | None, digits: int = 6) -> float | str:
    """Numeric CSV cell: rounded float, or empty string when undefined."""
    if x is None or x != x:
        return ""
    return round(x, digits)


def _pct(x: float | str) -> str:
    """Console formatting of a CSV cell (fraction -> percent)."""
    return "" if x == "" else f"{x:.2%}"


CSV_FIELDS = ["file", "ref_tokens", "hyp_tokens", "cer_raw", "cer_mapped", "cer_mapped_nofillers",
              "substitutions",
              "deletions", "insertions", "longest_del_run", "longest_del_pos",
              "entity_precision", "entity_recall", "repeat_passages", "repeat_tokens",
              "cer_without_repeats", "repeat_impact_pts", "scored_variant"]
DIAG_FIELDS = (
    [f"err_rate_d{i:02d}" for i in range(1, 11)]
    + ["agent_ref_tokens", "agent_error_rate", "agent_deletion_rate",
       "customer_ref_tokens", "customer_error_rate", "customer_deletion_rate",
       "english_ref_tokens", "english_miss_rate", "number_ref_tokens", "number_miss_rate",
       "cjk_miss_rate", "ref_bigram_coverage", "pair_warning"]
)
CSV_FIELDS = CSV_FIELDS + DIAG_FIELDS


def _rate(num: int, den: int) -> float | str:
    return _num(num / den) if den else ""


def diag_cells(d: dict) -> dict:
    """Flatten a diagnostics dict (or a sum of them) into CSV cells."""
    out = {f"err_rate_d{i + 1:02d}": _rate(e, t)
           for i, (e, t) in enumerate(zip(d["decile_err"], d["decile_tok"]))}
    for role in ("agent", "customer"):
        r = d["role"][role]
        out[f"{role}_ref_tokens"] = r["tok"]
        out[f"{role}_error_rate"] = _rate(r["sub"] + r["del"] + r["ins"], r["tok"])
        out[f"{role}_deletion_rate"] = _rate(r["del"], r["tok"])
    for c in ("english", "number", "cjk"):
        x = d["cls"][c]
        if c != "cjk":
            out[f"{c}_ref_tokens"] = x["tok"]
        out[f"{c}_miss_rate"] = _rate(x["sub"] + x["del"], x["tok"])
    return out


def sum_diag(diags: list[dict]) -> dict:
    tot = {"decile_err": [0] * 10, "decile_tok": [0] * 10,
           "role": {r: {"tok": 0, "sub": 0, "del": 0, "ins": 0} for r in ("agent", "customer")},
           "cls": {c: {"tok": 0, "sub": 0, "del": 0} for c in ("english", "number", "cjk")}}
    for d in diags:
        for i in range(10):
            tot["decile_err"][i] += d["decile_err"][i]
            tot["decile_tok"][i] += d["decile_tok"][i]
        for k, v in d["role"].items():
            for f_, n in v.items():
                tot["role"][k][f_] += n
        for k, v in d["cls"].items():
            for f_, n in v.items():
                tot["cls"][k][f_] += n
    return tot


def row_to_csv(row: Row) -> dict:
    p = row.primary
    return {"file": row.name, "ref_tokens": p.ref_len, "hyp_tokens": p.hyp_len,
            "cer_raw": _num(row.raw.cer), "cer_mapped": _num(row.mapped.cer),
            "cer_mapped_nofillers": _num(row.nofill.cer),
            "substitutions": p.sub, "deletions": p.dele, "insertions": p.ins,
            "longest_del_run": p.longest_del, "longest_del_pos": _num(p.longest_del_pos),
            "entity_precision": _num(row.ent_p), "entity_recall": _num(row.ent_r),
            "repeat_passages": len(row.repeats),
            "repeat_tokens": sum(x.length for x in row.repeats),
            "cer_without_repeats": _num(row.dedup.cer if row.dedup else p.cer),
            "repeat_impact_pts": round((p.cer - row.dedup.cer) * 100, 2) if row.dedup else 0.0,
            "scored_variant": row.variant,
            **diag_cells(row.diag),
            "ref_bigram_coverage": _num(row.coverage, 3), "pair_warning": row.pair_warning}


def corpus_row(rows: list[Row]) -> dict:
    """Corpus CER = total errors / total reference tokens (not a mean of per-file CERs)."""
    def agg(attr: str) -> float:
        tot = sum(getattr(r, attr).ref_len for r in rows)
        return sum(getattr(r, attr).errors for r in rows) / tot if tot else float("nan")
    return {"file": "CORPUS", "ref_tokens": sum(r.primary.ref_len for r in rows),
            "hyp_tokens": sum(r.primary.hyp_len for r in rows),
            "cer_raw": _num(agg("raw")), "cer_mapped": _num(agg("mapped")),
            "cer_mapped_nofillers": _num(agg("nofill")),
            "substitutions": sum(r.primary.sub for r in rows),
            "deletions": sum(r.primary.dele for r in rows),
            "insertions": sum(r.primary.ins for r in rows),
            "longest_del_run": max((r.primary.longest_del for r in rows), default=0),
            "longest_del_pos": "", "entity_precision": "", "entity_recall": "",
            "repeat_passages": sum(len(r.repeats) for r in rows),
            "repeat_tokens": sum(x.length for r in rows for x in r.repeats),
            "cer_without_repeats": _num(
                sum((r.dedup or r.primary).errors for r in rows)
                / max(1, sum(r.primary.ref_len for r in rows))),
            "repeat_impact_pts": "",
            "scored_variant": rows[0].variant if rows else "",
            **diag_cells(sum_diag([r.diag for r in rows])),
            "ref_bigram_coverage": "", "pair_warning": ""}


def mean_row(rows: list[Row]) -> dict:
    """Unweighted mean of the per-call CERs (macro average; the CORPUS row is the micro average)."""
    def m(attr: str) -> float | str:
        return _num(sum(getattr(r, attr).cer for r in rows) / len(rows)) if rows else ""
    base = {k: "" for k in CSV_FIELDS}
    base.update({"file": "MEAN_PER_CALL", "cer_raw": m("raw"), "cer_mapped": m("mapped"),
                 "cer_mapped_nofillers": m("nofill"),
                 "scored_variant": rows[0].variant if rows else ""})
    return base


def mapping_listing() -> str:
    """Human-readable list of every normalization mapping."""
    lines = ["Variant unification (always on):"]
    lines += [f"  {a} -> {b}" for a, b in VARIANTS.items()]
    lines += ["", "Colloquial -> written (--map-colloquial; longest key first):"]
    lines += [f"  {a} -> {b}" for a, b in sorted(COLLOQUIAL.items(), key=lambda kv: -len(kv[0]))]
    lines += ["", "English -> Chinese (--map-colloquial; whole tokens only):"]
    lines += [f"  {a} -> {b}" for a, b in ENGLISH.items()]
    lines += ["", f"Filler particles deleted (--drop-fillers): {' '.join(FILLERS)}"]
    lines += ["", "Context rules (--map-colloquial):"]
    lines += [f"  {desc}" for _, _, desc in CONTEXT_RULES]
    return "\n".join(lines)


def safe_name(s: str) -> str:
    return re.sub(r"[^\w.-]+", "_", s)[:120]


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-mappings", action="store_true", help="print all mappings and exit")
    ap.add_argument("--hyp-dir", type=Path, help="model-output .docx file or directory")
    ap.add_argument("--ref-dir", type=Path, help="ground-truth .docx file or directory")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--map-colloquial", action="store_true",
                    help="use colloquial->written mapping for alignment files / S-D-I / entities "
                         "(both CER variants are always written to the CSV)")
    ap.add_argument("--drop-fillers", action="store_true",
                    help="delete filler particles on both sides for S/D/I, alignment and entities "
                         "(cer_mapped_nofillers is always written to the CSV)")
    ap.add_argument("--repeat-min-tokens", type=int, default=10,
                    help="min length (tokens) of a repeated hypothesis passage to flag (default 10)")
    ap.add_argument("--gt-verified", action="store_true",
                    help="ground truth is human-verified: repeats it lacks are counted as model errors "
                         "(replaces the 'verify in the audio' note)")
    ap.add_argument("--pairs", type=Path,
                    help="CSV with columns hyp,ref (file names) to pair calls manually, e.g. when a "
                         "recording ID is corrupted; these override ID-based pairing")
    ap.add_argument("--skip-suspect", action="store_true",
                    help="do not score pairs flagged as suspect (low text overlap / length ratio)")
    ap.add_argument("--strip-speakers-hyp", action="store_true",
                    help="also strip 'XX:' speaker labels from the hypothesis")
    args = ap.parse_args(argv)
    if args.list_mappings:
        print(mapping_listing())
        return 0
    if not (args.hyp_dir and args.ref_dir and args.out):
        ap.error("--hyp-dir, --ref-dir and --out are required")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    hyps, refs = collect(args.hyp_dir), collect(args.ref_dir)
    manual: list = []
    if args.pairs:
        manual, errs = pairs_from_csv(args.pairs, hyps, refs)
        for e in errs:
            log.error(e)
        if errs:
            return 1
        used_h, used_r = {id(h) for h, _ in manual}, {id(r) for _, r in manual}
        hyps = [h for h in hyps if id(h) not in used_h]
        refs = [r for r in refs if id(r) not in used_r]
    pairs, un_h, un_r = pair_calls(hyps, refs)
    pairs = manual + pairs
    for h in un_h:
        log.warning("UNMATCHED hypothesis: %s keys=%s", h.source, sorted(h.keys))
    for r in un_r:
        log.warning("UNMATCHED reference: %s keys=%s", r.source, sorted(r.keys))
    if not pairs:
        log.error("No pairs found.")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for h, r in pairs:
        row = evaluate_pair(h, r, args.map_colloquial, args.strip_speakers_hyp,
                            args.drop_fillers, args.repeat_min_tokens)
        if row.pair_warning:
            log.warning("SUSPECT PAIR %s <-> %s: %s", h.source, r.source, row.pair_warning)
            if args.skip_suspect:
                continue
        rows.append(row)
        (args.out / f"diff_{safe_name(r.source)}.txt").write_text(row.diff, encoding="utf-8")
        (args.out / f"alignment_{safe_name(r.source)}.txt").write_text(
            row.primary.alignment, encoding="utf-8")
        (args.out / f"normalized_{safe_name(r.source)}.txt").write_text(
            f"REF (normalized, {len(tokenize(row.norm_ref))} tokens):\n{row.norm_ref}\n\n"
            f"HYP (normalized, {len(tokenize(row.norm_hyp))} tokens):\n{row.norm_hyp}\n",
            encoding="utf-8")

    if not rows:
        log.error("No pairs left to score.")
        return 1
    (args.out / "mappings.txt").write_text(mapping_listing(), encoding="utf-8")
    out_rows = [row_to_csv(r) for r in rows] + [corpus_row(rows), mean_row(rows)]
    with open(args.out / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(out_rows)

    print(f"{'file':<44}{'ref':>6}{'hyp':>6}{'CERraw':>9}{'CERmap':>9}{'CERnofil':>9}{'S':>5}{'D':>5}{'I':>5}"
          f"{'maxDel':>8}{'entP':>8}{'entR':>8}")
    for o in out_rows:
        print(f"{o['file'][:43]:<44}{o['ref_tokens']:>6}{o['hyp_tokens']:>6}{_pct(o['cer_raw']):>9}"
              f"{_pct(o['cer_mapped']):>9}{_pct(o['cer_mapped_nofillers']):>9}{o['substitutions']:>5}{o['deletions']:>5}{o['insertions']:>5}"
              f"{o['longest_del_run']:>8}{_pct(o['entity_precision']):>8}{_pct(o['entity_recall']):>8}")
    c = out_rows[-2]
    print("\nBY SPEAKER (ref tokens): "
          f"agent {c['agent_ref_tokens']} tok, error {_pct(c['agent_error_rate'])}, deleted {_pct(c['agent_deletion_rate'])} | "
          f"customer {c['customer_ref_tokens']} tok, error {_pct(c['customer_error_rate'])}, deleted {_pct(c['customer_deletion_rate'])}")
    print(f"BY TOKEN TYPE (missed = sub+del): English {c['english_ref_tokens']} tok {_pct(c['english_miss_rate'])} | "
          f"numbers {c['number_ref_tokens']} tok {_pct(c['number_miss_rate'])} | CJK {_pct(c['cjk_miss_rate'])}")
    print("ERROR RATE BY CALL POSITION (deciles, corpus): "
          + " ".join(_pct(c[f"err_rate_d{i:02d}"]) or "-" for i in range(1, 11)))
    for row in rows:
        if row.repeats:
            hl = max(1, row.hyp_len_tokens)
            print(f"\nREPEATED PASSAGES in {row.name}: {len(row.repeats)} passage(s), "
                  f"{sum(x.length for x in row.repeats)} tokens ({sum(x.length for x in row.repeats) / hl:.1%} of hypothesis)")
            for x in row.repeats:
                print(f"  at {x.start / hl:.0%} of hyp, {x.length} tokens, first said at {x.first_start / hl:.0%}: "
                      f"{x.text[:60]}{'...' if len(x.text) > 60 else ''}")
            d = row.dedup
            if row.ref_repeats < len(row.repeats) and args.gt_verified:
                print("  NOTE: ground truth is verified, so these repeats are model errors "
                      "(the primary CER already includes them).")
            elif row.ref_repeats < len(row.repeats):
                print(f"  NOTE: the ground truth repeats only {row.ref_repeats} of these "
                      f"{len(row.repeats)} passage(s). Either the model looped or the ground "
                      "truth omits a real repetition: verify in the audio. If it is real, fix the "
                      "ground truth, and treat the 'without repeat' CER below as not applicable.")
            print(f"  IMPACT: CER {row.primary.cer:.2%} -> {d.cer:.2%} without the repeat "
                  f"({(row.primary.cer - d.cer) * 100:.2f} pts); "
                  f"insertions {row.primary.ins} -> {d.ins}, deletions {row.primary.dele} -> {d.dele}")
    print(f"\nWrote {args.out / 'results.csv'} and {len(rows)} diff/alignment/normalized file set(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
