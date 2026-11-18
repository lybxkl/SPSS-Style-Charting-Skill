# -*- coding: utf-8 -*-
"""Offline unit tests for the coding layer (stdlib unittest only).

One test class per defect family from docs/skill-audit/part-B-coding.md:

- ``TestMakeCodingSheetCLI``: the P0 funnel (B7) plus B6/B10/B12/B13/B14.
- ``TestCodingFunctions``: the extractor rules (B1/B2/B3/B4/B5/B8/B9/B11).
- ``TestAnalysisUtils`` / ``TestAnalysisIO``: A1/A2/A6 and the testable P2s.
- ``TestSpssSyntax``: S1/S2/S3 and the testable P2s.

Everything runs against a temporary workspace; no network and no real corpus.
"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempCase, run, write_csv, read_csv, make_text_pdf

import contextlib
import io
import json
import shutil

import numpy as np
import pandas as pd

import analysis_utils as au
import csv_to_spss_syntax as c2s
import make_coding_sheet as mcs

# A body long enough to pass the default --min-chars 100 filter.
BODY = "本案系一起故意伤害案件，" * 12

# A legal document with a court header, a docket number, quoted trial language
# in the body and the dispositive language at the very end.
LEGAL_TEXT = (
    "黑龙江省哈尔滨市中级人民法院\n"
    "刑事判决书\n"
    "（2021）黑01刑初12号\n"
    "公诉机关黑龙江省哈尔滨市人民检察院。\n"
    "被告人张某某，男，1980年生。\n"
    "本院认为，被告人张某某故意伤害他人身体，致人轻伤，其行为已构成故意伤害罪。\n"
    "被告人未赔偿被害人损失，亦未取得谅解。\n"
    "依照《中华人民共和国刑法》第二百三十四条之规定，判决如下：\n"
    "一、被告人张某某犯故意伤害罪，判处有期徒刑一年。\n"
    "二、驳回附带民事诉讼原告人的诉讼请求。\n"
)


class TestMakeCodingSheetCLI(TempCase):
    """End-to-end behaviour of make_coding_sheet.py."""

    def setUp(self):
        super().setUp()
        self.corpus = self.p("corpus")
        os.makedirs(self.corpus, exist_ok=True)
        self.out = self.p("out")

    # -- helpers -----------------------------------------------------------
    def _doc(self, rel, text):
        path = os.path.join(self.corpus, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _run(self, *args):
        return run("make_coding_sheet.py", "--root", self.corpus,
                   "--out", self.out, *args, cwd=self.tmp)

    def _rows(self):
        return read_csv(os.path.join(self.out, "coding_sheet.csv"))

    def _skipped(self):
        return read_csv(os.path.join(self.out, "skipped_documents.csv"))

    def _flow(self):
        return read_csv(os.path.join(self.out, "sample_flow.csv"))

    def _jsonl(self):
        path = os.path.join(self.out, "coding_sheet.jsonl")
        with open(path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    # -- B7: every exclusion reaches skipped_documents.csv ------------------
    def test_audit_all_invalid_exits_2_and_logs_every_skip(self):
        self._doc("a.txt", BODY)
        self._doc("b.txt", BODY)
        audit = self.p("audit.csv")
        write_csv(audit, ["rel_path", "status"],
                  [["a.txt", "invalid"], ["b.txt", "invalid"]])
        proc = self._run("--audit", audit, "--min-chars", "1")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("no row with status=valid", proc.stderr)
        skipped = self._skipped()
        self.assertEqual(len(skipped), 2)
        self.assertEqual({row["rel_path"] for row in skipped}, {"a.txt", "b.txt"})
        for row in skipped:
            self.assertEqual(row["skip_stage"], "audit")
            self.assertTrue(row["reason"])
            self.assertTrue(row["detail"])
            self.assertEqual(row["relpath"], row["rel_path"])
        self.assertEqual([int(row["n"]) for row in self._flow()], [2, 0, 0, 0])
        self.assertEqual(self._rows(), [])
        self.assertIn("extracted: 0", proc.stdout)
        self.assertIn("skipped: 2", proc.stdout)
        self.assertIn("excluded: 2", proc.stdout)

    def test_audit_partial_keeps_valid_rows_and_the_funnel(self):
        self._doc("a.txt", BODY)
        self._doc("b.txt", BODY)
        audit = self.p("audit.csv")
        # The `file` column proves the contract key fallback (B7 + CONTRACTS).
        write_csv(audit, ["file", "status"],
                  [["a.txt", "valid"], ["b.txt", "duplicate"]])
        proc = self._run("--audit", audit, "--min-chars", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([row["rel_path"] for row in self._rows()], ["a.txt"])
        self.assertEqual([int(row["n"]) for row in self._flow()], [2, 1, 1, 1])
        self.assertEqual(len(self._skipped()), 1)

    def test_audit_from_another_root_is_a_usage_error_not_a_filter(self):
        """A wrong --root must not masquerade as "every file failed the audit"."""
        self._doc("a.txt", BODY)
        audit = self.p("audit_other.csv")
        write_csv(audit, ["rel_path", "status"],
                  [["elsewhere/a.txt", "valid"], ["elsewhere/b.txt", "valid"]])
        proc = self._run("--audit", audit, "--min-chars", "1")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("lists a different directory", proc.stderr)
        self.assertIn("elsewhere/a.txt", proc.stderr)
        skipped = self._skipped()
        self.assertEqual(len(skipped), 1)
        self.assertIn("wrong --root", skipped[0]["reason"])
        self.assertNotIn("status is not valid", skipped[0]["reason"])

    def test_dedupe_plan_exclusion_is_logged(self):
        self._doc("a.txt", BODY)
        self._doc("b.txt", BODY)
        plan = self.p("dedupe.csv")
        write_csv(plan, ["rel_path", "action"], [["b.txt", "move"]])
        proc = self._run("--dedupe-plan", plan, "--min-chars", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([row["rel_path"] for row in self._rows()], ["a.txt"])
        skipped = self._skipped()
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["skip_stage"], "dedupe")
        self.assertIn("dedupe", skipped[0]["reason"])

    def test_allow_empty_accepts_an_empty_worksheet(self):
        self._doc("a.txt", BODY)
        audit = self.p("audit.csv")
        write_csv(audit, ["rel_path", "status"], [["a.txt", "invalid"]])
        proc = self._run("--audit", audit, "--min-chars", "1", "--allow-empty")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("WARNING", proc.stderr)

    def test_audit_without_a_key_column_exits_2(self):
        self._doc("a.txt", BODY)
        audit = self.p("audit.csv")
        write_csv(audit, ["status"], [["valid"]])
        proc = self._run("--audit", audit, "--min-chars", "1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing a path column", proc.stderr)

    # -- B6: one generic reading for every genre, no built-in field readers --
    def test_genre_text_gets_no_special_fields(self):
        self._doc("a.txt", LEGAL_TEXT)
        proc = self._run("--min-chars", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = self._rows()[0]
        self.assertEqual(row["doc_type"], "document")
        for gone in ("court", "case_no", "province", "crime_candidates"):
            self.assertNotIn(gone, row)

    def test_no_shipped_keyword_dictionary_is_loaded(self):
        self._doc("a-判决书.txt", LEGAL_TEXT)
        proc = self._run("--min-chars", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("SHIPPED EXAMPLE", proc.stderr)
        self.assertEqual(self._rows()[0]["category_candidates"], "")

    # -- B13: skipped rows carry a stage and a file kind -------------------
    def test_skipped_rows_carry_stage_and_file_kind(self):
        self._doc("short.txt", "短")
        self._doc("notes.csv", "a,b\n1,2\n")
        self._doc("img.png", "not really a png")
        proc = self._run()  # default --min-chars 100: nothing can be coded
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("extracted 0 documents", proc.stderr)
        by_name = {row["file"]: row for row in self._skipped()}
        self.assertEqual(by_name["short.txt"]["skip_stage"], "min_chars")
        self.assertEqual(by_name["short.txt"]["file_kind"], "text")
        self.assertEqual(by_name["notes.csv"]["skip_stage"], "format")
        self.assertEqual(by_name["img.png"]["skip_stage"], "format")
        self.assertEqual(by_name["img.png"]["file_kind"], "image")
        for row in self._skipped():
            self.assertNotIn(".", row["doc_type"])  # a kind, never an extension

    def test_ext_filter_skip_is_logged(self):
        self._doc("a.txt", BODY)
        self._doc("b.md", BODY)
        proc = self._run("--ext", "txt", "--min-chars", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        skipped = self._skipped()
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["file"], "b.md")
        self.assertEqual(skipped[0]["skip_stage"], "ext_filter")
        self.assertEqual(skipped[0]["doc_type"], "")
        self.assertEqual(skipped[0]["file_kind"], "text")
        self.assertIn("ext=md", skipped[0]["detail"])

    # -- B12: deterministic traversal --------------------------------------
    def test_traversal_is_sorted(self):
        self._doc("b.txt", BODY)
        self._doc("a.txt", BODY)
        proc = self._run("--min-chars", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([row["relpath"] for row in self._rows()],
                         ["a.txt", "b.txt"])
        self.assertEqual([rec["run_order"] for rec in self._jsonl()], [1, 2])

    # -- B14: text storage is controllable ---------------------------------
    def test_no_text_and_text_truncation(self):
        self._doc("a.txt", "正文" * 200)
        proc = self._run("--min-chars", "1", "--no-text")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rec = self._jsonl()[0]
        self.assertEqual(rec["text"], "")
        self.assertFalse(rec["text_truncated"])
        proc = self._run("--min-chars", "1", "--max-text-chars", "50")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rec = self._jsonl()[0]
        self.assertEqual(len(rec["text"]), 50)
        self.assertTrue(rec["text_truncated"])

    def test_pdf_is_extracted(self):
        make_text_pdf(os.path.join(self.corpus, "doc.pdf"),
                      "故意伤害罪 判决如下 赔偿损失。")
        proc = self._run("--min-chars", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = self._rows()
        self.assertEqual(rows[0]["source_type"], "pdf")
        self.assertGreater(int(rows[0]["chars"]), 0)


class TestCodingFunctions(unittest.TestCase):
    """Unit tests for the extractor rules (no subprocess needed)."""

    def test_year_needs_word_boundaries(self):
        self.assertIsNone(mcs.find_year(("filename", "身份证110101198001011234"))[0])
        self.assertIsNone(mcs.find_year(("filename", "1948年档案"))[0])
        self.assertEqual(mcs.find_year(("filename", "2021年度报告"))[0], 2021)

    def test_sentences_keep_offsets_and_the_legacy_shape(self):
        text = "甲赔偿损失、乙未赔偿损失。"
        self.assertEqual(mcs.sentences(text, True),
                         [("甲赔偿损失、", 0, 6), ("乙未赔偿损失。", 6, 13)])
        self.assertEqual(mcs.sentences(text), ["甲赔偿损失、", "乙未赔偿损失。"])

    def test_evidence_uses_the_contract_format_and_clips(self):
        long_text = "很" * 300 + "赔偿损失。"
        hit = mcs.find_signals(long_text, {"赔偿": ["赔偿"]})["赔偿"][0]
        self.assertTrue(hit["truncated"])
        self.assertEqual(len(hit["sentence"]), mcs.EVIDENCE_MAX_CHARS)
        self.assertTrue(hit["sentence"].endswith("…"))
        self.assertEqual(hit["end"], len(long_text))
        self.assertEqual(hit["evidence"],
                         f"赔偿={hit['sentence']}@0-{len(long_text)}")

    def test_signal_stats_count_suppressed_hits(self):
        stats = {}
        mcs.find_signals("赔偿。" * 5, {"赔偿": ["赔偿"]},
                         limit_per_term=3, stats=stats)
        self.assertEqual(stats, {"included": 3, "skipped": 2})

    def test_negation_wins_over_affirmation(self):
        hits = mcs.find_signals(
            "被告人赔偿了损失。被告人未赔偿损失。被告人驳回赔偿请求。",
            {"赔偿": ["赔偿"]})["赔偿"]
        self.assertEqual([hit["polarity"] for hit in hits],
                         ["positive", "negative", "negative"])
        self.assertEqual([hit["negated"] for hit in hits], [False, True, True])
        support = mcs.find_signals("法院不予支持该请求。",
                                   {"支持": ["支持"]})["支持"][0]
        self.assertEqual(support["polarity"], "negative")

    def test_categories_prefer_filename_hits_then_text(self):
        cmap = {"故意伤害": ["故意伤害"], "盗窃": ["盗窃"]}
        self.assertEqual(
            mcs.detect_categories("案由：故意伤害罪。", "盗窃-刑事判决书.txt", cmap),
            ["盗窃"])
        self.assertEqual(
            mcs.detect_categories("案由：故意伤害罪。", "a.txt", cmap),
            ["故意伤害"])

    def test_title_is_the_first_meaningful_line(self):
        # No genre word list picks titles any more: the first meaningful line
        # wins, whatever the document genre is.
        self.assertEqual(mcs.first_title("黑龙江省哈尔滨市中级人民法院\n刑事判决书\n正文",
                                         "x.txt"),
                         "黑龙江省哈尔滨市中级人民法院")
        self.assertEqual(mcs.first_title("某某公司2021年度报告\n正文", "x.txt"),
                         "某某公司2021年度报告")


class TestAnalysisUtils(unittest.TestCase):
    """A1/A2/A6 plus the testable P2 defects in analysis_utils."""

    def test_code_like_province_column_is_not_continuous(self):
        codes = pd.Series([index % 31 + 1 for index in range(310)])
        kind, _series, mapping, message = au.outcome_kind(codes)
        self.assertEqual(kind, "unsupported")
        self.assertEqual(mapping, {})
        self.assertIn("categorical_high_cardinality", message)
        self.assertTrue(au.is_code_like(codes))

    def test_decimal_income_stays_continuous(self):
        income = pd.Series([1000.5 + index * 3.7 for index in range(200)])
        self.assertFalse(au.is_code_like(income))
        self.assertEqual(au.outcome_kind(income)[0], "continuous")

    def test_small_sample_of_code_levels_is_unsupported(self):
        # Same column, small sample: one distinct code per row is an identifier,
        # not a categorical outcome -- the verdict must not depend on n.
        codes = pd.Series(range(1, 12))
        self.assertTrue(au.is_code_like(codes))
        self.assertEqual(au.outcome_kind(codes)[0], "unsupported")

    def test_five_level_codes_stay_categorical(self):
        codes = pd.Series([index % 5 + 1 for index in range(300)])
        self.assertFalse(au.is_code_like(codes))
        self.assertEqual(au.outcome_kind(codes)[0], "categorical")

    def test_entirely_missing_outcome_is_unsupported(self):
        kind, _series, mapping, message = au.outcome_kind(
            pd.Series([np.nan, None, pd.NA]))
        self.assertEqual(kind, "unsupported")
        self.assertEqual(mapping, {})
        self.assertEqual(message, "outcome entirely missing")

    def test_entirely_missing_binary_returns_none(self):
        self.assertEqual(au.encode_binary(pd.Series([np.nan, None])), (None, {}))

    # -- outcome_map: null declares a missing label instead of killing the run
    def test_outcome_map_null_declares_missing_not_crash(self):
        s = pd.Series(["有效", "无效", "不适用", "有效", np.nan])
        kind, encoded, mapping, message = au.outcome_kind(
            s, mapping={"有效": 1, "无效": 0, "不适用": None})
        self.assertEqual(kind, "binary", message)
        self.assertEqual(mapping, {"有效": 1, "无效": 0})
        self.assertEqual(int(encoded.isna().sum()), 2)
        self.assertEqual(list(encoded.dropna()), [1.0, 0.0, 1.0])

    def test_outcome_map_uncovered_value_lists_it(self):
        s = pd.Series(["有效", "无效", "未知"])
        kind, _series, _mapping, message = au.outcome_kind(
            s, mapping={"有效": 1, "无效": 0})
        self.assertEqual(kind, "unsupported")
        self.assertIn("uncovered: ['未知']", message)

    def test_outcome_map_invalid_code_is_named(self):
        s = pd.Series(["有效", "无效"])
        kind, _series, _mapping, message = au.outcome_kind(
            s, mapping={"有效": 1, "无效": 2})
        self.assertEqual(kind, "unsupported")
        self.assertIn("invalid entries", message)
        self.assertIn("无效=2", message)

    def test_filter_coerces_dtype_and_records_row_counts(self):
        df = pd.DataFrame({"year": [2021, 2021, 2022], "in_analysis": [1, 1, 1]})
        with contextlib.redirect_stderr(io.StringIO()):
            out, desc = au.apply_filter(df, {"filter": {"year": "2021"}})
        self.assertEqual(len(out), 2)
        self.assertIn("3→2", desc)

    def test_filter_matches_a_text_column_with_a_number(self):
        df = pd.DataFrame({"year": ["2021", "2021", "2022"]})
        out, _desc = au.apply_filter(df, {"filter": {"year": 2021}})
        self.assertEqual(len(out), 2)

    def test_zero_row_filter_raises_with_a_hint(self):
        df = pd.DataFrame({"year": [2021, 2022]})
        with self.assertRaises(ValueError) as caught:
            au.apply_filter(df, {"filter": {"year": 1999}})
        message = str(caught.exception)
        self.assertIn("matched 0 of 2 rows", message)
        self.assertIn("dtype", message)

    def test_explicit_filter_still_respects_the_in_analysis_gate(self):
        # A config-level `filter` used to displace the gate entirely: the rows
        # excluded from the analysis sample came back silently (+5% in a real
        # corpus, all of them procedural rulings).
        df = pd.DataFrame({"year": [2021, 2022, 2021], "in_analysis": [1, 0, 0]})
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            out, desc = au.apply_filter(df, {"filter": {"year": 2021}})
        self.assertEqual(len(out), 1)
        self.assertIn("in_analysis gate 3→1", buffer.getvalue())
        self.assertIn("in_analysis", desc)

    def test_keep_out_of_scope_opts_out_of_the_gate_on_purpose(self):
        df = pd.DataFrame({"year": [2021, 2022], "in_analysis": [1, 0]})
        with contextlib.redirect_stderr(io.StringIO()):
            out, desc = au.apply_filter(df, {"filter": {"year": 2021}},
                                        keep_out_of_scope=True)
        self.assertEqual(len(out), 1)
        self.assertIn("out_of_scope", desc)

    def test_filter_query_also_respects_the_gate(self):
        df = pd.DataFrame({"v": [1, 2, 3], "in_analysis": [1, 1, 0]})
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            out, desc = au.apply_filter(df, {"filter_query": "v >= 2"})
        self.assertEqual(len(out), 1)
        self.assertIn("in_analysis gate 3→2", buffer.getvalue())
        # The description must show both steps: the gate, then the condition.
        self.assertIn("in_analysis==1 (3→2) then v >= 2 (2→1 rows)", desc)

    def test_in_analysis_default_applies_without_an_explicit_filter(self):
        df = pd.DataFrame({"v": [1, 2, 3], "in_analysis": [1, 0, 1]})
        out, desc = au.apply_filter(df, {})
        self.assertEqual(len(out), 2)
        self.assertIn("in_analysis", desc)

    def test_negation_prefix_expands_binary_labels(self):
        _encoded, mapping = au.encode_binary(pd.Series(["支持", "不予支持"]))
        self.assertEqual(mapping, {"支持": 1, "不予支持": 0})
        _encoded, mapping = au.encode_binary(pd.Series(["已发生", "未发生"]))
        self.assertEqual(mapping, {"已发生": 1, "未发生": 0})
        self.assertEqual(au.encode_binary(pd.Series(["男", "女"])), (None, {}))

    def test_missing_sentinels_do_not_demote_a_binary_column(self):
        series = pd.Series(["是", "否", "NA", "null", "N/A"])
        self.assertEqual(au.outcome_kind(series)[0], "binary")

    def test_id_like_drops_evidence_and_source_columns(self):
        values = pd.Series(["x1", "x2"])
        self.assertTrue(au.is_id_like("rel_path", values))
        self.assertTrue(au.is_id_like("province_src", values))
        self.assertTrue(au.is_id_like("quote_ev", values))
        self.assertFalse(au.is_id_like("year", values))

    def test_fmt_never_prints_a_missing_marker(self):
        self.assertEqual(au.fmt(pd.NA), "")
        self.assertEqual(au.fmt(float("nan")), "")
        self.assertEqual(au.fmt(1.2349), "1.235")

    def test_bad_outcome_map_does_not_crash(self):
        self.assertEqual(au.encode_binary(pd.Series(["是", "否"]), {"是": "yes"}),
                         (None, {}))
        encoded, mapping = au.encode_binary(pd.Series(["是", "否"]),
                                           {"是": 1, "否": 0})
        self.assertEqual(list(encoded), [1.0, 0.0])
        self.assertEqual(mapping, {"是": 1, "否": 0})

    def test_all_null_outcome_map_declares_no_code(self):
        # JSON null marks a label missing; a map of only nulls codes nothing,
        # and the message must say so instead of "invalid entries: []".
        self.assertEqual(au.encode_binary(pd.Series(["是", "否"]),
                                          {"是": None, "否": None}), (None, {}))
        kind, _encoded, _mapping, message = au.outcome_kind(
            pd.Series(["是", "否"]), mapping={"是": None, "否": None})
        self.assertEqual(kind, "unsupported")
        self.assertIn("declares no 0/1 code", message)
        kind, _encoded, _mapping, message = au.outcome_kind(
            pd.Series(["是", "否"]), mapping={"是": 1, "否": "no"})
        self.assertEqual(kind, "unsupported")
        self.assertIn("invalid entries", message)

    def test_category_map_reads_only_category_keys(self):
        # Domain aliases (a legacy "crime" key) must not smuggle a keyword
        # dictionary in; only the neutral "category"/"categories" keys count.
        self.assertEqual(mcs.category_map_from({"crime": {"a": ["a"]}}), {})
        self.assertEqual(mcs.category_map_from(
            {"categories": {"a": ["a"]}}), {"a": ["a"]})

    def test_categorical_dtype_is_opt_in(self):
        series = pd.Series([1, 2, 3])
        _kind, original, _mapping, _message = au.outcome_kind(series)
        self.assertTrue(pd.api.types.is_integer_dtype(original))
        _kind, normalized, _mapping, _message = au.outcome_kind(
            series, normalize_dtype=True)
        self.assertEqual(normalized.dtype, object)


class TestAnalysisIO(TempCase):
    """A7: encoding fallback must be decided by content, not by codec luck."""

    def test_read_csv_auto_decodes_big5(self):
        path = self.p("big5.csv")
        with open(path, "w", encoding="big5", newline="") as fh:
            fh.write("法院,件數\n臺灣臺北地方法院,3\n")
        frame = au.read_csv_auto(path)
        self.assertEqual(list(frame.columns), ["法院", "件數"])
        self.assertEqual(frame.iloc[0, 0], "臺灣臺北地方法院")

    def test_read_csv_auto_decodes_gb18030(self):
        path = self.p("gb.csv")
        with open(path, "w", encoding="gb18030", newline="") as fh:
            fh.write("法院,数量\n黑龙江省高级人民法院,2\n")
        frame = au.read_csv_auto(path)
        self.assertEqual(frame.iloc[0, 0], "黑龙江省高级人民法院")


class TestSpssSyntax(TempCase):
    """S1/S2/S3 plus the testable P2 defects in csv_to_spss_syntax."""

    def _run(self, *args):
        return run("csv_to_spss_syntax.py", *args, cwd=self.tmp)

    def test_thousands_separator_and_na_stay_numeric(self):
        csv_path = self.p("money.csv")
        write_csv(csv_path, ["金额", "备注"],
                  [["1,234", "a"], ["2,000", "b"], ["NA", "c"]])
        report = {}
        header, specs, _labels, _recodes, _encoding = c2s.infer(
            csv_path, report=report)
        self.assertEqual(header, ["金额", "备注"])
        self.assertTrue(specs[0][1].startswith("F"))
        self.assertTrue(report["columns"][0]["numeric"])
        self.assertEqual(report["notes"], [])

    def test_string_fallback_is_reported(self):
        csv_path = self.p("mixed.csv")
        write_csv(csv_path, ["得分"], [["1"], ["2"], ["未知"]])
        report = {}
        _header, specs, _labels, _recodes, _encoding = c2s.infer(
            csv_path, report=report)
        self.assertTrue(specs[0][1].startswith("A"))
        self.assertEqual(len(report["notes"]), 1)
        self.assertIn("fell back to string", report["notes"][0])

    def test_utf8_sps_declares_and_writes_utf8(self):
        csv_path = self.p("d.csv")
        write_csv(csv_path, ["年份", "得分"], [["2021", "1"], ["2022", "2"]])
        out = self.p("out", "syntax.sps")
        proc = self._run("--csv", csv_path, "--out-sps", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, "rb") as fh:
            raw = fh.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn("/ENCODING='UTF8'", raw.decode("utf-8-sig"))

    def test_gbk_sps_is_written_in_the_declared_encoding(self):
        csv_path = self.p("d.csv")
        write_csv(csv_path, ["年份", "得分"], [["2021", "1"]])
        out = self.p("out", "syntax.sps")
        proc = self._run("--csv", csv_path, "--out-sps", out,
                         "--encoding", "gb18030")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, "rb") as fh:
            raw = fh.read()
        self.assertIn("/ENCODING='GBK'", raw.decode("gb18030"))
        with self.assertRaises(UnicodeDecodeError):
            raw.decode("utf-8")

    def test_missing_values_and_variable_level_are_declared(self):
        csv_path = self.p("d.csv")
        write_csv(csv_path, ["得分", "是否"],
                  [["1", "是"], ["2", "否"], ["3", "是"]])
        out = self.p("out", "syntax.sps")
        proc = self._run("--csv", csv_path, "--out-sps", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, encoding="utf-8-sig") as fh:
            text = fh.read()
        self.assertIn("MISSING VALUES 得分 (-99, -98, -97).", text)
        self.assertIn("VARIABLE LEVEL", text)
        self.assertIn("得分 (ORDINAL)", text)
        self.assertIn("是否 (NOMINAL)", text)
        self.assertIn("VALUE LABELS", text)

    def test_sentinel_conflict_uses_non_conflicting_values(self):
        csv_path = self.p("d.csv")
        write_csv(csv_path, ["得分"], [["-99"], ["1"], ["2"]])
        out = self.p("out", "syntax.sps")
        proc = self._run("--csv", csv_path, "--out-sps", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("-999999", proc.stderr)
        with open(out, encoding="utf-8-sig") as fh:
            text = fh.read()
        self.assertIn("(-999999, -999998, -999997)", text)

    def test_delimiter_is_sniffed(self):
        csv_path = self.p("semi.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("a;b\n1;2\n")
        out = self.p("out", "syntax.sps")
        proc = self._run("--csv", csv_path, "--out-sps", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, encoding="utf-8-sig") as fh:
            text = fh.read()
        self.assertIn('/DELIMITERS=";"', text)

    def test_value_label_bytes_are_capped(self):
        label = c2s.quote_label("长" * 100, c2s.VALUE_LABEL_BYTES)
        self.assertLessEqual(len(label.encode("utf-8")),
                             c2s.VALUE_LABEL_BYTES + 2)

    def test_ragged_rows_are_reported(self):
        csv_path = self.p("ragged.csv")
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("a,b\n1,2\n3\n4,5,6\n")
        report = {}
        c2s.infer(csv_path, report=report)
        self.assertEqual(report["ragged_rows"], 2)

    def test_exponent_notation_gets_the_real_width(self):
        csv_path = self.p("exp.csv")
        write_csv(csv_path, ["金额"], [["1e12"], ["2e12"]])
        _header, specs, _labels, _recodes, _encoding = c2s.infer(csv_path)
        self.assertEqual(specs[0][1], "F14.0")

    def test_rename_map_is_written(self):
        csv_path = self.p("d.csv")
        write_csv(csv_path, ["a-b", "正常"], [["1", "2"]])
        out = self.p("out", "syntax.sps")
        proc = self._run("--csv", csv_path, "--out-sps", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = read_csv(self.p("out", "renamed_map.csv"))
        self.assertEqual([row["raw"] for row in rows], ["a-b", "正常"])
        self.assertEqual(rows[0]["renamed"], "1")
        self.assertEqual(rows[1]["renamed"], "0")

    def test_astral_cjk_survives_name_cleaning(self):
        self.assertEqual(c2s.sanitize_name("𠮷", 0, set()), "𠮷")

    def test_missing_csv_exits_2(self):
        proc = self._run("--csv", self.p("nope.csv"),
                         "--out-sps", self.p("out", "s.sps"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("CSV not found", proc.stderr)


class TestExtractPipeline(TempCase):
    """``--extract`` must produce a dataset, not just a worksheet (Sprint A)."""

    HEADER = ("审\n理\n法\n院：某某区人民法院\n案\n号：(2021)测****刑初7 号\n"
              "裁\n判\n日\n期：2021.03.05\n案\n由：刑事/妨害社会管理秩序罪/滥伐林木罪\n")

    def setUp(self):
        super().setUp()
        self.corpus = self.p("corpus")
        os.makedirs(self.corpus, exist_ok=True)
        self.out = self.p("out")
        # Shipped profiles are shape examples and --extract refuses them, so
        # the pipeline tests copy one into the project's draft/ first -- the
        # same thing a real project does after reading its samples.
        self.profile = self.p("draft", "fields.json")
        os.makedirs(os.path.dirname(self.profile), exist_ok=True)
        shutil.copyfile(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "empirical-research-pipeline", "profiles", "legal-judgment.json"),
            self.profile)

    def _doc(self, rel, text):
        path = os.path.join(self.corpus, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # newline="" keeps the fixture byte-identical to the offsets asserted
        # below; text mode would rewrite "\n" as "\r\n" on Windows.
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def _run(self, *args):
        return run("make_coding_sheet.py", "--root", self.corpus,
                   "--out", self.out, "--allow-empty", *args, cwd=self.tmp)

    def test_dataset_evidence_and_run_are_written(self):
        self._doc("a.txt", self.HEADER + "判决如下：一、被告人犯滥伐林木罪，"
                                         "判处有期徒刑一年六个月，并处罚金5000元。\n" + BODY)
        proc = self._run("--min-chars", "1", "--extract", self.profile)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in ("dataset.csv", "evidence.jsonl", "run.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, name)), name)
        rows = read_csv(os.path.join(self.out, "dataset.csv"))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["case_no"], "(2021)测****刑初7 号")
        self.assertEqual(row["sentence_months"], "18")
        self.assertEqual(row["fine_yuan"], "5000")
        self.assertEqual(row["case_no_src"], "kv_block")
        # A source column exists for every field: a value without provenance
        # cannot be audited.
        for key in ("case_no", "year", "charge", "fine_yuan", "restore_amount"):
            self.assertIn(f"{key}_src", row)

    def test_evidence_offsets_verify_against_the_source(self):
        body = self.HEADER + "判决如下：一、被告人犯滥伐林木罪，判处罚金5000元。\n" + BODY
        self._doc("a.txt", body)
        proc = self._run("--min-chars", "1", "--extract", self.profile)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(self.out, "evidence.jsonl"), encoding="utf-8") as fh:
            rec = json.loads(fh.readline())
        self.assertEqual(rec["_row_id"], "00001")
        self.assertTrue(rec["evidence"])
        for line in rec["evidence"]:
            self.assertIn("@", line)
            self.assertNotIn("\n", line)
            name, rest = line.split("=", 1)
            snippet, _, rng = rest.rpartition("@")
            start, end = (int(x) for x in rng.split("-"))
            self.assertIn(" ".join(body[start:end].split()), " ".join(snippet.split()))

    def test_run_json_records_hits_and_profile_hash(self):
        self._doc("a.txt", self.HEADER + "判决如下：一、判处罚金5000元。\n" + BODY)
        self._doc("b.txt", "无关材料，只有正文，没有可抽取字段。" * 8)
        proc = self._run("--min-chars", "1", "--extract", self.profile)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(self.out, "run.json"), encoding="utf-8") as fh:
            runinfo = json.load(fh)
        self.assertEqual(runinfo["documents"], 2)
        self.assertEqual(len(runinfo["profile_sha256"]), 64)
        self.assertEqual(runinfo["fields"]["case_no"]["hit"], 1)
        self.assertEqual(runinfo["fields"]["case_no"]["na"], 1)

    def test_flow_gets_an_extraction_stage(self):
        self._doc("a.txt", self.HEADER + BODY)
        proc = self._run("--min-chars", "1", "--extract", self.profile)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        stages = [row["stage"] for row in read_csv(
            os.path.join(self.out, "sample_flow.csv"))]
        self.assertIn("抽取字段完成", stages)

    def test_shipped_profile_is_refused(self):
        self._doc("a.txt", self.HEADER + BODY)
        shipped = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "empirical-research-pipeline", "profiles", "legal-judgment.json")
        proc = self._run("--min-chars", "1", "--extract", shipped)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("refuses profiles shipped with the skill", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.out, "dataset.csv")))

    def test_shipped_profile_refusal_survives_path_variants(self):
        # The guard must hold against lexical tricks, not just the exact path.
        self._doc("a.txt", self.HEADER + BODY)
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        shipped = os.path.join(here, "empirical-research-pipeline",
                               "profiles", "legal-judgment.json")
        variants = [
            # a ..-hop that lands back inside the shipped directory
            os.path.join(here, "empirical-research-pipeline", "profiles",
                         "..", "profiles", "legal-judgment.json"),
        ]
        if os.name == "nt":
            # lower-case drive + mixed-case directory (case-insensitive FS)
            variants.append(shipped.replace(
                here[:2], here[:2].lower()).replace("profiles", "Profiles"))
            # the \\?\ extended-length prefix
            variants.append("\\\\?\\" + shipped)
        for target in variants:
            self.assertTrue(os.path.isfile(target), target)
            proc = self._run("--min-chars", "1", "--extract", target)
            self.assertEqual(proc.returncode, 2, target)
            self.assertIn("refuses profiles shipped with the skill", proc.stderr)

    def test_project_owned_profiles_directory_is_allowed(self):
        # A project may name its own directory "profiles" -- the guard fences
        # the skill's shipped directory, not the name.
        self._doc("a.txt", self.HEADER + "判决如下：一、判处罚金5000元。\n" + BODY)
        own = self.p("profiles", "fields.json")
        os.makedirs(os.path.dirname(own), exist_ok=True)
        shutil.copyfile(self.profile, own)
        proc = self._run("--min-chars", "1", "--extract", own)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "dataset.csv")))

    def test_missing_profile_exits_2(self):
        self._doc("a.txt", BODY)
        proc = self._run("--min-chars", "1", "--extract", self.p("nope.json"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("profile not found", proc.stderr)

    def test_invalid_profile_exits_2_with_the_reason(self):
        self._doc("a.txt", BODY)
        bad = self.p("bad.json")
        with open(bad, "w", encoding="utf-8") as fh:
            json.dump({"profile": "t", "fields": [
                {"name": "x", "func": "pattern", "type": "text", "pattern": "a"}]}, fh)
        proc = self._run("--min-chars", "1", "--extract", bad)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("'na' phrase is required", proc.stderr)

    def test_generic_doc_type_is_not_a_file_extension(self):
        self._doc("a.txt", BODY)
        proc = self._run("--min-chars", "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = read_csv(os.path.join(self.out, "coding_sheet.csv"))[0]
        self.assertEqual(row["doc_type"], "document")
        self.assertEqual(row["doc_type_src"], "default")


class TestExtractResume(TempCase):
    """--resume for --extract: the journal makes an interrupted run cheap (batch 6)."""

    def setUp(self):
        super().setUp()
        self.corpus = self.p("corpus")
        os.makedirs(self.corpus, exist_ok=True)
        self.out = self.p("out")
        self.profile = self.p("draft", "fields.json")
        os.makedirs(os.path.dirname(self.profile), exist_ok=True)
        shutil.copyfile(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "empirical-research-pipeline", "profiles", "legal-judgment.json"),
            self.profile)

    def doc(self, name, header_extra=""):
        header = ("审\n理\n法\n院：某某区人民法院\n案\n号：(2021)测****刑初7 号\n"
                  "裁\n判\n日\n期：2021.03.05\n案\n由：刑事/妨害社会管理秩序罪/滥伐林木罪\n"
                  + header_extra)
        path = os.path.join(self.corpus, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(header + "判决如下：一、被告人犯滥伐林木罪，"
                    "判处有期徒刑一年六个月，并处罚金5000元。\n" + BODY)
        return path

    def run_extract(self, *extra):
        return run("make_coding_sheet.py", "--root", self.corpus, "--out", self.out,
                   "--allow-empty", "--min-chars", "1", "--extract", self.profile,
                   *extra, cwd=self.tmp)

    def outputs(self):
        # every product the run writes, closed properly: a replay bug in
        # review rows or candidates must not slip through a narrow lens
        names = ("dataset.csv", "evidence.jsonl", "coding_sheet.jsonl",
                 "extraction_review.csv", "extraction_candidates.jsonl",
                 "missing_by_source.csv", "decisions_todo.csv",
                 "skipped_documents.csv", "coding_sheet.csv",
                 "sample_flow.csv")
        blobs = []
        for name in names:
            path = os.path.join(self.out, name)
            if not os.path.exists(path):
                continue
            with open(path, "rb") as fh:
                blobs.append((name, fh.read()))
        return blobs

    def test_resume_is_byte_identical_and_reuses_every_document(self):
        self.doc("a.txt")
        self.doc("b.txt")
        first = self.run_extract()
        self.assertEqual(first.returncode, 0, first.stderr)
        before = self.outputs()
        second = self.run_extract("--resume")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.outputs(), before)
        self.assertIn("resume: reused 2", second.stdout)
        self.assertEqual(self.run_resume_state()["reused"], 2)

    def test_same_size_content_change_is_reprocessed(self):
        self.doc("a.txt")
        self.doc("b.txt")
        first = self.run_extract()
        self.assertEqual(first.returncode, 0, first.stderr)
        # same byte count, different content: only mtime can catch this
        self.doc("a.txt", header_extra="备注：合成样本。\n")
        second = self.run_extract("--resume")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("resume: reused 1, reprocessed 1", second.stdout)
        rows = read_csv(os.path.join(self.out, "dataset.csv"))
        self.assertEqual(len(rows), 2)

    def test_frame_mismatch_profile_is_refused(self):
        self.doc("a.txt")
        first = self.run_extract()
        self.assertEqual(first.returncode, 0, first.stderr)
        with open(self.profile, encoding="utf-8") as fh:
            profile = json.load(fh)
        profile["fields"] = profile["fields"][:1]
        with open(self.profile, "w", encoding="utf-8") as fh:
            json.dump(profile, fh, ensure_ascii=False)
        second = self.run_extract("--resume")
        self.assertEqual(second.returncode, 2)
        self.assertIn("frame", second.stderr)

    def test_torn_journal_tail_is_ignored(self):
        self.doc("a.txt")
        first = self.run_extract()
        self.assertEqual(first.returncode, 0, first.stderr)
        before = self.outputs()
        journal = os.path.join(self.out, "extract_journal.jsonl")
        with open(journal, "a", encoding="utf-8") as fh:
            fh.write('{"frame": tor')   # what a crash mid-write leaves behind
        second = self.run_extract("--resume")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("torn line", second.stderr)
        self.assertEqual(self.outputs(), before)

    def test_journal_compacts_between_runs(self):
        self.doc("a.txt")
        self.doc("b.txt")
        first = self.run_extract()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.journal_count(), 2)
        second = self.run_extract("--resume")
        self.assertEqual(self.journal_count(), 2)   # no unbounded growth

    def journal_rels(self):
        journal = os.path.join(self.out, "extract_journal.jsonl")
        rels = []
        with open(journal, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rels.append(json.loads(line)["doc"]["rel"])
        return rels

    def journal_count(self):
        return len(self.journal_rels())

    def run_resume_state(self):
        with open(os.path.join(self.out, "run.json"), encoding="utf-8") as fh:
            run_json = json.load(fh)
        producer = run_json.get("producers", {}).get("make_coding_sheet.py") or run_json
        return producer["resume"]

    def test_truncated_resume_keeps_beyond_cutoff_entries(self):
        # --max-files shrinks the walk, not the corpus: entries beyond the
        # cutoff must stay in the journal (they are reusable next run) and
        # the note must not claim they "no longer exist"
        self.doc("a.txt")
        self.doc("b.txt")
        self.doc("c.txt")
        first = self.run_extract()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.journal_count(), 3)
        second = self.run_extract("--resume", "--max-files", "1")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("no longer present", second.stderr)
        self.assertIn("--max-files", second.stderr)
        self.assertEqual(sorted(self.journal_rels()), ["a.txt", "b.txt", "c.txt"])
        self.assertEqual(self.run_resume_state()["dropped"], 0)
        # and the next full resume still reuses everything
        third = self.run_extract("--resume")
        self.assertIn("resume: reused 3", third.stdout)
        # replay across a truncation boundary equals a fresh full run,
        # across every product (not just the three headline files)
        fresh = self.run_extract("--out", self.p("fresh"))
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        names = [name for name, _ in self.outputs()]
        for name in names:
            with open(os.path.join(self.out, name), "rb") as fh:
                replayed = fh.read()
            with open(os.path.join(self.p("fresh"), name), "rb") as fh:
                produced = fh.read()
            self.assertEqual(replayed, produced, name)

    def test_size_change_is_reprocessed(self):
        self.doc("a.txt")
        self.doc("b.txt")
        first = self.run_extract()
        self.assertEqual(first.returncode, 0, first.stderr)
        with open(os.path.join(self.corpus, "a.txt"), "a", encoding="utf-8") as fh:
            fh.write("补一段更长的正文，改变文件大小。" * 3)
        second = self.run_extract("--resume")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("resume: reused 1, reprocessed 1", second.stdout)

    def test_vanished_documents_are_dropped_from_the_journal(self):
        self.doc("a.txt")
        self.doc("b.txt")
        first = self.run_extract()
        self.assertEqual(first.returncode, 0, first.stderr)
        os.remove(os.path.join(self.corpus, "b.txt"))
        second = self.run_extract("--resume")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("no longer present", second.stderr)
        self.assertEqual(self.journal_rels(), ["a.txt"])
        rows = read_csv(os.path.join(self.out, "dataset.csv"))
        self.assertEqual(len(rows), 1)

    def test_frame_mismatches_ext_and_min_chars_are_refused(self):
        self.doc("a.txt")
        first = self.run_extract()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_extract("--resume", "--ext", "md")
        self.assertEqual(second.returncode, 2)
        self.assertIn("frame", second.stderr)
        third = self.run_extract("--resume", "--min-chars", "9999")
        self.assertEqual(third.returncode, 2)
        self.assertIn("frame", third.stderr)

    def test_frame_mismatch_no_text_switch_is_refused(self):
        self.doc("a.txt")
        first = self.run_extract()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_extract("--resume", "--no-text")
        self.assertEqual(second.returncode, 2)
        self.assertIn("frame", second.stderr)


if __name__ == "__main__":
    unittest.main()
