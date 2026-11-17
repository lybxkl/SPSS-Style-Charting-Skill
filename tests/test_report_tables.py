# -*- coding: utf-8 -*-
"""report_tables.py: the full report pack is traceable to dataset bytes.

Every report file is listed in report_index.json with its sha256; the index
also anchors the dataset (and the cleaning log, when given) so a number in
any table can be traced back to the exact input. Roles are declared, kinds
are mechanical facts, refusals exit 2.
"""
import hashlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempCase, run, write_csv, read_csv


def analysis_dataset(path: str) -> str:
    return write_csv(path, ["id", "gender", "age", "city", "score", "income"], [
        ["001", "男", "34", "北京", "3.5", "5000"],
        ["002", "女", "29", "上海", "4.0", "6000"],
        ["003", "男", "200", "南京", "", "7000"],
        ["004", "女", "45", "上海", "2.5", "8000"],
        ["005", "", "41", "北京", "3.0", ""],
        ["005", "", "41", "北京", "3.0", ""],
    ])


def run_reports(dataset, out, *extra):
    return run("report_tables.py", "--dataset", dataset, "--out", out, *extra)


def row_by(rows, **match):
    for row in rows:
        if all(row.get(key) == value for key, value in match.items()):
            return row
    raise AssertionError(f"no row matches {match}")


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class TestFullPack(TempCase):
    def setUp(self):
        super().setUp()
        self.data = analysis_dataset(self.p("analysis.csv"))
        self.out = self.p("reports")
        proc = run_reports(self.data, self.out, "--id", "id",
                            "--outcome", "score",
                            "--crosstab", "gender,city")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_variable_report_profiles_every_column(self):
        rows = read_csv(os.path.join(self.out, "variable_report.csv"))
        self.assertEqual(len(rows), 6)
        gender = row_by(rows, column="gender")
        self.assertEqual(gender["kind"], "categorical")
        self.assertEqual(gender["role"], "variable")
        self.assertEqual(int(gender["n_missing"]), 2)
        age = row_by(rows, column="age")
        self.assertEqual(age["kind"], "numeric")
        self.assertEqual(age["n_non_numeric"], "0")
        score = row_by(rows, column="score")
        self.assertEqual(score["role"], "outcome")
        ident = row_by(rows, column="id")
        self.assertEqual(ident["role"], "id")

    def test_descriptive_stats_match_hand_computation(self):
        rows = read_csv(os.path.join(self.out, "descriptive_stats.csv"))
        age = row_by(rows, variable="age")
        # ages 34,29,200,45,41,41: mean 65, median 41, IQR 44-35.75
        self.assertEqual(age["n"], "6")
        self.assertEqual(age["n_missing"], "0")
        self.assertEqual(age["mean"], "65")
        self.assertEqual(age["median"], "41")
        self.assertEqual(age["min"], "29")
        self.assertEqual(age["max"], "200")
        self.assertEqual(age["p25"], "35.75")
        self.assertEqual(age["p75"], "44")
        self.assertEqual(age["iqr"], "8.25")
        score = row_by(rows, variable="score")
        self.assertEqual(score["n"], "5")
        self.assertEqual(score["n_missing"], "1")

    def test_frequency_tables_show_missing_and_cumulative(self):
        rows = read_csv(os.path.join(self.out, "frequency_tables.csv"))
        genders = [row for row in rows if row["variable"] == "gender"]
        self.assertEqual(len(genders), 3)
        self.assertEqual({row["value"] for row in genders},
                         {"男", "女", "(缺失)"})
        for row in genders:
            self.assertEqual(row["n"], "2")
            self.assertEqual(row["pct"], "33.3333")
        missing = row_by(genders, value="(缺失)")
        self.assertEqual(missing["cumulative_pct"], "33.3333")
        # id column never appears as a variable
        self.assertFalse(any(row["variable"] == "id" for row in rows))

    def test_crosstab_cells_and_row_percentages(self):
        rows = read_csv(os.path.join(self.out, "crosstabs.csv"))
        self.assertEqual(len(rows), 4)
        cell = row_by(rows, var_a="gender", value_a="男", value_b="北京")
        self.assertEqual(cell["n"], "1")
        self.assertEqual(cell["pct_within_a"], "50")
        cell = row_by(rows, var_a="gender", value_a="(缺失)", value_b="北京")
        self.assertEqual(cell["n"], "2")
        self.assertEqual(cell["pct_within_a"], "100")
        cell = row_by(rows, var_a="gender", value_a="女", value_b="上海")
        self.assertEqual(cell["n"], "2")
        self.assertEqual(cell["pct_within_a"], "100")

    def test_missing_report_and_patterns(self):
        rows = read_csv(os.path.join(self.out, "missing_report.csv"))
        self.assertEqual(int(row_by(rows, variable="income")["n_missing"]), 2)
        self.assertEqual(int(row_by(rows, variable="gender")["n_missing"]), 2)
        self.assertEqual(int(row_by(rows, variable="score")["n_missing"]), 1)
        patterns = read_csv(os.path.join(self.out, "missing_patterns.csv"))
        by_pattern = {row["pattern"]: row for row in patterns}
        self.assertEqual(by_pattern["(无缺失)"]["n_rows"], "3")
        self.assertEqual(by_pattern["gender;income"]["n_rows"], "2")
        self.assertEqual(by_pattern["score"]["n_rows"], "1")
        self.assertEqual(by_pattern["(无缺失)"]["pct"], "50")

    def test_duplicate_report_lists_id_and_full_row(self):
        rows = read_csv(os.path.join(self.out, "duplicate_report.csv"))
        id_row = row_by(rows, duplicate_kind="id", key="005")
        self.assertEqual(id_row["n_rows"], "2")
        self.assertEqual(id_row["n_extra"], "1")
        full = row_by(rows, duplicate_kind="full_row")
        self.assertEqual(full["n_rows"], "2")
        self.assertEqual(full["n_extra"], "1")

    def test_report_index_anchors_every_file(self):
        with open(os.path.join(self.out, "report_index.json"),
                  encoding="utf-8") as handle:
            index = json.load(handle)
        with open(self.data, "rb") as handle:
            dataset_sha = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(index["dataset"]["sha256"], dataset_sha)
        self.assertEqual(index["dataset"]["n_rows"], 6)
        self.assertEqual(index["args"]["id"], "id")
        names = {item["file"] for item in index["reports"]}
        self.assertIn("variable_report.csv", names)
        self.assertIn("crosstabs.csv", names)
        self.assertIn("data_report.md", names)
        for item in index["reports"]:
            path = os.path.join(self.out, item["file"])
            self.assertTrue(os.path.isfile(path), item["file"])
            with open(path, "rb") as handle:
                self.assertEqual(hashlib.sha256(handle.read()).hexdigest(),
                                 item["sha256"], item["file"])

    def test_master_report_mentions_chain_and_basis(self):
        with open(os.path.join(self.out, "data_report.md"),
                  encoding="utf-8") as handle:
            md = handle.read()
        self.assertIn("数据报表", md)
        self.assertIn("溯源", md)
        self.assertIn("G1/G2", md)


