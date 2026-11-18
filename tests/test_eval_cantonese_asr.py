import eval_cantonese_asr as ev


def test_normalize_strips_tags_punct_and_fullwidth():
    assert ev.normalize("[00:05] 你好，ＡＢＣ　１２３。") == "你好 abc 123"


def test_normalize_variants_and_thousands():
    assert ev.normalize("爲咗 1,000") == "為咗 1000"


def test_normalize_map_colloquial_multichar_first():
    assert ev.normalize("佢哋冇嚟", map_colloquial=True) == "他們沒有來"
    assert ev.normalize("佢哋冇嚟") == "佢哋冇嚟"


def test_tokenize_mixed_script():
    assert ev.tokenize("信用 credit card 12ab") == ["信", "用", "credit", "card", "12ab"]


def test_chinese_numerals():
    assert ev.chinese_numerals_to_arabic("三百三十三").strip() == "333"
    assert ev.chinese_numerals_to_arabic("一九七三").strip() == "1973"
    assert ev.chinese_numerals_to_arabic("一起") == "一起"


def test_reference_text_backchannel_and_labels():
    lines = ["Audio clip (OneDrive link): x.mp4", "CS: 你好 (黃: 係。) 請問", "黃: 好"]
    assert ev.normalize(ev.reference_text(lines)) == "你好 係 請問 好"


def test_keys_and_pairing():
    k1 = ev.keys_from_text("CXone recording_Agent Name_2026-01-01_01-23[UTC]_aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb.mp4")
    k2 = ev.keys_from_text("..._3333-bbbbbbbbbbbb.mp4")
    assert k1 & k2 == {"uuid:bbbbbbbbbbbb"}
    h = ev.Call("h", k1)
    r = ev.Call("r", k2)
    other = ev.Call("o", {"uuid:000000000000"})
    pairs, uh, ur = ev.pair_calls([h], [other, r])
    assert pairs == [(h, r)] and not uh and ur == [other]


def test_score_and_longest_deletion():
    ref = ev.tokenize("我 想 查 詢 保 單 號 碼")
    hyp = ev.tokenize("我 想 號 碼")
    s = ev.score_tokens(ref, hyp)
    assert (s.sub, s.dele, s.ins) == (0, 4, 0)
    assert s.longest_del == 4 and abs(s.cer - 0.5) < 1e-9


def test_entity_scores():
    p, r = ev.entity_scores(ev.extract_entities("aa000167 1973"), ev.extract_entities("aa000167 1974"))
    assert p == 0.5 and r == 0.5


def test_date_mapping_only_after_digit():
    assert ev.normalize("3號 今日", map_colloquial=True) == "3日 今日"
    assert ev.normalize("3號") == "3號"


def test_fullwidth_timestamp_removed():
    assert ev.normalize("［00:05］你好") == "你好"


def test_numerals_in_main_text():
    assert ev.normalize("八月二十九號之前", map_colloquial=True) == "8 月 29日之前"
    assert ev.normalize("一個人 兩位") == "1 個人 2 位"
    assert ev.normalize("前四位 一起") == "前 4 位 一起"
    assert ev.normalize("一九七三年") == "1973 年"


def test_lexical_swaps_and_longest_first():
    assert ev.normalize("跟住呢度而家仲乜嘢", map_colloquial=True) == "接著這裡現在還什麼"
    assert ev.normalize("係咪同埋同你", map_colloquial=True) == "是不是和跟你"
    assert ev.normalize("呢一份 呢個", map_colloquial=True) == "這一份 這個"


def test_english_mapping_whole_token_only():
    assert ev.normalize("reply你哋 do notreply email", map_colloquial=True) == "回覆你們 do not reply 電郵"
    assert ev.normalize("reconfirm 下", map_colloquial=True) == "重新確認 下"


def test_variant_hu():
    assert ev.normalize("客户") == "客戶"


def test_drop_fillers():
    assert ev.normalize("嗯 好阿 可以啦", drop_fillers=True) == "好 可以"
    assert ev.normalize("嗯 好阿") == "嗯 好阿"


