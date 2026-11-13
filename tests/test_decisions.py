# -*- coding: utf-8 -*-
"""Contract tests for the judgment ledger and the review gate.

Three defect families are covered here:

* ``DecisionContractTest`` — a ledger that cannot be checked (bad span, quote,
  fabricated value, duplicate target, unresolved human decision);
* ``ExtractionReviewTest`` — a declared NA must not become the next line's
  number, and a review flag must stop a delivery run until a decision lands;
* ``ReviewPackTest`` — the packet's numbers must come from the artefacts, and
  an empty run must not look like a clean run.

All fixtures are temporary; no network, no real corpus.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _helpers import SCRIPTS, TempCase, read_csv, run, write_csv  # noqa: E402

sys.path.insert(0, SCRIPTS)
import check_decisions as CD  # noqa: E402
import extract_lib as E  # noqa: E402

PROFILES = os.path.join(os.path.dirname(SCRIPTS), "profiles")
ELDER = os.path.join(PROFILES, "eldercare-interview.json")

INTERVIEW = """访谈记录
访谈编号：T8
受访者年龄：{age}
访谈日期：2021年5月12日
访谈地点：幸福社区
访谈内容
答：还可以。
"""


def _span(text: str, needle: str) -> tuple[int, int]:
    start = text.index(needle)
    return start, start + len(needle)


class DecisionContractTest(TempCase):
    def _write(self, items: list[dict], name: str = "decisions.jsonl") -> str:
        path = self.p(name)
        with open(path, "w", encoding="utf-8") as fh:
            for item in items:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        return path

    def _review(self) -> dict:
        return {("a.txt", "age"): {
            "rel_path": "a.txt", "field": "age", "value": "67",
            "alternatives": "71", "needs_review": "False"}}

    def _base(self, **over) -> dict:
        text = "受访者年龄：67岁"
        start, end = _span(text, "67岁")
        item = {"id": "D-1", "stage": "extract", "target": "a.txt#age",
                "decision": "value", "value": 67, "reason": "原文写明 67 岁",
                "evidence": [f"a.txt@{start}-{end}"], "quote": "67岁",
                "confidence": 0.9, "needs_human": False}
        item.update(over)
        return item

    def setUp(self) -> None:
        super().setUp()
        with open(self.p("a.txt"), "w", encoding="utf-8") as fh:
            fh.write("受访者年龄：67岁\n")

    def test_valid_ledger_passes(self):
        issues = CD.validate_decisions([self._base()], self.tmp, self._review())
        self.assertEqual(issues, [])

    def test_fabricated_value_is_rejected(self):
        issues = CD.validate_decisions(
            [self._base(value=99)], self.tmp, self._review())
        self.assertTrue(any(issue["check"] == "candidate" for issue in issues))

    def test_quote_must_match_the_span(self):
        issues = CD.validate_decisions(
            [self._base(quote="71岁")], self.tmp, self._review())
        self.assertTrue(any(issue["check"] == "evidence" for issue in issues))

    def test_out_of_range_span_is_rejected(self):
        issues = CD.validate_decisions(
            [self._base(evidence=["a.txt@0-999"])], self.tmp, self._review())
        self.assertTrue(any("out of range" in issue["detail"] for issue in issues))

    def test_duplicate_target_needs_supersedes(self):
        first = self._base()
        second = self._base(id="D-2", value=71)
        issues = CD.validate_decisions([first, second], self.tmp, self._review())
        self.assertTrue(any(issue["check"] == "duplicate" for issue in issues))

    def test_unknown_field_target_is_rejected(self):
        item = self._base(target="a.txt#nope", decision="na", value=None)
        issues = CD.validate_decisions([item], self.tmp, self._review())
        self.assertTrue(any(issue["check"] == "candidate" for issue in issues))

    def test_unresolved_blocks_unless_allowed(self):
        item = self._base(needs_human=True)
        issues = CD.validate_decisions([item], self.tmp, self._review())
        self.assertTrue(any(issue["check"] == "unresolved" for issue in issues))
        self.assertEqual(CD.validate_decisions([item], self.tmp, self._review(),
                                               allow_unresolved=True), [])

    def test_cli_exit_codes_and_issues_file(self):
        good = self._write([self._base()])
        review = write_csv(
            self.p("review.csv"),
            ["rel_path", "field", "value", "alternatives"],
            [["a.txt", "age", "67", "71"]])
        proc = run("check_decisions.py", "--decisions", good, "--root", self.tmp,
                   "--review", review, "--out", self.p("issues.csv"))
        self.assertEqual(proc.returncode, 0, proc.stderr)

        bad = self._write([self._base(value=99)], "bad.jsonl")
        proc = run("check_decisions.py", "--decisions", bad, "--root", self.tmp,
                   "--review", review, "--out", self.p("bad_issues.csv"))
        self.assertEqual(proc.returncode, 2)
        self.assertTrue(read_csv(self.p("bad_issues.csv")))


class ExtractionReviewTest(TempCase):
    def _corpus(self, age: str) -> str:
        root = self.p("corpus")
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "t8.txt"), "w", encoding="utf-8") as fh:
            fh.write(INTERVIEW.format(age=age))
        return root

    def test_declared_na_does_not_become_the_next_line(self):
        text = INTERVIEW.format(age="未记录")
        out = E.apply_profile(E.load_profile(ELDER), text, base_dir=PROFILES)
        age = out["fields"]["respondent_age"]
        self.assertIsNone(age["value"])
        self.assertEqual(age["source"], "na")
        self.assertIn("value_withheld", age["flags"])
        rejected = [item["value"] for item in age["candidates"]
                    if item.get("note") == "rejected_by_na"]
        self.assertIn(2021, rejected)

    def test_unknown_word_is_flagged_not_silently_trusted(self):
        out = E.apply_profile(E.load_profile(ELDER),
                              INTERVIEW.format(age="不详"), base_dir=PROFILES)
        age = out["fields"]["respondent_age"]
        self.assertTrue(age["needs_review"])
        self.assertIn("cross_line_header", age["flags"])

    def test_same_line_value_is_clean(self):
        out = E.apply_profile(E.load_profile(ELDER),
                              INTERVIEW.format(age="71"), base_dir=PROFILES)
        age = out["fields"]["respondent_age"]
        self.assertEqual(age["value"], 71)
        self.assertFalse(age["needs_review"])

    def test_lone_decimal_point_is_not_zero(self):
        self.assertIsNone(E.num("访谈地点"))
        self.assertIsNone(E.num_find("访谈地点"))
        self.assertEqual(E.num("零点五"), 0.5)

    def test_review_gate_then_decision(self):
        root = self._corpus("未记录")
        out = self.p("out")
        proc = run("make_coding_sheet.py", "--root", root, "--out", out,
                   "--extract", ELDER, "--min-chars", "5", "--require-review")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        review = read_csv(os.path.join(out, "extraction_review.csv"))
        age_row = next(row for row in review
                       if row["field"] == "respondent_age")
        self.assertEqual(age_row["needs_review"], "True")
        self.assertEqual(age_row["value"], "")

        text = INTERVIEW.format(age="未记录")
        start, end = _span(text, "未记录")
        decisions = self.p("decisions.jsonl")
        with open(decisions, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "id": "D-1", "stage": "extract",
                "target": "t8.txt#respondent_age", "decision": "na",
                "value": None,
                "reason": "原文写未记录；下一行日期属于 interview_date",
                "evidence": [f"t8.txt@{start}-{end}"], "quote": "未记录",
                "confidence": 0.99, "needs_human": False,
            }, ensure_ascii=False) + "\n")
        proc = run("check_decisions.py", "--decisions", decisions,
                   "--root", root, "--review",
                   os.path.join(out, "extraction_review.csv"),
                   "--out", self.p("issues.csv"))
        self.assertEqual(proc.returncode, 0, proc.stderr)

        proc = run("make_coding_sheet.py", "--root", root, "--out", out,
                   "--extract", ELDER, "--min-chars", "5",
                   "--decisions", decisions, "--require-review")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = read_csv(os.path.join(out, "dataset.csv"))
        self.assertEqual(rows[0]["respondent_age"], "")
        self.assertEqual(rows[0]["respondent_age_src"], "decision:na")
        review = read_csv(os.path.join(out, "extraction_review.csv"))
        self.assertEqual(review[0]["needs_review"], "False")
        with open(os.path.join(out, "run.json"), encoding="utf-8") as fh:
            run_info = json.load(fh)
        self.assertEqual(run_info["review"]["decisions_applied"], 1)
        self.assertEqual(run_info["review"]["needs_review"], 0)


    def test_decision_replaces_the_rejected_evidence(self):
        root = self._corpus("不详")
        out = self.p("out")
        text = INTERVIEW.format(age="不详")
        start, end = _span(text, "不详")
        decisions = self.p("decisions.jsonl")
        with open(decisions, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "id": "D-9", "stage": "extract",
                "target": "t8.txt#respondent_age", "decision": "na",
                "value": None, "reason": "不详与未记录同义；2021 是访谈日期",
                "evidence": [f"t8.txt@{start}-{end}"], "quote": "不详",
                "confidence": 0.9, "needs_human": False,
            }, ensure_ascii=False) + "\n")
        proc = run("make_coding_sheet.py", "--root", root, "--out", out,
                   "--extract", ELDER, "--min-chars", "5",
                   "--decisions", decisions)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(out, "evidence.jsonl"), encoding="utf-8") as fh:
            record = json.loads(fh.readline())
        lines = [line for line in record["evidence"]
                 if line.startswith("respondent_age=")]
        self.assertEqual(lines, ["respondent_age=decision:D-9"])
        self.assertIsNone(record["fields"]["respondent_age"]["span"])


    def test_exclude_removes_the_document_from_every_artefact(self):
        root = self.p("corpus2")
        os.makedirs(root, exist_ok=True)
        for name, age in (("t8.txt", "71"), ("t9.txt", "72")):
            with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                fh.write(INTERVIEW.format(age=age))
        decisions = self.p("exclude.jsonl")
        with open(decisions, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "id": "D-9", "stage": "extract", "target": "t9.txt",
                "decision": "exclude", "value": None,
                "reason": "重复记录，不进分析样本", "evidence": ["t9.txt"],
                "confidence": 0.99, "needs_human": False,
            }, ensure_ascii=False) + "\n")
        out = self.p("excluded")
        proc = run("make_coding_sheet.py", "--root", root, "--out", out,
                   "--extract", ELDER, "--min-chars", "5",
                   "--decisions", decisions)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = read_csv(os.path.join(out, "dataset.csv"))
        self.assertEqual([row["rel_path"] for row in rows], ["t8.txt"])
        with open(os.path.join(out, "evidence.jsonl"), encoding="utf-8") as fh:
            evidence = [json.loads(line)["rel_path"] for line in fh]
        self.assertEqual(evidence, ["t8.txt"])
        review = read_csv(os.path.join(out, "extraction_review.csv"))
        self.assertEqual({row["rel_path"] for row in review}, {"t8.txt"})
        with open(os.path.join(out, "run.json"), encoding="utf-8") as fh:
            info = json.load(fh)
        self.assertEqual(info["review"]["documents_excluded_by_decision"], 1)


class ReviewPackTest(TempCase):
    def test_pack_reports_what_the_artefacts_say(self):
        data = write_csv(
            self.p("data.csv"), ["x", "y", "in_analysis"],
            [[1, 2, 1], [2, "", 1], [3, 4, 0]])
        stats = self.p("stats")
        write_csv(os.path.join(stats, "coef_all.csv"),
                  ["model", "term", "type", "n"],
                  [["m1", "x", "ols", 240], ["m1", "z", "ols", 240]])
        write_csv(os.path.join(stats, "fit.csv"),
                  ["model", "n", "pseudo_r2"], [["m1", 240, 0.31]])
        figures = write_csv(
            self.p("chart_manifest.csv"),
            ["id", "n", "status", "section"],
            [["F01", 240, "ok", "A"], ["F02", 240, "error", "B"]])
        verify = write_csv(
            self.p("issues.csv"),
            ["severity", "check", "where", "detail"],
            [["error", "V-03", "docx:2", "80 份找不到"]])
        flow = write_csv(
            self.p("sample_flow.csv"), ["stage", "n"],
            [["文件总数", 10], ["有效文件", 8], ["编码完成", 8]])
        decisions = self.p("decisions.jsonl")
        with open(decisions, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "id": "D-1", "stage": "extract", "target": "a.txt#age",
                "decision": "na", "value": None, "reason": "未记录",
                "evidence": ["data.csv"], "confidence": 0.9,
                "needs_human": True,
            }, ensure_ascii=False) + "\n")

        out = self.p("review", "review_pack.md")
        proc = run("review_pack.py", "--data", data, "--stats", stats,
                   "--figures", figures, "--verify", verify,
                   "--sample-flow", flow, "--decisions", decisions,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, encoding="utf-8") as fh:
            body = fh.read()
        self.assertIn("交付前审稿包", body)
        self.assertIn("1 个 error", body)
        self.assertIn("单调不增：是", body)
        self.assertIn("待人工：1 条", body)
        self.assertIn("模型 `m1`", body)
        with open(self.p("review", "review_pack.json"),
                  encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["sample"]["rows"], 3)
        self.assertEqual(payload["figures"]["not_ok"], ["F02"])
        self.assertTrue(payload["questions"])
        self.assertLessEqual(len(payload["questions"]), 5)

    def test_no_inputs_is_an_error(self):
        proc = run("review_pack.py", "--out", self.p("pack.md"))
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