class TestChainsAndInputs(TempCase):
    def test_cleaning_log_is_recorded_in_index(self):
        data = analysis_dataset(self.p("analysis.csv"))
        recipe = self.p("recipe.json")
        with open(recipe, "w", encoding="utf-8") as handle:
            json.dump({"recipe_version": 1, "id_columns": [],
                       "max_drop_fraction": 0.5, "steps": []}, handle)
        log_dir = self.p("cleaning")
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", recipe, "--out", log_dir
                             ).returncode, 0)
        out = self.p("reports")
        proc = run_reports(data, out, "--id", "id", "--cleaning-log",
                           os.path.join(log_dir, "cleaning_log.jsonl"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(out, "report_index.json"),
                  encoding="utf-8") as handle:
            index = json.load(handle)
        log_path = os.path.join(log_dir, "cleaning_log.jsonl")
        with open(log_path, "rb") as handle:
            sha = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(index["cleaning_log"]["sha256"], sha)
        with open(os.path.join(out, "data_report.md"),
                  encoding="utf-8") as handle:
            self.assertIn("清洗链", handle.read())

    def test_missing_reasons_file_is_copied_and_anchored(self):
        data = analysis_dataset(self.p("analysis.csv"))
        reasons = write_csv(self.p("missing_by_source.csv"),
                            ["field", "bucket", "n", "share_of_na"], [
                                ["score", "not_found", "1", "1.0"],
                                ["score", "na_phrase", "0", "0.0"],
                            ])
        out = self.p("reports")
        proc = run_reports(data, out, "--missing-reasons", reasons)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        copied = read_csv(os.path.join(out, "missing_reasons_by_field.csv"))
        self.assertEqual(len(copied), 2)
        self.assertEqual(copied[0]["bucket"], "not_found")
        with open(os.path.join(out, "report_index.json"),
                  encoding="utf-8") as handle:
            index = json.load(handle)
        self.assertEqual(index["missing_reasons"]["n_rows"], 2)

    def test_missing_reasons_bad_header_refused(self):
        data = analysis_dataset(self.p("analysis.csv"))
        bad = write_csv(self.p("bad.csv"), ["field", "n"], [["score", "1"]])
        proc = run_reports(data, self.p("reports"), "--missing-reasons", bad)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must have columns", proc.stderr)


class TestRefusalsAndKinds(TempCase):
    def test_unknown_id_or_outcome_column(self):
        data = analysis_dataset(self.p("analysis.csv"))
        self.assertEqual(run_reports(data, self.p("r1"), "--id", "nope"
                                     ).returncode, 2)
        self.assertEqual(run_reports(data, self.p("r2"), "--outcome", "nope"
                                     ).returncode, 2)

    def test_crosstab_spec_must_have_two_columns(self):
        data = analysis_dataset(self.p("analysis.csv"))
        proc = run_reports(data, self.p("r"), "--crosstab", "a,b,c")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("two columns", proc.stderr)
        proc = run_reports(data, self.p("r"), "--crosstab", "gender,missing")
        self.assertEqual(proc.returncode, 2)

    def test_missing_or_empty_dataset(self):
        self.assertEqual(run_reports(self.p("none.csv"), self.p("r")
                                     ).returncode, 2)
        empty = write_csv(self.p("empty.csv"), ["id", "x"], [])
        self.assertEqual(run_reports(empty, self.p("r")).returncode, 2)

    def test_extra_field_rows_are_refused_not_absorbed(self):
        path = self.p("bad.csv")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("id,x\n1,2,3,4\n")
        proc = run_reports(path, self.p("r"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("field count differs from the header", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_high_cardinality_becomes_text_and_skips(self):
        data = write_csv(self.p("analysis.csv"), ["id", "city", "note"], [
            ["1", "北京", "a"], ["2", "上海", "b"], ["3", "南京", "c"],
            ["4", "广州", "d"],
        ])
        out = self.p("reports")
        proc = run_reports(data, out, "--max-cardinality", "3",
                           "--crosstab", "city,note")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = read_csv(os.path.join(out, "variable_report.csv"))
        self.assertEqual(row_by(rows, column="city")["kind"], "text")
        freq = read_csv(os.path.join(out, "frequency_tables.csv"))
        self.assertFalse(any(row["variable"] == "city" for row in freq))
        with open(os.path.join(out, "report_index.json"),
                  encoding="utf-8") as handle:
            index = json.load(handle)
        self.assertTrue(any("crosstab" in item["reason"]
                            for item in index["skipped"]))

    def test_nan_spelling_is_a_value_not_a_number(self):
        data = write_csv(self.p("analysis.csv"), ["id", "score"], [
            ["1", "1.5"], ["2", "NaN"], ["3", "2.5"]])
        out = self.p("reports")
        self.assertEqual(run_reports(data, out).returncode, 0)
        rows = read_csv(os.path.join(out, "variable_report.csv"))
        score = row_by(rows, column="score")
        self.assertEqual(score["kind"], "categorical")
        self.assertEqual(score["n_non_numeric"], "1")

    def test_numeric_crosstab_is_skipped_visibly(self):
        data = analysis_dataset(self.p("analysis.csv"))
        out = self.p("reports")
        proc = run_reports(data, out, "--crosstab", "age,gender")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(out, "report_index.json"),
                  encoding="utf-8") as handle:
            index = json.load(handle)
        self.assertTrue(any("age" in item["reason"]
                            for item in index["skipped"]))

    def test_small_n_leaves_skew_kurtosis_blank(self):
        data = write_csv(self.p("analysis.csv"), ["id", "x"], [
            ["1", "1"], ["2", "2"]])
        out = self.p("reports")
        self.assertEqual(run_reports(data, out).returncode, 0)
        rows = read_csv(os.path.join(out, "descriptive_stats.csv"))
        self.assertEqual(rows[0]["skew"], "")
        self.assertEqual(rows[0]["kurtosis"], "")
        self.assertNotEqual(rows[0]["sd"], "")


class TestAuditFixes(TempCase):
    """Findings from the independent audit round: frequency caps, warnings,
    encoding fallbacks, id_missing visibility, collision documentation."""

    def test_numeric_high_cardinality_leaves_frequency_visibly(self):
        rows = [["id", str(i)] for i in range(300)]
        data = write_csv(self.p("analysis.csv"), ["id", "income"], rows)
        out = self.p("reports")
        proc = run_reports(data, out, "--max-cardinality", "50")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        freq = read_csv(os.path.join(out, "frequency_tables.csv"))
        self.assertFalse(any(row["variable"] == "income" for row in freq))
        with open(os.path.join(out, "report_index.json"),
                  encoding="utf-8") as handle:
            index = json.load(handle)
        skipped = [item for item in index["skipped"]
                   if item["item"] == "frequency:income"]
        self.assertEqual(len(skipped), 1)
        self.assertIn("300 unique values", skipped[0]["reason"])
        # the column itself is still fully profiled
        var = read_csv(os.path.join(out, "variable_report.csv"))
        self.assertEqual(row_by(var, column="income")["kind"], "numeric")

    def test_gb18030_dataset_is_read_by_both_scripts(self):
        payload = "id,city\n1,北京\n2,上海\n3,北京\n"
        path = self.p("gb.csv")
        with open(path, "w", encoding="gb18030", newline="") as handle:
            handle.write(payload)
        out = self.p("reports")
        proc = run_reports(path, out, "--id", "id")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        var = read_csv(os.path.join(out, "variable_report.csv"))
        city = row_by(var, column="city")
        self.assertEqual(city["n"], "3")
        self.assertEqual(city["top_value"], "北京")
        self.assertEqual(city["top_value_n"], "2")
        # and the cleaning engine reads it too
        recipe = self.p("recipe.json")
        with open(recipe, "w", encoding="utf-8") as handle:
            json.dump({"recipe_version": 1, "id_columns": ["id"],
                       "max_drop_fraction": 1.0, "steps": []}, handle)
        clean_out = self.p("cleaning")
        proc = run("clean_data.py", "--dataset", path, "--recipe", recipe,
                   "--out", clean_out)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_cleaning_row_mismatch_is_a_visible_warning(self):
        # the full recipe cleans 6 rows down to 3; a 5-row analysis table
        # anchored to that log is stale and must be called out
        data = analysis_dataset(self.p("analysis.csv"))
        recipe = self.p("recipe.json")
        with open(recipe, "w", encoding="utf-8") as handle:
            json.dump({"recipe_version": 1, "id_columns": ["id"],
                       "max_drop_fraction": 0.5, "steps": [
                           {"op": "drop_exact_duplicates",
                            "columns": ["id", "gender", "age", "city",
                                        "score", "income"]},
                           {"op": "coerce_type", "column": "score",
                            "to": "float", "on_fail": "missing"},
                           {"op": "drop_rows_if_missing",
                            "columns": ["score"], "mode": "any",
                            "reason": "score missing"}]}, handle,
                      ensure_ascii=False)
        cleaning_out = self.p("cleaning")
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", recipe, "--out", cleaning_out
                             ).returncode, 0)
        stale = write_csv(self.p("stale.csv"),
                          ["id", "gender", "age", "city", "score",
                           "income"], [
                              ["001", "男", "34", "北京", "3.5", "5000"],
                              ["002", "女", "29", "上海", "4.0", "6000"],
                              ["004", "女", "45", "上海", "2.5", "8000"],
                              ["005", "男", "41", "北京", "3.0", ""],
                              ["006", "女", "50", "南京", "4.0", "9000"],
                          ])
        out = self.p("reports")
        proc = run_reports(stale, out, "--cleaning-log",
                           os.path.join(cleaning_out, "cleaning_log.jsonl"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(out, "report_index.json"),
                  encoding="utf-8") as handle:
            index = json.load(handle)
        self.assertTrue(any("ended with 4 rows" in warning
                            for warning in index["warnings"]))
        md = open(os.path.join(out, "data_report.md"),
                  encoding="utf-8").read()
        self.assertIn("## 警告", md)
        self.assertIn("5 rows", md)

    def test_cleaning_failure_is_a_visible_warning(self):
        data = analysis_dataset(self.p("analysis.csv"))
        # hand-craft a failed cleaning log (unreadable dataset case)
        failed_log = self.p("cleaning_log.jsonl")
        with open(failed_log, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"record": "failure", "error": "dataset not readable",
                 "generated_at": "2026-11-18T00:00:00+00:00",
                 "status": "failed"},
                ensure_ascii=False) + "\n")
        out = self.p("reports")
        proc = run_reports(data, out, "--cleaning-log", failed_log)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(out, "report_index.json"),
                  encoding="utf-8") as handle:
            index = json.load(handle)
        self.assertTrue(any("ends in failure" in warning
                            for warning in index["warnings"]))
        md = open(os.path.join(out, "data_report.md"),
                  encoding="utf-8").read()
        self.assertIn("dataset not readable", md)

    def test_missing_id_rows_are_listed_not_hidden(self):
        data = write_csv(self.p("analysis.csv"), ["id", "x"], [
            ["1", "a"], ["", "b"], ["", "c"], ["1", "d"]])
        out = self.p("reports")
        proc = run_reports(data, out, "--id", "id")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = read_csv(os.path.join(out, "duplicate_report.csv"))
        missing = row_by(rows, duplicate_kind="id_missing")
        self.assertEqual(missing["n_rows"], "2")
        dup = row_by(rows, duplicate_kind="id", key="1")
        self.assertEqual(dup["n_rows"], "2")

    def test_crosstab_counts_missing_on_both_sides(self):
        data = write_csv(self.p("analysis.csv"), ["id", "gender", "city"], [
            ["1", "男", "北京"], ["2", "女", ""], ["3", "", "南京"],
            ["4", "", ""], ["5", "男", "北京"],
        ])
        out = self.p("reports")
        proc = run_reports(data, out, "--crosstab", "gender,city")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = read_csv(os.path.join(out, "crosstabs.csv"))
        cell = row_by(rows, var_a="gender", value_a="(缺失)",
                      value_b="(缺失)")
        self.assertEqual(cell["n"], "1")
        cell = row_by(rows, var_a="gender", value_a="女", value_b="(缺失)")
        self.assertEqual(cell["n"], "1")
        self.assertEqual(cell["pct_within_a"], "100")

    def test_missing_patterns_cap_has_a_summary_row(self):
        # 55 rows, each with a unique missing pattern over 6 columns
        header = ["id"] + [f"v{i}" for i in range(6)]
        body = []
        for index in range(55):
            row = [str(index)]
            for bit in range(6):
                row.append("" if (index >> bit) & 1 else "x")
            body.append(row)
        data = write_csv(self.p("analysis.csv"), header, body)
        out = self.p("reports")
        self.assertEqual(run_reports(data, out).returncode, 0)
        patterns = read_csv(os.path.join(out, "missing_patterns.csv"))
        self.assertEqual(len(patterns), 51)          # 50 + summary row
        summary = patterns[-1]
        self.assertIn("其余", summary["pattern"])
        total = sum(int(row["n_rows"]) for row in patterns)
        self.assertEqual(total, 55)

    def test_literal_missing_label_merges_with_marker_as_documented(self):
        # documented limitation: a cell literally equal to (缺失) is
        # indistinguishable from the marker in frequency_tables.csv
        data = write_csv(self.p("analysis.csv"), ["id", "note"], [
            ["1", "(缺失)"], ["2", "(缺失)"], ["3", ""]])
        out = self.p("reports")
        self.assertEqual(run_reports(data, out).returncode, 0)
        rows = read_csv(os.path.join(out, "frequency_tables.csv"))
        row = row_by(rows, variable="note", value="(缺失)")
        self.assertEqual(row["n"], "3")