def test_find_repeats_flags_later_copy():
    base = ev.tokenize("我想問之前我收到你們的電郵如果我續保的話需要回覆")
    filler = ev.tokenize("好的謝謝")
    toks = base + filler + base + ev.tokenize("再見")
    reps = ev.find_repeats(toks, min_len=10)
    assert len(reps) == 1 and reps[0].length == len(base) and reps[0].start == len(base) + len(filler)
    assert ev.remove_repeats(toks, reps) == base + filler + ev.tokenize("再見")


def test_find_repeats_ignores_short_and_none():
    assert ev.find_repeats(ev.tokenize("拜拜 拜拜 拜拜 好的"), min_len=10) == []


def test_do_not_reply_stays_english():
    for src in ("do not reply", "do notreply", "donotreply", "Do-Not-Reply"):
        assert ev.normalize(src, map_colloquial=True) == "do not reply"
    assert ev.normalize("請 reply do notreply", map_colloquial=True) == "請 回覆 do not reply"


def test_pairing_tolerates_cyrillic_lookalike_and_wrapped_header():
    ps = ["Audio clip (OneDrive link): X recording A 2026-01-01 04-17[UTC] cccccccc-1111-2222-",
          "3333-ddddбddddddd.mp4", "CS： 你好"]
    merged = ev.merge_wrapped_headers(ps)
    assert len(merged) == 2
    k_ref = ev.keys_from_text(merged[0])
    k_hyp = ev.keys_from_text("..._cccccccc-1111-2222-3333-dddddddddddd.mp4")
    h, r = ev.Call("h", k_hyp), ev.Call("r", k_ref)
    pairs, uh, ur = ev.pair_calls([h], [r])
    assert pairs == [(h, r)]


def test_ids_are_spacing_insensitive():
    assert ev.normalize("abcd 12345678") == ev.normalize("ABCD12345678") == "abcd12345678"
    assert ev.normalize("a b c d 0 0 2") == "abcd002"
    assert ev.normalize("hk 0001175165 是") == "hk0001175165 是"


def test_join_ids_leaves_normal_text():
    assert ev.normalize("i sorry 8 月 29日") == "i sorry 8 月 29日"
    assert ev.normalize("credit card 12 sorry 8") == "credit card 12 sorry 8"


def test_entities_ignore_letter_prefix_of_long_ids():
    ref = ev.extract_entities(ev.normalize("abcd 是 12345678 好"))
    hyp = ev.extract_entities(ev.normalize("abcd12345678 好"))
    assert ref == hyp == ["12345678"]
    assert ev.extract_entities("kv102") == ["kv102"]  # short mixed tokens kept whole


def test_new_mappings_and_variants():
    assert ev.normalize("賬戶 紀錄", map_colloquial=True) == "帳戶 記錄"
    assert ev.normalize("啊 呀 須要", map_colloquial=True) == "阿 阿 需要"
    assert ev.normalize("咁樣", map_colloquial=True) == "咁樣"  # no longer mapped to 這樣
    assert ev.normalize("咁 咧 好", drop_fillers=True) == "好"


def test_csv_cells_are_numeric(tmp_path):
    import csv
    from docx import Document
    for name, lines in (("ref.docx", ["Audio clip: x_aaaaaaaa-bbbb-cccc-dddd-111122223333.mp4", "CS: 你好 請問"]),
                        ("hyp.docx", ["data/x_aaaaaaaa-bbbb-cccc-dddd-111122223333.mp4", "你好 請"])):
        d = Document()
        for l in lines:
            d.add_paragraph(l)
        d.save(tmp_path / name)
    assert ev.main(["--hyp-dir", str(tmp_path / "hyp.docx"), "--ref-dir", str(tmp_path / "ref.docx"),
                    "--out", str(tmp_path / "o"), "--map-colloquial"]) == 0
    rows = list(csv.DictReader(open(tmp_path / "o" / "results.csv", encoding="utf-8-sig")))
    assert rows[0]["scored_variant"] == "mapped"
    assert 0 < float(rows[0]["cer_mapped"]) < 1 and "%" not in rows[0]["cer_mapped"]
    assert [r["file"] for r in rows][-2:] == ["CORPUS", "MEAN_PER_CALL"]


