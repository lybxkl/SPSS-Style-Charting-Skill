# -*- coding: utf-8 -*-
"""Unit tests for verify_numbers.py (Sprint C1).

Every test builds its own temporary workspace and drives the CLI, so argparse,
exit codes and the two output CSVs are covered as well as the checks.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempCase, make_docx, read_csv, run, write_csv


class VerifyCase(TempCase):
    def setUp(self):
        super().setUp()
        self.out = self.p("out")
        self.tables = self.p("tables")
        os.makedirs(self.tables, exist_ok=True)

    def verify(self, *args):
        return run("verify_numbers.py", "--out", self.out, *args)

    def issues(self):
        return read_csv(os.path.join(self.out, "number_issues.csv"))

    def traces(self):
        return read_csv(os.path.join(self.out, "number_trace.csv"))

    def issue_checks(self):
        return [issue["check"] for issue in self.issues()]


class TestTableTotals(VerifyCase):
    """V-01 表内合计."""

    def test_total_row_matches(self):
        write_csv(os.path.join(self.tables, "table1_summary.csv"),
                  ["类别", "频数", "占比"],
                  [["A", "40", "40%"], ["B", "60", "60%"], ["合计", "100", "100%"]])
        proc = self.verify("--tables", self.tables, "--check", "tables")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.issues(), [])

    def test_total_row_off_by_one_is_an_error(self):
        write_csv(os.path.join(self.tables, "table1_summary.csv"),
                  ["类别", "频数"], [["A", "40"], ["B", "60"], ["合计", "99"]])
        proc = self.verify("--tables", self.tables, "--check", "tables")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        issues = self.issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "error")
        self.assertEqual(issues[0]["check"], "V-01")
        self.assertIn("差 1", issues[0]["detail"])
        self.assertIn("table1_summary.csv", issues[0]["where"])

    def test_category_counts_must_equal_the_note_n(self):
        write_csv(os.path.join(self.tables, "table2_counts.csv"),
                  ["类别", "频数"],
                  [["A", "40"], ["B", "60"], ["注：N=101", ""]])
        proc = self.verify("--tables", self.tables, "--check", "tables")
        self.assertEqual(proc.returncode, 2)
        issue = self.issues()[0]
        self.assertEqual(issue["check"], "V-01")
        self.assertIn("N=101", issue["detail"])

    def test_total_column_matches(self):
        write_csv(os.path.join(self.tables, "table3_wide.csv"),
                  ["项目", "甲", "乙", "合计"],
                  [["A", "1", "2", "3"], ["B", "4", "5", "9"]])
        proc = self.verify("--tables", self.tables, "--check", "tables")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.issues(), [])


class TestFigureTableCross(VerifyCase):
    """V-02 表图同值."""

    def _manifest(self, n_text):
        path = self.p("manifest.csv")
        write_csv(path, ["id", "caption"], [["Figure3", f"图3 修复责任（N={n_text}）"]])
        return path

    def test_caption_n_must_match_the_table(self):
        write_csv(os.path.join(self.tables, "table3_restore.csv"),
                  ["项目", "值"], [["样本量 N", "1358"]])
        proc = self.verify("--tables", self.tables, "--check", "cross",
                           "--figures-manifest", self._manifest("1357"),
                           "--figure-scope", "图3=sample",
                           "--table-scope", "table3_restore.csv=sample")
        self.assertEqual(proc.returncode, 2)
        issue = self.issues()[0]
        self.assertEqual(issue["check"], "V-02")
        self.assertEqual(issue["expected"], "1357")
        self.assertEqual(issue["actual"], "1358")
        self.assertIn("差 1", issue["detail"])

    def test_matching_n_passes(self):
        write_csv(os.path.join(self.tables, "table3_restore.csv"),
                  ["项目", "值"], [["样本量 N", "1358"]])
        proc = self.verify("--tables", self.tables, "--check", "cross",
                           "--figures-manifest", self._manifest("1358"),
                           "--figure-scope", "图3=sample",
                           "--table-scope", "table3_restore.csv=sample")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.issues(), [])
        pairs = [t for t in self.traces() if t["source_col"] == "V-02-pair"]
        self.assertEqual(len(pairs), 1, self.traces())
        self.assertIn("table3_restore.csv", pairs[0]["matched_by"])

    def test_same_number_without_declared_scope_is_info(self):
        write_csv(os.path.join(self.tables, "table3_restore.csv"),
                  ["项目", "值"], [["样本量 N", "2713"]])
        proc = self.verify("--tables", self.tables, "--check", "cross",
                           "--figures-manifest", self._manifest("2878"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        issue = self.issues()[0]
        self.assertEqual(issue["check"], "V-02")
        self.assertEqual(issue["severity"], "info")
        self.assertIn("未配对", issue["detail"])

    def _scope_manifest(self, n_text, scope):
        path = self.p("manifest.csv")
        write_csv(path, ["id", "caption", "n_scope"],
                  [["图3", f"图3 修复责任（N={n_text}）", scope]])
        return path

    def test_same_corpus_scope_pairs(self):
        write_csv(os.path.join(self.tables, "table3_restore.csv"),
                  ["项目", "值"], [["样本量 N", "2878"]])
        flow = self.p("flow.csv")
        write_csv(flow, ["stage", "n"], [["原始文件", "3111"], ["唯一裁判文书", "2878"]])
        proc = self.verify("--tables", self.tables, "--check", "cross",
                           "--sample-flow", flow,
                           "--figures-manifest", self._scope_manifest("2878", "corpus"),
                           "--table-scope", "table3_restore.csv=corpus")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.issues(), [])

    def test_cross_scope_is_only_a_warning(self):
        write_csv(os.path.join(self.tables, "table3_restore.csv"),
                  ["项目", "值"], [["样本量 N", "2713"]])
        flow = self.p("flow.csv")
        write_csv(flow, ["stage", "n"], [["原始文件", "3111"], ["唯一裁判文书", "2878"]])
        proc = self.verify("--tables", self.tables, "--check", "cross",
                           "--sample-flow", flow,
                           "--figures-manifest", self._scope_manifest("2878", "corpus"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        issues = self.issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "warning")
        self.assertIn("corpus", issues[0]["detail"])
        self.assertIn("sample", issues[0]["detail"])


class TestTextTrace(VerifyCase):
    """V-03 正文数字溯源."""

    def _table(self):
        write_csv(os.path.join(self.tables, "table1_n.csv"),
                  ["项目", "值"], [["样本量 N", "1358"], ["OR", "2.63"], ["占比", "0.657"]])

    def _md(self, text):
        path = self.p("paper.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_space_thousands_is_traced(self):
        self._table()
        proc = self.verify("--tables", self.tables, "--md", self._md("样本共 N=1 358 份。"),
                           "--check", "trace")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("numbers checked: 1  traced: 1", proc.stdout)
        trace = self.traces()[0]
        self.assertTrue(trace["matched_by"].startswith("tables/"), trace["matched_by"])
        self.assertEqual(trace["source_row"], "1")

    def test_unknown_number_is_an_error(self):
        self._table()
        proc = self.verify("--tables", self.tables, "--md", self._md("回归结果显示 OR=99.9。"),
                           "--check", "trace")
        self.assertEqual(proc.returncode, 2)
        issue = self.issues()[0]
        self.assertEqual(issue["check"], "V-03")
        self.assertIn("OR=99.9", issue["where"])
        self.assertEqual(self.traces()[0]["matched_by"], "none")

    def test_percent_matches_a_proportion(self):
        self._table()
        proc = self.verify("--tables", self.tables, "--md", self._md("修复责任适用率为 65.7%。"),
                           "--check", "trace")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue(self.traces()[0]["matched_by"].startswith("tables/"))

    def test_numbers_csv_is_checked_first(self):
        numbers = self.p("numbers.csv")
        write_csv(numbers, ["key", "value"], [["restore_rate", "0.657"]])
        proc = self.verify("--numbers", numbers, "--md", self._md("修复责任适用率为 65.7%。"),
                           "--check", "trace")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.traces()[0]["matched_by"], "numbers")
        self.assertIn("V-03-numbers", self.issue_checks())

    def test_ignored_numbers_become_info(self):
        self._table()
        md = self._md("人工抽读 79 份文书。")
        strict = self.verify("--tables", self.tables, "--md", md, "--check", "trace")
        self.assertEqual(strict.returncode, 2)
        proc = self.verify("--tables", self.tables, "--md", md, "--check", "trace",
                           "--ignore", r"79\s*份")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        issues = self.issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "info")
        self.assertEqual(issues[0]["check"], "V-03-ignored")
        self.assertIn("ignored: 1", proc.stdout)

    def test_statute_article_numbers_are_not_statistics(self):
        self._table()
        proc = self.verify("--tables", self.tables, "--check", "trace",
                           "--md", self._md("《民法典》第 1234 条确立修复责任，样本共 N=1358 份。"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("numbers checked: 1", proc.stdout)

    def test_p_less_than_is_checked_as_an_inequality(self):
        self._table()
        proc = self.verify("--tables", self.tables, "--md", self._md("差异显著（p<.001）。"),
                           "--check", "trace")
        # The fixture table has no p value below .001 -> this must be reported.
        self.assertEqual(proc.returncode, 2)
        self.assertIn("p<.001", self.issues()[0]["where"])


class TestFigureNumbering(VerifyCase):
    """V-04 图号连续且被引用."""

    def _manifest(self, ids):
        path = self.p("manifest.csv")
        write_csv(path, ["id", "caption"],
                  [[figure, f"{figure} 图注（N=100）"] for figure in ids])
        return path

    def test_gap_in_figure_numbers_is_an_error(self):
        manifest = self._manifest(["图1", "图3"])
        md = self.p("paper.md")
        with open(md, "w", encoding="utf-8") as handle:
            handle.write("图1 与 图3。")
        proc = self.verify("--figures-manifest", manifest, "--md", md, "--check", "figures")
        self.assertEqual(proc.returncode, 2)
        issue = self.issues()[0]
        self.assertEqual(issue["check"], "V-04")
        self.assertIn("图2", issue["actual"])

    def test_unreferenced_figure_is_a_warning(self):
        manifest = self._manifest(["图1", "图2", "图3"])
        md = self.p("paper.md")
        with open(md, "w", encoding="utf-8") as handle:
            handle.write("图1 与 图2。")
        proc = self.verify("--figures-manifest", manifest, "--md", md, "--check", "figures")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        issues = self.issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "warning")
        self.assertIn("图3", issues[0]["detail"])

        strict = self.verify("--figures-manifest", manifest, "--md", md,
                             "--check", "figures", "--fail-on-warn")
        self.assertEqual(strict.returncode, 2)


class TestModelN(VerifyCase):
    """V-05 样本 N 跨表一致."""

    def test_fitted_n_is_used_instead_of_missing_row_exclusion_count(self):
        write_csv(os.path.join(self.tables, "coef_M1.csv"),
                  ["model", "term", "n", "sample"], [["M1", "x", 5, "full"]])
        for dropped in (0, 2, ""):
            with self.subTest(n_dropna=dropped):
                write_csv(os.path.join(self.tables, "fit.csv"),
                          ["model", "n", "n_dropna", "subset"], [["M1", 5, dropped, "full"]])
                proc = self.verify("--tables", self.tables, "--check", "cross", "--fail-on-warn")
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertFalse([r for r in self.issues() if r["check"] == "V-05"])

    def test_real_estimation_n_mismatch_is_still_an_error(self):
        write_csv(os.path.join(self.tables, "coef_M1.csv"),
                  ["model", "term", "n"], [["M1", "x", 5]])
        write_csv(os.path.join(self.tables, "fit.csv"),
                  ["model", "n", "n_dropna"], [["M1", 4, 0]])
        proc = self.verify("--tables", self.tables, "--check", "cross")
        self.assertEqual(proc.returncode, 2)
        issue = next(r for r in self.issues() if r["check"] == "V-05")
        self.assertEqual(issue["actual"], "4")

    def test_missing_estimation_n_cannot_fall_back_to_exclusion_count(self):
        write_csv(os.path.join(self.tables, "coef_M1.csv"),
                  ["model", "term", "n"], [["M1", "x", 5]])
        for header, row in [(["model", "n_dropna"], ["M1", 0]),
                            (["model", "n", "n_dropna"], ["M1", "", 0])]:
            with self.subTest(header=header):
                write_csv(os.path.join(self.tables, "fit.csv"), header, [row])
                proc = self.verify("--tables", self.tables, "--check", "cross", "--fail-on-warn")
                self.assertEqual(proc.returncode, 2)
                issues = [r for r in self.issues() if r["check"] == "V-05"]
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0]["severity"], "warning")
                self.assertIn("无法核对", issues[0]["detail"])

    def test_real_ols_outputs_pass_cross_check_with_and_without_missing_rows(self):
        spec = self.p("ols_spec.json")
        with open(spec, "w", encoding="utf-8") as stream:
            json.dump({"models": [{"id": "M1", "type": "ols", "outcome": "y",
                                   "predictors": ["x"], "dropna": True}]}, stream)
        complete = [[0, 1], [1, 2], [2, 1], [3, 4], [4, 3]]
        for missing in ([], [[5, ""], ["", 6]]):
            with self.subTest(excluded=len(missing)):
                data = self.p("ols_data.csv")
                write_csv(data, ["x", "y"], complete + missing)
                model = run("auto_stats.py", "--data", data, "--spec", spec,
                            "--out", self.tables, "--only", "models")
                self.assertEqual(model.returncode, 0, model.stdout + model.stderr)
                fit = read_csv(os.path.join(self.tables, "fit.csv"))[0]
                self.assertEqual(int(fit["n"]), 5)
                self.assertEqual(int(fit["n_dropna"]), len(missing))
                proc = self.verify("--tables", self.tables, "--check", "cross", "--fail-on-warn")
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertFalse([r for r in self.issues() if r["check"] == "V-05"])

    def test_two_models_with_different_n_is_an_error(self):
        write_csv(os.path.join(self.tables, "coef_a.csv"),
                  ["term", "n", "n_scope"], [["x", "1358", "sample"]])
        write_csv(os.path.join(self.tables, "coef_b.csv"),
                  ["term", "n", "n_scope"], [["x", "1357", "sample"]])
        proc = self.verify("--tables", self.tables, "--check", "cross")
        self.assertEqual(proc.returncode, 2)
        issue = next(item for item in self.issues() if item["check"] == "V-05")
        self.assertIn("coef_b.csv", issue["where"])
        self.assertIn("1358", issue["detail"])

    def test_documented_subsample_is_allowed(self):
        write_csv(os.path.join(self.tables, "coef_a.csv"),
                  ["term", "n", "n_scope"], [["x", "1358", "sample"]])
        write_csv(os.path.join(self.tables, "coef_b.csv"),
                  ["term", "n", "n_scope", "sample"],
                  [["x", "1240", "sample", "剔除 2026 年"]])
        proc = self.verify("--tables", self.tables, "--check", "cross")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertFalse([item for item in self.issues() if item["check"] == "V-05"])


class TestSampleFlow(VerifyCase):
    """V-06 漏斗对账."""

    def _flow(self, rows):
        path = self.p("sample_flow.csv")
        write_csv(path, ["stage", "n"], rows)
        return path

    def test_non_monotonic_funnel_is_an_error(self):
        flow = self._flow([["原始文件", "100"], ["可读 PDF", "90"], ["分析样本", "95"]])
        proc = self.verify("--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 2)
        issue = self.issues()[0]
        self.assertEqual(issue["check"], "V-06")
        self.assertIn("95", issue["detail"])
        self.assertIn("90", issue["detail"])

    def test_monotonic_funnel_passes(self):
        flow = self._flow([["原始文件", "100"], ["可读 PDF", "90"], ["分析样本", "80"]])
        proc = self.verify("--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.issues(), [])

    def test_check_flow_does_not_run_table_checks(self):
        write_csv(os.path.join(self.tables, "table1_bad.csv"),
                  ["类别", "频数"], [["A", "1"], ["B", "2"], ["合计", "99"]])
        flow = self._flow([["原始文件", "100"], ["分析样本", "101"]])
        proc = self.verify("--tables", self.tables, "--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual([issue["check"] for issue in self.issues()], ["V-06"])

    def test_excluded_rows_do_not_break_monotonicity(self):
        flow = self.p("sample_flow.csv")
        write_csv(flow, ["stage", "n", "kind"],
                  [["原始文件", "100", "stage"], ["非资料文件", "90", "excluded"],
                   ["可读 PDF", "80", "stage"], ["重复副本", "20", "excluded"]])
        proc = self.verify("--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.issues(), [])

    def test_excluded_larger_than_its_stage_is_an_error(self):
        flow = self.p("sample_flow.csv")
        write_csv(flow, ["stage", "n", "kind"],
                  [["原始文件", "100", "stage"], ["非资料文件", "120", "excluded"]])
        proc = self.verify("--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 2)
        issue = self.issues()[0]
        self.assertEqual(issue["check"], "V-06")
        self.assertIn("剔除", issue["detail"])

    def test_missing_kind_column_error_explains_the_fix(self):
        flow = self._flow([["原始文件", "100"], ["分析样本", "101"]])
        proc = self.verify("--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 2)
        detail = self.issues()[0]["detail"]
        self.assertIn("加一列 kind", detail)
        self.assertIn("该行缺 kind，按 stage 处理", detail)
        self.assertIn("kind=excluded|model", detail)
        trace = [item for item in self.traces() if item["source_col"] == "kind"]
        self.assertEqual(len(trace), 1, self.traces())
        self.assertIn("sample_flow.csv", trace[0]["source_file"])
        self.assertIn("assumed stage", trace[0]["matched_by"])

    def test_model_rows_are_a_subset_of_their_stage(self):
        flow = self.p("sample_flow.csv")
        write_csv(flow, ["stage", "n", "kind", "note"],
                  [["原始文件", "100", "stage", ""],
                   ["分析样本", "80", "stage", ""],
                   ["模型1", "50", "model", "stage=分析样本"],
                   ["模型2", "80", "model", "stage=分析样本"]])
        proc = self.verify("--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.issues(), [])

    def test_model_row_without_stage_note_is_an_error(self):
        flow = self.p("sample_flow.csv")
        write_csv(flow, ["stage", "n", "kind", "note"],
                  [["原始文件", "100", "stage", ""],
                   ["模型1", "50", "model", ""]])
        proc = self.verify("--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("note", self.issues()[0]["detail"])

    def test_model_row_larger_than_its_stage_is_an_error(self):
        flow = self.p("sample_flow.csv")
        write_csv(flow, ["stage", "n", "kind", "note"],
                  [["原始文件", "100", "stage", ""],
                   ["分析样本", "80", "stage", ""],
                   ["模型1", "90", "model", "stage=分析样本"]])
        proc = self.verify("--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("子集", self.issues()[0]["detail"])

    def test_illegal_kind_lists_the_three_values(self):
        flow = self.p("sample_flow.csv")
        write_csv(flow, ["stage", "n", "kind"], [["原始文件", "100", "other"]])
        proc = self.verify("--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 2)
        detail = self.issues()[0]["detail"]
        for word in ("stage", "excluded", "model"):
            self.assertIn(word, detail)


class TestContract(VerifyCase):
    """输入/输出契约与退出码."""

    def test_empty_input_is_an_error(self):
        proc = self.verify()
        self.assertEqual(proc.returncode, 2)
        issues = self.issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["check"], "input")
        self.assertIn("nothing to verify", issues[0]["detail"])

    def test_output_columns_are_fixed(self):
        write_csv(os.path.join(self.tables, "table1_bad.csv"),
                  ["类别", "频数"], [["A", "1"], ["B", "2"], ["合计", "99"]])
        self.verify("--tables", self.tables, "--check", "tables")
        self.assertEqual(list(self.issues()[0].keys()),
                         ["severity", "check", "where", "expected", "actual", "detail"])
        self.assertEqual(list(self.traces()[0].keys()) if self.traces() else [
            "number", "source_file", "source_row", "source_col", "matched_by"],
            ["number", "source_file", "source_row", "source_col", "matched_by"])

    def test_unreadable_docx_is_a_located_error(self):
        write_csv(os.path.join(self.tables, "table1_n.csv"),
                  ["项目", "值"], [["样本量 N", "1358"]])
        bad = self.p("broken.docx")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("这不是一个 docx 文件")
        proc = self.verify("--tables", self.tables, "--docx", bad, "--check", "trace")
        self.assertEqual(proc.returncode, 2)
        issue = self.issues()[0]
        self.assertEqual(issue["check"], "parse")
        self.assertIn("broken.docx", issue["where"])
        self.assertRegex(issue["detail"], r"Error|Exception")

    def test_docx_paragraphs_are_traced(self):
        write_csv(os.path.join(self.tables, "table1_n.csv"),
                  ["项目", "值"], [["样本量 N", "1358"]])
        docx = make_docx(self.p("paper.docx"), ["样本共 N=1358 份。"])
        proc = self.verify("--tables", self.tables, "--docx", docx, "--check", "trace")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("traced: 1", proc.stdout)

    def test_run_json_records_the_script_version(self):
        write_csv(os.path.join(self.tables, "table1_ok.csv"),
                  ["类别", "频数"], [["A", "1"], ["B", "2"], ["合计", "3"]])
        self.verify("--tables", self.tables, "--check", "tables")
        with open(os.path.join(self.out, "run.json"), encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["script"], "verify_numbers.py")
        self.assertEqual(payload["version"], "1.0.1")

    def test_stdout_summary_reports_both_counts(self):
        write_csv(os.path.join(self.tables, "table1_bad.csv"),
                  ["类别", "频数"], [["A", "1"], ["B", "2"], ["合计", "99"]])
        proc = self.verify("--tables", self.tables, "--check", "tables")
        self.assertRegex(proc.stdout, r"numbers checked: 0\s+traced: 0\s+issues: 1 error / 0 warning")


class TestSemanticEvidence(VerifyCase):
    """R3-01: V-03 evidence must measure the same thing as the prose number."""

    def _table(self, header, rows, name="table1_models.csv"):
        write_csv(os.path.join(self.tables, name), header, rows)

    def _md(self, text):
        path = self.p("paper.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_p_value_cannot_prove_a_percentage(self):
        # 0.0494 in a p column is a probability, not a share: 4.94% must fail.
        self._table(["检验", "p"], [["χ²", "0.0494"]])
        proc = self.verify("--tables", self.tables, "--check", "trace",
                           "--md", self._md("修复责任适用率为 4.94%。"))
        self.assertEqual(proc.returncode, 2, proc.stdout)
        issue = self.issues()[0]
        self.assertEqual(issue["check"], "V-03")
        self.assertIn("4.94%", issue["where"])
        self.assertIn("pct", issue["detail"])

    def test_estimate_cannot_prove_a_sample_size(self):
        # An estimate of 1358 is not a count: N=1,358 must fail.
        self._table(["term", "est"], [["修复责任", "1358"]])
        proc = self.verify("--tables", self.tables, "--check", "trace",
                           "--md", self._md("样本共 N=1,358 份。"))
        self.assertEqual(proc.returncode, 2, proc.stdout)
        issue = self.issues()[0]
        self.assertEqual(issue["check"], "V-03")
        self.assertIn("count", issue["detail"])

    def test_count_column_still_traces_a_count(self):
        self._table(["项目", "N"], [["分析样本", "1358"]])
        proc = self.verify("--tables", self.tables, "--check", "trace",
                           "--md", self._md("样本共 N=1,358 份。"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue(self.traces()[0]["matched_by"].startswith("tables/"))


class TestPValueOperators(VerifyCase):
    """R3-02: p<.001 in the prose matches p<0.001 in the table."""

    def _table(self, p_cell):
        write_csv(os.path.join(self.tables, "table1_tests.csv"),
                  ["检验", "p"], [["χ²", p_cell]])

    def _md(self, text):
        path = self.p("paper.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_same_bound_matches(self):
        self._table("<0.001")
        proc = self.verify("--tables", self.tables, "--check", "trace",
                           "--md", self._md("差异显著（p<.001）。"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.issues(), [])

    def test_concrete_p_below_the_bound_passes(self):
        self._table("0.0009")
        proc = self.verify("--tables", self.tables, "--check", "trace",
                           "--md", self._md("差异显著（p<.01）。"))
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_concrete_p_above_the_bound_is_an_error(self):
        self._table("0.0494")
        proc = self.verify("--tables", self.tables, "--check", "trace",
                           "--md", self._md("差异显著（p<.01）。"))
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(self.issues()[0]["check"], "V-03")

    def test_exact_p_needs_an_exact_table_value(self):
        self._table("<0.001")
        proc = self.verify("--tables", self.tables, "--check", "trace",
                           "--md", self._md("差异显著（p=0.001）。"))
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("上界", self.issues()[0]["detail"])


class TestMissingInputs(VerifyCase):
    """R3-03: a run must not silently skip a check it cannot perform."""

    def test_check_all_with_only_a_manifest_reports_missing_inputs(self):
        manifest = self.p("manifest.csv")
        write_csv(manifest, ["id", "caption"], [["图1", "图1 描述（N=100）"]])
        proc = self.verify("--figures-manifest", manifest, "--check", "all")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        details = " ".join(issue["detail"] for issue in self.issues())
        self.assertIn("missing input --tables", details)
        self.assertIn("missing input --sample-flow", details)
        checks = {issue["check"] for issue in self.issues() if issue["severity"] == "error"}
        self.assertTrue({"V-01", "V-03", "V-06"} <= checks, checks)

    def test_single_check_group_without_its_input_is_an_error(self):
        proc = self.verify("--md", self._md("样本共 N=1358 份。"), "--check", "trace")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("missing input", " ".join(i["detail"] for i in self.issues()))

    def _md(self, text):
        path = self.p("paper.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path


class TestModelScopeGrouping(VerifyCase):
    """R3-04/R3-07: sample=full must not switch V-05 off; scope aliases unify."""

    def test_full_sample_still_compares_models(self):
        write_csv(os.path.join(self.tables, "coef_a.csv"),
                  ["term", "n", "n_scope", "sample"], [["x", "1358", "sample", "full"]])
        write_csv(os.path.join(self.tables, "coef_b.csv"),
                  ["term", "n", "n_scope", "sample"], [["x", "1357", "sample", "full"]])
        proc = self.verify("--tables", self.tables, "--check", "cross")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual([i["check"] for i in self.issues()], ["V-05"])

    def test_scope_alias_is_normalised(self):
        write_csv(os.path.join(self.tables, "coef_a.csv"),
                  ["term", "n", "n_scope"], [["x", "1358", "样本"]])
        write_csv(os.path.join(self.tables, "coef_b.csv"),
                  ["term", "n", "n_scope"], [["x", "1357", "sample"]])
        proc = self.verify("--tables", self.tables, "--check", "cross")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual([i["check"] for i in self.issues()], ["V-05"])

    def test_other_scope_is_excluded_with_a_trace(self):
        write_csv(os.path.join(self.tables, "coef_a.csv"),
                  ["term", "n", "n_scope"], [["x", "1358", "sample"]])
        write_csv(os.path.join(self.tables, "coef_b.csv"),
                  ["term", "n", "n_scope"], [["x", "2878", "corpus"]])
        proc = self.verify("--tables", self.tables, "--check", "cross")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertTrue([t for t in self.traces() if t["source_col"] == "V-05-scope"])


class TestMixedFunnel(VerifyCase):
    """R3-15: a kind-less funnel collapses its cascading errors."""

    def test_mixed_funnel_is_one_error_plus_infos(self):
        flow = self.p("sample_flow.csv")
        write_csv(flow, ["stage", "n"],
                  [["原始文件", "100"], ["非资料文件", "5"],
                   ["可读 PDF", "90"], ["重复副本", "4"], ["分析样本", "95"]])
        proc = self.verify("--sample-flow", flow, "--check", "flow")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        issues = self.issues()
        errors = [issue for issue in issues if issue["severity"] == "error"]
        infos = [issue for issue in issues if issue["severity"] == "info"]
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("漏斗混排", errors[0]["detail"])
        self.assertEqual(len(infos), 2)
        self.assertTrue(all(issue["check"] == "V-06" for issue in issues))


class TestReportContract(unittest.TestCase):
    """P1: severity typos must not silently defeat --fail-on-warn."""

    def test_unknown_severity_raises(self):
        import verify_numbers

        report = verify_numbers.Report()
        with self.assertRaises(ValueError):
            report.add("fatal", "V-03", "x")


class TestIgnoreContract(VerifyCase):
    """P1: an ignored number is an info row, never a warning."""

    def test_info_rows_do_not_trigger_fail_on_warn(self):
        write_csv(os.path.join(self.tables, "table1_n.csv"),
                  ["项目", "值"], [["样本量 N", "1358"]])
        md = self.p("paper.md")
        with open(md, "w", encoding="utf-8") as handle:
            handle.write("人工抽读 79 份文书。")
        proc = self.verify("--tables", self.tables, "--md", md, "--check", "trace",
                           "--ignore", r"79\s*份", "--fail-on-warn")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("ignored: 1 (by --ignore)", proc.stdout)


class TestManifestOrder(VerifyCase):
    """A chart-pack manifest carries package ids (F01), not book figure numbers."""

    def _manifest(self, rows):
        path = self.p("manifest.csv")
        write_csv(path, ["id", "caption", "n", "status"], rows)
        return path

    def _table(self):
        write_csv(os.path.join(self.tables, "table1_ok.csv"),
                  ["类别", "频数"], [["A", "1"], ["B", "2"], ["合计", "3"]])

    def test_package_ids_map_to_manifest_order(self):
        self._table()
        manifest = self._manifest([["F01", "注：N=1,000", "1000", "ok"],
                                   ["F02", "注：N=1,000", "1000", "ok"],
                                   ["F03", "注：N=1,000", "1000", "failed"]])
        proc = self.verify("--tables", self.tables, "--check", "cross",
                           "--figures-manifest", manifest)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertFalse([issue for issue in self.issues()
                          if issue["check"] == "V-02" and issue["severity"] == "error"])
        traces = [trace for trace in self.traces() if trace["matched_by"] == "manifest-order"]
        self.assertEqual([trace["number"] for trace in traces], ["图1", "图2"])

    def test_explicit_figure_no_wins_over_row_order(self):
        self._table()
        manifest = self._manifest([["F01", "图7 描述（N=1,000）", "1000", "ok"]])
        proc = self.verify("--tables", self.tables, "--check", "cross",
                           "--figures-manifest", manifest)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertFalse([trace for trace in self.traces()
                          if trace["matched_by"] == "manifest-order"])

    def test_two_rows_with_one_figure_number_is_an_error(self):
        self._table()
        manifest = self._manifest([["图1", "注：N=1,000", "1000", "ok"],
                                   ["图1", "注：N=1,000", "1000", "ok"]])
        proc = self.verify("--tables", self.tables, "--check", "cross",
                           "--figures-manifest", manifest)
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("图号", " ".join(issue["where"] for issue in self.issues()))


class TestFigureData(VerifyCase):
    """--figure-data: numbers printed inside a figure get a declared source."""

    def _data(self, rows):
        path = self.p("figure_data.csv")
        write_csv(path, ["figure", "label", "value"], rows)
        return path

    def _md(self, text):
        path = self.p("paper.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_a_count_printed_in_a_figure_is_info(self):
        data = self._data([["图2c", "案件数", "808"]])
        proc = self.verify("--figure-data", data, "--check", "trace",
                           "--md", self._md("年份分布呈单峰（808 件）。"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        issues = self.issues()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "info")
        self.assertEqual(issues[0]["check"], "V-03-figure")
        trace = self.traces()[0]
        self.assertEqual(trace["matched_by"], "figure-data")
        self.assertEqual(trace["source_col"], "value")
        self.assertIn("figure_data.csv", trace["source_file"])

    def test_an_amount_cannot_prove_a_p_value(self):
        data = self._data([["图3", "平均修复金额", "13200"]])
        proc = self.verify("--figure-data", data, "--check", "trace",
                           "--md", self._md("差异显著（p<.001）。"))
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(self.issues()[0]["check"], "V-03")
        self.assertEqual(self.traces()[0]["matched_by"], "none")

    def test_an_amount_cannot_prove_an_estimate(self):
        data = self._data([["图3", "平均修复金额", "13200"]])
        proc = self.verify("--figure-data", data, "--check", "trace",
                           "--md", self._md("修复责任提高（OR=1.32）。"))
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(self.issues()[0]["check"], "V-03")

    def test_figure_data_wins_over_numbers(self):
        data = self._data([["图2c", "案件数", "808"]])
        numbers = self.p("numbers.csv")
        write_csv(numbers, ["value"], [["808"]])
        proc = self.verify("--figure-data", data, "--numbers", numbers, "--check", "trace",
                           "--md", self._md("年份分布呈单峰（808 件）。"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.traces()[0]["matched_by"], "figure-data")

    def test_numbers_csv_accepts_counts(self):
        numbers = self.p("numbers.csv")
        write_csv(numbers, ["value"], [["3107"], ["5750"], ["79"], ["23"], ["808"]])
        proc = self.verify("--numbers", numbers, "--check", "trace",
                           "--md", self._md("共 3 107 份；抽样 5 750 个；抽读 79 份、23 份；单峰 808 件。"))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual([t["matched_by"] for t in self.traces()], ["numbers"] * 5)
        self.assertEqual(self.issues()[0]["check"], "V-03-numbers")


if __name__ == "__main__":
    unittest.main()
