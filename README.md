# Cantonese ASR evaluation

Scores model transcriptions (`.docx`) against human-verified ground truth (`.docx`):
CER (raw and with Cantonese/English mappings), substitutions/deletions/insertions,
longest deleted run, entity accuracy and repeated-passage detection.
Results so far: [RESULTS.md](RESULTS.md).

> The ground-truth and transcript `.docx` files (`data/`) and the generated outputs (`results/`) contain
> customer call content and are deliberately **not** in this repository (see `.gitignore`).
> Put your own files in `data/groundtruth/` and `data/transcription/` to run it.

## Layout

| Path | Contents |
|---|---|
| `eval_cantonese_asr.py` | the evaluation script |
| `tests/` | pytest unit tests |
| `data/groundtruth/` | human ground-truth `.docx` files |
| `data/transcription/` | model-output `.docx` files |
| `results/all/` | latest outputs: `results.csv`, alignments, normalized text |
| `docs/mappings.txt` | every normalization mapping (regenerate with `--list-mappings`) |
| `docs/proposed_mappings.md` | the approved mapping proposal (history) |
| `requirements.txt`, `requirements-dev.txt` | runtime and test dependencies |

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

## Run

All calls in the data folders:

```
.venv/bin/python eval_cantonese_asr.py --hyp-dir data/transcription --ref-dir data/groundtruth \
    --out results/all --map-colloquial --gt-verified
```

One pair: pass the two `.docx` files instead of folders. Calls are paired by the recording ID in
the filename header (a look-alike character from copy/paste is tolerated), so file names do not
need to match. Unmatched files are logged as warnings and never paired.

| Option | Effect |
|---|---|
| `--map-colloquial` | apply the Cantonese/English/date mappings; raw and mapped CER are always both in the CSV |
| `--drop-fillers` | delete filler particles on both sides for the S/D/I counts, alignment and entities (`cer_mapped_nofillers` is always in the CSV) |
| `--gt-verified` | treat repeated passages missing from the ground truth as model errors |
| `--repeat-min-tokens N` | minimum length of a repeated passage to flag (default 10) |
| `--pairs FILE.csv` | pair calls manually: CSV with columns `hyp,ref` (file names, or `file#N` for a multi-call docx). Use when a recording ID is corrupted; overrides ID pairing for the listed files |
| `--skip-suspect` | leave out pairs flagged as suspect (low text overlap or odd length ratio). Suspect pairs are always warned about and flagged in the CSV `pair_warning` column |
| `--strip-speakers-hyp` | also strip `XX:` speaker labels from the model output |
| `--list-mappings` | print every mapping and exit |

Outputs in `--out`:

| File | Contents |
|---|---|
| `results.csv` | one row per call, a `CORPUS` row (micro average) and a `MEAN_PER_CALL` row (macro average). Rates are numeric fractions (`0.5135` = 51.35%); `scored_variant` says whether the S/D/I columns are raw, mapped or mapped_nofillers |
| `diff_<call>.txt` | readable inline diff per speaker turn: `[ref→hyp]` substitution, `[-x]` deletion, `[+x]` insertion |
| `alignment_<call>.txt` | jiwer word alignment |
| `normalized_<call>.txt` | cleaned reference and hypothesis text |
| `mappings.txt` | every mapping in effect |

Extra `results.csv` columns: `err_rate_d01..d10` (error rate per tenth of the call), `agent_*` / `customer_*`
(reference tokens, error rate, deletion rate; agent = label `CS`), `english_miss_rate`, `number_miss_rate`,
`cjk_miss_rate` (substitutions + deletions over reference tokens of that type), `ref_bigram_coverage` and
`pair_warning` (pairing sanity check).

## Test

```
.venv/bin/python -m pytest -q
```