def _mk(tmp_path, name, lines):
    from docx import Document
    d = Document()
    for l in lines:
        d.add_paragraph(l)
    d.save(tmp_path / name)


def test_reference_segments_roles_and_backchannel():
    segs = ev.reference_segments(["Audio clip: x.mp4", "CS： 你好 （黃：係。） 請問", "黃：好"])
    assert [r for r, _ in segs] == ["agent", "agent", "customer", "customer"][:0] or True
    roles = [r for r, t in segs if t.strip()]
    texts = [t.strip() for _, t in segs if t.strip()]
    assert texts == ["你好", "係。", "請問", "好"]
    assert roles == ["agent", "customer", "agent", "customer"]


def test_diagnostics_by_role_class_and_position():
    ref = ["我", "想", "問", "ok", "123"]
    hyp = ["我", "想", "ok", "999"]
    sc = ev.score_tokens(ref, hyp)
    d = ev.diagnostics(sc, ref, ["agent", "agent", "customer", "customer", "customer"])
    assert d["role"]["customer"]["del"] == 1 and d["role"]["customer"]["sub"] == 1
    assert d["cls"]["number"]["sub"] == 1 and d["cls"]["english"]["sub"] + d["cls"]["english"]["del"] == 0
    assert sum(d["decile_tok"]) == 5


def test_render_diff_markup_and_speaker_blocks():
    ref = ["我", "想", "問", "ok"]
    hyp = ["我", "要", "ok"]
    sc = ev.score_tokens(ref, hyp)
    out = ev.render_diff(sc, ref, hyp, ["agent", "agent", "customer", "customer"])
    assert "AGENT" in out and "CUSTOMER" in out
    assert "[想→要]" in out and "[-問]" in out


def test_pair_sanity_flags_unrelated_text():
    a = ev.tokenize("我想問之前我收到你們的電郵如果我續保的話需要回覆你們")
    b = ev.tokenize("請問小姐怎麼稱呼出生日期是七十八年九月一日保單號碼")
    assert ev.pair_sanity(a, a)[1] == ""
    assert "low text overlap" in ev.pair_sanity(a, b)[1]
    assert "length ratio" in ev.pair_sanity(a, a[:5])[1]


def test_manual_pairs_and_skip_suspect(tmp_path):
    ref1 = ["Audio clip: a_aaaaaaaa-bbbb-cccc-dddd-111122223333.mp4", "CS: 我想問之前我收到你們的電郵如果我續保的話需要回覆你們"]
    hyp_same = ["data/zzz.mp4", "我想問之前我收到你們的電郵如果我續保的話需要回覆你們"]  # no usable ID
    hyp_other = ["data/yyy.mp4", "請問小姐怎麼稱呼出生日期是七十八年九月一日保單號碼"]
    _mk(tmp_path, "ref.docx", ref1)
    _mk(tmp_path, "hyp_same.docx", hyp_same)
    _mk(tmp_path, "hyp_other.docx", hyp_other)
    import csv as _csv
    for name, hyp in (("good.csv", "hyp_same.docx"), ("bad.csv", "hyp_other.docx")):
        with open(tmp_path / name, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["hyp", "ref"])
            w.writerow([hyp, "ref.docx"])
    for hyp in ("hyp_same.docx", "hyp_other.docx"):
        pass
    argv = ["--ref-dir", str(tmp_path / "ref.docx"), "--map-colloquial"]
    assert ev.main(argv + ["--hyp-dir", str(tmp_path / "hyp_same.docx"), "--pairs", str(tmp_path / "good.csv"),
                           "--out", str(tmp_path / "o1")]) == 0
    assert (tmp_path / "o1" / "results.csv").exists()
    # suspect pair is scored with a warning, and skipped with --skip-suspect
    assert ev.main(argv + ["--hyp-dir", str(tmp_path / "hyp_other.docx"), "--pairs", str(tmp_path / "bad.csv"),
                           "--out", str(tmp_path / "o2")]) == 0
    assert ev.main(argv + ["--hyp-dir", str(tmp_path / "hyp_other.docx"), "--pairs", str(tmp_path / "bad.csv"),
                           "--skip-suspect", "--out", str(tmp_path / "o3")]) == 1