class TestAuditRound2(TempCase):
    """Findings from the second audit round: value-vs-number parity with
    the cleaning engine, honest master report, skip visibility."""

    def test_overflow_is_not_numeric(self):
        data = write_csv(self.p("analysis.csv"), ["id", "x"], [
            ["1", "1e999"], ["2", "5"], ["3", "7"]])
        out = self.p("reports")
        self.assertEqual(run_reports(data, out).returncode, 0)
        rows = read_csv(os.path.join(out, "variable_report.csv"))
        self.assertEqual(row_by(rows, column="x")["kind"], "categorical")
        self.assertEqual(row_by(rows, column="x")["n_non_numeric"], "1")

    def test_digit_separator_is_not_numeric(self):
        data = write_csv(self.p("analysis.csv"), ["id", "n"], [
            ["1", "1_000"], ["2", "2_000"]])
        out = self.p("reports")
        self.assertEqual(run_reports(data, out).returncode, 0)
        rows = read_csv(os.path.join(out, "variable_report.csv"))
        self.assertEqual(row_by(rows, column="n")["kind"], "categorical")
        self.assertEqual(row_by(rows, column="n")["n_non_numeric"], "2")

    def test_failed_cleaning_log_is_not_claimed_absent(self):
        data = analysis_dataset(self.p("analysis.csv"))
        failed_log = self.p("cleaning_log.jsonl")
        with open(failed_log, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"record": "failure", "error": "dataset not readable",
                 "generated_at": "2026-11-18T00:00:00+00:00",
                 "status": "failed"},
                ensure_ascii=False) + "\n")
        out = self.p("reports")
        proc = run_reports(data, out, "--cleaning-log", failed_log)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = read_text(os.path.join(out, "data_report.md"))
        self.assertIn("台账存在但没有 header 记录", md)
        self.assertNotIn("未提供 cleaning_log", md)
        self.assertIn("dataset not readable", md)

    def test_text_and_empty_columns_get_skip_entries(self):
        data = write_csv(self.p("analysis.csv"), ["id", "note", "blank"], [
            ["1", "a", ""], ["2", "b", ""], ["3", "c", ""]])
        out = self.p("reports")
        proc = run_reports(data, out, "--max-cardinality", "2")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # with cap 2 every column is over the cap or empty: no value list
        freq = read_csv(os.path.join(out, "frequency_tables.csv"))
        self.assertEqual(freq, [])
        with open(os.path.join(out, "report_index.json"),
                  encoding="utf-8") as handle:
            index = json.load(handle)
        skipped = {item["item"]: item["reason"]
                   for item in index["skipped"]}
        self.assertIn("frequency:note", skipped)
        self.assertIn("frequency:blank", skipped)
        self.assertIn("no non-missing values", skipped["frequency:blank"])

    def test_negative_max_cardinality_refused(self):
        data = analysis_dataset(self.p("analysis.csv"))
        proc = run_reports(data, self.p("r"), "--max-cardinality", "0")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("at least 1", proc.stderr)

    def test_same_column_crosstab_refused(self):
        data = analysis_dataset(self.p("analysis.csv"))
        proc = run_reports(data, self.p("r"), "--crosstab", "gender,gender")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("two different columns", proc.stderr)

    def test_id_column_crosstab_skipped_visibly(self):
        data = analysis_dataset(self.p("analysis.csv"))
        out = self.p("reports")
        proc = run_reports(data, out, "--id", "id",
                           "--crosstab", "id,gender")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(out, "report_index.json"),
                  encoding="utf-8") as handle:
            index = json.load(handle)
        self.assertTrue(any("id column" in item["reason"]
                            for item in index["skipped"]))

    def test_duplicate_header_refused(self):
        data = self.p("bad.csv")
        with open(data, "w", encoding="utf-8", newline="") as handle:
            handle.write("id,id,x\n1,2,3\n")
        proc = run_reports(data, self.p("r"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("duplicate header name", proc.stderr)

    def test_out_pointing_at_a_file_is_refused(self):
        data = analysis_dataset(self.p("analysis.csv"))
        blocker = self.p("blocker")
        open(blocker, "w").close()
        proc = run_reports(data, blocker)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a directory", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_out_parent_unbuildable_is_refused(self):
        data = analysis_dataset(self.p("analysis.csv"))
        blocker = self.p("blocker")
        open(blocker, "w").close()
        proc = run_reports(data, self.p("blocker", "reports"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot create output directory", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
