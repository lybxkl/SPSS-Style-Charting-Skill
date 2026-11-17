# -*- coding: utf-8 -*-
"""clean_data.py: cleaning is executed from a recipe, recorded, replayable.

The engine must not clean anything the recipe did not declare, must abort
on every refusal path (exit 2) instead of guessing, and must leave an audit
trail whose fingerprint chain is verifiable by replay.
"""
import hashlib
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempCase, run, write_csv, read_csv


def base_dataset(path: str) -> str:
    return write_csv(path, ["id", "name", "age", "city", "score"], [
        ["001", "张三", "34", "北京", "3.5"],
        ["002", "李四", "29", " 上海 ", "4.0"],
        ["003", "王五", "200", "南京", "NaN"],
        ["003", "王五", "200", "南京", "NaN"],
        ["004", "赵六", "不详", "上海", "2.5"],
        ["005", "钱七", "41", "", "missing-xy"],
    ])


def full_recipe(path: str) -> str:
    payload = {
        "recipe_version": 1,
        "id_columns": ["id"],
        "max_drop_fraction": 0.5,
        "na_values": [""],
        "steps": [
            {"op": "drop_exact_duplicates",
             "columns": ["id", "name", "age", "city", "score"]},
            {"op": "map_values", "column": "city",
             "map": {" 上海 ": "上海", "北京": "北京", "上海": "上海",
                     "南京": "南京"},
             "unmapped": "error"},
            {"op": "coerce_type", "column": "age", "to": "int",
             "on_fail": "missing"},
            {"op": "flag_outliers", "column": "age",
             "rule": {"min": 16, "max": 100}, "action": "set_missing"},
            {"op": "coerce_type", "column": "score", "to": "float",
             "on_fail": "missing"},
            {"op": "drop_rows_if_missing", "columns": ["score"],
             "mode": "any", "reason": "outcome missing"},
        ],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return path


def recipe_with(path: str, steps: list, fraction: float = 0.5,
                id_columns: list | None = None,
                na_values: list | None = None) -> str:
    payload = {"recipe_version": 1,
               "id_columns": id_columns if id_columns is not None else [],
               "max_drop_fraction": fraction,
               "steps": steps}
    if na_values is not None:
        payload["na_values"] = na_values
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return path


def read_log(out_dir: str) -> list[dict]:
    path = os.path.join(out_dir, "cleaning_log.jsonl")
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class TestFullPipeline(TempCase):
    def test_recipe_runs_and_artifacts_are_correct(self):
        data = base_dataset(self.p("data.csv"))
        recipe = full_recipe(self.p("recipe.json"))
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual([row["id"] for row in clean], ["001", "002", "004"])
        self.assertEqual(clean[0]["age"], "34")
        self.assertEqual(clean[1]["city"], "上海")
        self.assertEqual(clean[2]["age"], "")

        flow = read_csv(os.path.join(out, "flow.csv"))
        self.assertEqual([row["stage"] for row in flow],
                         ["清洗前", "去重后", "缺失剔除后", "清洗后"])
        self.assertEqual([int(row["n"]) for row in flow], [6, 5, 3, 3])

        log = read_log(out)
        header = log[0]
        self.assertEqual(header["record"], "header")
        self.assertEqual(header["dataset"]["n_rows"], 6)
        self.assertEqual(header["id_columns"], ["id"])
        steps = [r for r in log if r["record"] == "step"]
        self.assertEqual(len(steps), 6)
        for prev, nxt in zip(steps, steps[1:]):
            self.assertEqual(prev["sha_out"], nxt["sha_in"])
        self.assertEqual(steps[0]["n_dropped"], 1)
        self.assertEqual(steps[0]["dropped_ids_sample"], [["003"]])
        self.assertEqual(steps[1]["n_cells_changed"], 1)
        self.assertEqual(steps[2]["n_set_missing"], 1)   # "不详" -> missing
        self.assertEqual(steps[3]["n_outliers"], 1)       # age 200
        # "NaN" and "missing-xy" are values, not numbers: both -> missing
        self.assertEqual(steps[4]["n_set_missing"], 2)
        self.assertEqual(steps[5]["n_dropped"], 2)

        summary = log[-1]
        self.assertEqual(summary["record"], "summary")
        self.assertEqual(summary["n_final"], 3)
        self.assertEqual(summary["n_dropped_total"], 3)
        with open(os.path.join(out, "clean_dataset.csv"), "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(summary["final_sha256"], digest)

        md = open(os.path.join(out, "cleaning_log.md"), encoding="utf-8").read()
        self.assertIn("清洗台账", md)
        self.assertIn("drop_exact_duplicates", md)
        self.assertIn("复核方式", md)

    def test_replay_is_deterministic(self):
        data = base_dataset(self.p("data.csv"))
        recipe = full_recipe(self.p("recipe.json"))
        first, second = self.p("out1"), self.p("out2")
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", recipe, "--out", first).returncode, 0)
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", recipe, "--out", second).returncode, 0)
        with open(os.path.join(first, "clean_dataset.csv"), "rb") as a, \
                open(os.path.join(second, "clean_dataset.csv"), "rb") as b:
            self.assertEqual(a.read(), b.read())
        chain1 = [(r.get("sha_in"), r.get("sha_out"))
                  for r in read_log(first) if r["record"] == "step"]
        chain2 = [(r.get("sha_in"), r.get("sha_out"))
                  for r in read_log(second) if r["record"] == "step"]
        self.assertEqual(chain1, chain2)

    def test_empty_steps_is_explicit_identity(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual(len(clean), 6)
        self.assertEqual(clean[1]["city"], " 上海 ")   # untouched, verbatim
        flow = read_csv(os.path.join(out, "flow.csv"))
        self.assertEqual([row["stage"] for row in flow], ["清洗前", "清洗后"])
        summary = read_log(out)[-1]
        self.assertEqual(summary["steps_run"], 0)

    def test_template_emission(self):
        proc = run("clean_data.py", "--emit-template", self.p("t.json"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(self.p("t.json"), encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["recipe_version"], 1)
        self.assertIn("_ops", payload)
        self.assertEqual(payload["steps"], [])


class TestRefusals(TempCase):
    def test_unmapped_value_aborts_instead_of_guessing(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "map_values", "column": "city",
             "map": {"北京": "京"}, "unmapped": "error"}])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not in the map", proc.stderr)
        log = read_log(out)
        self.assertEqual(log[-1]["record"], "failure")
        self.assertFalse(os.path.exists(os.path.join(out,
                                                     "clean_dataset.csv")))

    def test_unmapped_keep_counts_visibly(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "map_values", "column": "city",
             "map": {"北京": "京"}, "unmapped": "keep"}])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        steps = [r for r in read_log(out) if r["record"] == "step"]
        # unmapped non-missing values: " 上海 ", 南京×2, 上海
        self.assertEqual(steps[0]["n_unmapped_kept"], 4)

    def test_max_drop_fraction_guard(self):
        data = write_csv(self.p("data.csv"), ["id", "score"], [
            ["1", "1"], ["2", ""], ["3", ""], ["4", ""], ["5", ""], ["6", ""]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "drop_rows_if_missing", "columns": ["score"],
             "mode": "any", "reason": "outcome missing"}], fraction=0.2)
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("exceeds max_drop_fraction", proc.stderr)
        self.assertIn("83.3%", proc.stderr)

    def test_unknown_op_rejected(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"),
                             [{"op": "impute_mean", "column": "age"}])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown op", proc.stderr)

    def test_missing_required_key_rejected(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"),
                             [{"op": "drop_rows_if_missing",
                               "columns": ["score"]}])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing keys", proc.stderr)

    def test_unknown_column_rejected_with_evolution(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "rename_column", "from": "age", "to": "年龄"},
            {"op": "coerce_type", "column": "age", "to": "int",
             "on_fail": "missing"}])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not in dataset", proc.stderr)
        self.assertIn("年龄", proc.stderr)   # the renamed column is offered

    def test_missing_guard_value_rejected(self):
        data = base_dataset(self.p("data.csv"))
        recipe = self.p("recipe.json")
        with open(recipe, "w", encoding="utf-8") as handle:
            json.dump({"recipe_version": 1, "id_columns": [],
                       "steps": []}, handle)
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("max_drop_fraction", proc.stderr)

    def test_bad_json_recipe(self):
        data = base_dataset(self.p("data.csv"))
        recipe = self.p("recipe.json")
        with open(recipe, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not valid JSON", proc.stderr)

    def test_missing_files(self):
        self.assertEqual(run("clean_data.py", "--dataset", self.p("no.csv"),
                             "--recipe", self.p("no.json"),
                             "--out", self.p("out")).returncode, 2)
        data = base_dataset(self.p("data.csv"))
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", self.p("no.json"),
                             "--out", self.p("out")).returncode, 2)

    def test_duplicate_ids_refused_without_a_dedupe_step(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [],
                             id_columns=["id"])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("after cleaning", proc.stderr)
        self.assertIn("no longer unique", proc.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.p("out"),
                                                     "clean_dataset.csv")))

    def test_duplicate_ids_are_cleanable_by_a_dedupe_step(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "drop_exact_duplicates",
             "columns": ["id", "name", "age", "city", "score"]}],
            id_columns=["id"])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_coerce_error_mode_lists_offenders(self):
        data = write_csv(self.p("data.csv"), ["id", "age"], [
            ["1", "34"], ["2", "3.5"], ["3", "old"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "coerce_type", "column": "age", "to": "int",
             "on_fail": "error"}])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unparseable", proc.stderr)
        self.assertIn("3.5", proc.stderr)

    def test_flag_outliers_requires_numeric_first(self):
        data = write_csv(self.p("data.csv"), ["id", "age"], [
            ["1", "34"], ["2", "very old"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "flag_outliers", "column": "age",
             "rule": {"min": 16, "max": 100}, "action": "set_missing"}])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("run a coerce_type step first", proc.stderr)

    def test_nan_and_inf_are_values_not_numbers(self):
        data = write_csv(self.p("data.csv"), ["id", "score"], [
            ["1", "NaN"], ["2", "inf"], ["3", "2.5"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "coerce_type", "column": "score", "to": "float",
             "on_fail": "missing"}])
        out = self.p("out")
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", recipe, "--out", out).returncode, 0)
        steps = [r for r in read_log(out) if r["record"] == "step"]
        self.assertEqual(steps[0]["n_set_missing"], 2)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual([row["score"] for row in clean],
                         ["", "", "2.5"])


class TestSemantics(TempCase):
    def test_na_values_vocabulary(self):
        data = write_csv(self.p("data.csv"), ["id", "answer"], [
            ["1", "拒绝回答"], ["2", "同意"], ["3", ""]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "drop_rows_if_missing", "columns": ["answer"],
             "mode": "any", "reason": "refused/blank"}],
            fraction=1.0, na_values=["", "拒绝回答"])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual([row["id"] for row in clean], ["2"])

    def test_rename_and_keep_columns(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "rename_column", "from": "name", "to": "姓名"},
            {"op": "keep_columns", "columns": ["id", "姓名", "age"]}])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual(list(clean[0].keys()), ["id", "姓名", "age"])
        self.assertEqual(clean[0]["姓名"], "张三")
        steps = [r for r in read_log(out) if r["record"] == "step"]
        self.assertEqual(steps[1]["columns_dropped"], ["city", "score"])

    def test_trim_option_on_text(self):
        data = write_csv(self.p("data.csv"), ["id", "city"], [
            ["1", " 上海 "], ["2", "北京"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "coerce_type", "column": "city", "to": "text",
             "on_fail": "missing", "trim": True}])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual(clean[0]["city"], "上海")
        steps = [r for r in read_log(out) if r["record"] == "step"]
        self.assertEqual(steps[0]["n_cells_changed"], 1)

    def test_canonical_float_form(self):
        data = write_csv(self.p("data.csv"), ["id", "score"], [
            ["1", "3.50"], ["2", ".5"], ["3", "1e2"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "coerce_type", "column": "score", "to": "float",
             "on_fail": "missing"}])
        out = self.p("out")
        self.assertEqual(run("clean_data.py", "--dataset", data,
                              "--recipe", recipe, "--out", out).returncode, 0)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual([row["score"] for row in clean],
                         ["3.5", "0.5", "100.0"])

    def test_int_accepts_zero_fraction_only(self):
        data = write_csv(self.p("data.csv"), ["id", "n"], [
            ["1", "3"], ["2", "3.0"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "coerce_type", "column": "n", "to": "int",
             "on_fail": "missing"}])
        out = self.p("out")
        self.assertEqual(run("clean_data.py", "--dataset", data,
                              "--recipe", recipe, "--out", out).returncode, 0)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual([row["n"] for row in clean], ["3", "3"])

    def test_repeated_drop_stages_are_numbered(self):
        data = write_csv(self.p("data.csv"), ["id", "a", "b"], [
            ["1", "", ""], ["2", "x", ""], ["3", "x", "x"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "drop_rows_if_missing", "columns": ["a"], "mode": "any",
             "reason": "a missing"},
            {"op": "drop_rows_if_missing", "columns": ["b"], "mode": "any",
             "reason": "b missing"}], fraction=1.0)
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        flow = read_csv(os.path.join(out, "flow.csv"))
        self.assertEqual([row["stage"] for row in flow],
                         ["清洗前", "缺失剔除后", "缺失剔除后 2", "清洗后"])


class TestAuditFixes(TempCase):
    """Findings from the independent audit round: crash paths, guards,
    canonical forms, flow merging."""

    def test_empty_dataset_fails_cleanly_without_traceback(self):
        write_csv(self.p("data.csv"), ["id", "x"], [])
        recipe = recipe_with(self.p("recipe.json"), [])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", self.p("data.csv"),
                   "--recipe", recipe, "--out", out)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no columns or no rows", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        log = read_log(out)
        self.assertEqual(log[-1]["record"], "failure")
        md = open(os.path.join(out, "cleaning_log.md"),
                  encoding="utf-8").read()
        self.assertIn("失败中止", md)
        self.assertIn("无 header 记录", md)
        self.assertFalse(os.path.exists(os.path.join(out,
                                                     "clean_dataset.csv")))

    def test_malformed_csv_fails_cleanly_without_traceback(self):
        with open(self.p("data.csv"), "w", encoding="utf-8") as handle:
            handle.write("id,x\n1,2,3,4,5\n")
        recipe = recipe_with(self.p("recipe.json"), [])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", self.p("data.csv"),
                   "--recipe", recipe, "--out", out)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("field count differs from the header", proc.stderr)
        self.assertIn("2", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(read_log(out)[-1]["record"], "failure")
        md = open(os.path.join(out, "cleaning_log.md"),
                  encoding="utf-8").read()
        self.assertIn("失败中止", md)

    def test_control_characters_are_refused(self):
        data = write_csv(self.p("data.csv"), ["id", "note"], [
            ["1", "ok"], ["2", "bad\x1fsep"]])
        recipe = recipe_with(self.p("recipe.json"), [])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("fingerprint separators", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_digit_separator_is_a_value_not_a_number(self):
        data = write_csv(self.p("data.csv"), ["id", "n"], [
            ["1", "1_000"], ["2", "5"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "coerce_type", "column": "n", "to": "int",
             "on_fail": "error"}])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unparseable", proc.stderr)
        self.assertIn("1_000", proc.stderr)

    def test_canonical_float_keeps_full_precision(self):
        data = write_csv(self.p("data.csv"), ["id", "x"], [
            ["1", "1.0000000000000002"], ["2", "0.30000000000000004"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "coerce_type", "column": "x", "to": "float",
             "on_fail": "missing"}])
        out = self.p("out")
        self.assertEqual(run("clean_data.py", "--dataset", data,
                              "--recipe", recipe, "--out", out).returncode, 0)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual(clean[0]["x"], "1.0000000000000002")
        self.assertEqual(clean[1]["x"], "0.30000000000000004")

    def test_keep_columns_twice_is_rejected(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "keep_columns", "columns": ["id", "id", "age"]}])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("lists a column twice", proc.stderr)

    def test_max_drop_fraction_boundary_value_passes(self):
        data = write_csv(self.p("data.csv"), ["id", "score"], [
            ["1", "1"], ["2", ""], ["3", ""], ["4", "2"],
            ["5", "3"], ["6", ""]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "drop_rows_if_missing", "columns": ["score"],
             "mode": "any", "reason": "outcome missing"}], fraction=0.5)
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        clean = read_csv(os.path.join(self.p("out"), "clean_dataset.csv"))
        self.assertEqual(len(clean), 3)

    def test_empty_steps_na_values_still_applies(self):
        data = write_csv(self.p("data.csv"), ["id", "answer"], [
            ["1", "无"], ["2", "同意"]])
        recipe = recipe_with(self.p("recipe.json"), [],
                             na_values=["", "无"])
        out = self.p("out")
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", recipe, "--out", out).returncode, 0)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual(clean[0]["answer"], "")
        self.assertEqual(clean[1]["answer"], "同意")

    def test_emit_template_creates_nested_directory(self):
        target = self.p("deep", "nested", "recipe.json")
        proc = run("clean_data.py", "--emit-template", target)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.isfile(target))

    def test_flow_out_merges_into_sample_flow_and_is_idempotent(self):
        data = base_dataset(self.p("data.csv"))
        recipe = full_recipe(self.p("recipe.json"))
        sample_flow = write_csv(self.p("sample_flow.csv"),
                                ["stage", "n", "note"], [
                                    ["文件总数", "20", "files walked"],
                                    ["编码完成", "6", "records"],
                                ])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"), "--flow-out", sample_flow)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        merged = read_csv(sample_flow)
        self.assertEqual([row["stage"] for row in merged],
                         ["文件总数", "编码完成", "清洗前", "去重后",
                          "缺失剔除后", "清洗后"])
        self.assertNotIn("kind", merged[0])
        # re-running replaces the cleaning rows instead of stacking them
        run("clean_data.py", "--dataset", data, "--recipe", recipe,
            "--out", self.p("out2"), "--flow-out", sample_flow)
        again = read_csv(sample_flow)
        self.assertEqual(merged, again)

    def test_flow_out_respects_kind_column_and_fills_stage(self):
        data = base_dataset(self.p("data.csv"))
        recipe = full_recipe(self.p("recipe.json"))
        sample_flow = write_csv(self.p("sample_flow.csv"),
                                ["stage", "n", "note", "kind"], [
                                    ["文件总数", "20", "files walked",
                                     "stage"],
                                    ["编码完成", "6", "records", "stage"],
                                ])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"), "--flow-out", sample_flow)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        merged = read_csv(sample_flow)
        self.assertEqual([row["kind"] for row in merged],
                         ["stage", "stage", "stage", "stage", "stage",
                          "stage"])
        self.assertEqual([int(row["n"]) for row in merged[2:]],
                         [6, 5, 3, 3])
        # re-running with the kind layout is also idempotent
        run("clean_data.py", "--dataset", data, "--recipe", recipe,
            "--out", self.p("out2"), "--flow-out", sample_flow)
        self.assertEqual(read_csv(sample_flow), merged)

    def test_flow_out_creates_a_fresh_file_when_missing(self):
        data = base_dataset(self.p("data.csv"))
        recipe = full_recipe(self.p("recipe.json"))
        fresh = self.p("flows", "sample_flow.csv")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"), "--flow-out", fresh)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        merged = read_csv(fresh)
        self.assertEqual([row["stage"] for row in merged],
                         ["清洗前", "去重后", "缺失剔除后", "清洗后"])
        # a fresh file is three-column: the kind column belongs to the
        # coding step that owns sample_flow.csv, not to the merger
        with open(fresh, encoding="utf-8-sig", newline="") as handle:
            self.assertEqual(handle.readline().strip(), "stage,n,note")

    def test_flow_out_replaces_rows_from_a_previous_recipe(self):
        data = base_dataset(self.p("data.csv"))
        full = full_recipe(self.p("full.json"))
        smaller = recipe_with(self.p("small.json"), [
            {"op": "drop_exact_duplicates", "columns": ["id"]}])
        sample_flow = self.p("sample_flow.csv")
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", full, "--out", self.p("out1"),
                             "--flow-out", sample_flow).returncode, 0)
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", smaller, "--out", self.p("out2"),
                             "--flow-out", sample_flow).returncode, 0)
        stages = [row["stage"] for row in read_csv(sample_flow)]
        self.assertEqual(stages, ["清洗前", "去重后", "清洗后"])


class TestAuditRound2(TempCase):
    """Findings from the second audit round: ledger snapshots, id
    validation, overflow values, header guards, flow anchors."""

    def test_header_columns_survive_rename_and_keep(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "rename_column", "from": "name", "to": "姓名"},
            {"op": "keep_columns", "columns": ["id", "姓名", "age"]}])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        header = read_log(out)[0]
        # the header must state the INPUT columns, not the cleaned ones
        self.assertEqual(header["dataset"]["columns"],
                         ["id", "name", "age", "city", "score"])
        self.assertEqual(header["dataset"]["n_columns"], 5)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual(list(clean[0].keys()), ["id", "姓名", "age"])

    def test_unknown_id_columns_refused(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [],
                             id_columns=["nope"])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("id_columns not in dataset", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_overflow_to_infinity_is_a_value_not_a_number(self):
        data = write_csv(self.p("data.csv"), ["id", "x"], [
            ["1", "1e999"], ["2", "5"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "coerce_type", "column": "x", "to": "float",
             "on_fail": "missing"}])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual(clean[0]["x"], "")
        recipe = recipe_with(self.p("recipe2.json"), [
            {"op": "coerce_type", "column": "x", "to": "float",
             "on_fail": "error"}])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out2"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unparseable", proc.stderr)

    def test_map_values_requires_string_values(self):
        data = base_dataset(self.p("data.csv"))
        recipe = self.p("recipe.json")
        with open(recipe, "w", encoding="utf-8") as handle:
            json.dump({"recipe_version": 1, "id_columns": [],
                       "max_drop_fraction": 0.5, "steps": [
                           {"op": "map_values", "column": "city",
                            "map": {"北京": 1}, "unmapped": "keep"}]},
                      handle)
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must be a string", proc.stderr)
        with open(recipe, "w", encoding="utf-8") as handle:
            json.dump({"recipe_version": 1, "id_columns": [],
                       "max_drop_fraction": 0.5, "steps": [
                           {"op": "map_values", "column": "city",
                            "map": {"北京": None}, "unmapped": "keep"}]},
                      handle)
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", recipe,
                             "--out", self.p("out2")).returncode, 2)
        with open(recipe, "w", encoding="utf-8") as handle:
            json.dump({"recipe_version": 1, "id_columns": [],
                       "max_drop_fraction": 0.5, "steps": [
                           {"op": "map_values", "column": "city",
                            "map": {"北京": ["京"]}, "unmapped": "keep"}]},
                      handle)
        self.assertEqual(run("clean_data.py", "--dataset", data,
                             "--recipe", recipe,
                             "--out", self.p("out3")).returncode, 2)

    def test_flow_always_ends_with_the_clean_stage(self):
        data = write_csv(self.p("data.csv"), ["id", "x"], [
            ["1", "a"], ["2", "b"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "drop_exact_duplicates", "columns": ["id", "x"]}])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        flow = read_csv(os.path.join(out, "flow.csv"))
        self.assertEqual([row["stage"] for row in flow],
                         ["清洗前", "去重后", "清洗后"])
        self.assertEqual([int(row["n"]) for row in flow], [2, 2, 2])

    def test_control_characters_in_header_refused(self):
        data = self.p("data.csv")
        with open(data, "w", encoding="utf-8", newline="") as handle:
            handle.write("id\x1d,x\n1,ok\n")
        recipe = recipe_with(self.p("recipe.json"), [])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("column name", proc.stderr)
        self.assertIn("fingerprint separators", proc.stderr)

    def test_duplicate_header_refused(self):
        data = self.p("data.csv")
        with open(data, "w", encoding="utf-8", newline="") as handle:
            handle.write("id,id,x\n1,2,3\n")
        recipe = recipe_with(self.p("recipe.json"), [])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("duplicate header name", proc.stderr)

    def test_empty_header_name_refused(self):
        data = self.p("data.csv")
        with open(data, "w", encoding="utf-8", newline="") as handle:
            handle.write("id,,x\n1,2,3\n")
        recipe = recipe_with(self.p("recipe.json"), [])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("empty header name", proc.stderr)

    def test_out_pointing_at_a_file_is_refused(self):
        data = base_dataset(self.p("data.csv"))
        blocker = self.p("blocker")
        open(blocker, "w").close()
        recipe = recipe_with(self.p("recipe.json"), [])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", blocker)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a directory", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_out_parent_unbuildable_is_refused(self):
        data = base_dataset(self.p("data.csv"))
        blocker = self.p("blocker")
        open(blocker, "w").close()
        recipe = recipe_with(self.p("recipe.json"), [])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("blocker", "clean"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot create output directory", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_merge_flow_reads_gb18030_and_normalizes_output(self):
        data = base_dataset(self.p("data.csv"))
        recipe = full_recipe(self.p("recipe.json"))
        sample_flow = self.p("sample_flow.csv")
        with open(sample_flow, "w", encoding="gb18030", newline="") as handle:
            handle.write("stage,n,note\n文件总数,20,files walked\n")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"), "--flow-out", sample_flow)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        merged = read_csv(sample_flow)          # read_csv uses utf-8-sig
        self.assertEqual(merged[0]["stage"], "文件总数")
        self.assertIn("清洗后", [row["stage"] for row in merged])

    def test_unclosed_quote_is_refused_by_the_reader(self):
        data = self.p("data.csv")
        with open(data, "w", encoding="utf-8", newline="") as handle:
            handle.write('id,x\n"1,2\n')
        recipe = recipe_with(self.p("recipe.json"), [])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not readable", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_rename_collision_with_existing_column_refused(self):
        data = base_dataset(self.p("data.csv"))
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "rename_column", "from": "age", "to": "id"}])
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("collides with an existing column", proc.stderr)

    def test_flag_outliers_report_only_keeps_values(self):
        data = write_csv(self.p("data.csv"), ["id", "age"], [
            ["1", "34"], ["2", "200"], ["3", "29"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "coerce_type", "column": "age", "to": "int",
             "on_fail": "error"},
            {"op": "flag_outliers", "column": "age",
             "rule": {"max": 100}, "action": "report_only"}])
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual(clean[1]["age"], "200")
        steps = [r for r in read_log(out) if r["record"] == "step"]
        self.assertEqual(steps[1]["n_outliers"], 1)
        self.assertEqual(steps[1]["action"], "report_only")

    def test_drop_rows_mode_all_requires_every_column_missing(self):
        data = write_csv(self.p("data.csv"), ["id", "a", "b"], [
            ["1", "", ""], ["2", "x", ""], ["3", "", "y"]])
        recipe = recipe_with(self.p("recipe.json"), [
            {"op": "drop_rows_if_missing", "columns": ["a", "b"],
             "mode": "all", "reason": "both missing"}], fraction=1.0)
        out = self.p("out")
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        clean = read_csv(os.path.join(out, "clean_dataset.csv"))
        self.assertEqual([row["id"] for row in clean], ["2", "3"])

    def test_shape_sentinel_reports_more_offenders(self):
        path = self.p("data.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write("id,x\n")
            for index in range(12):
                handle.write(f"{index},v,extra\n")
        recipe = recipe_with(self.p("recipe.json"), [])
        proc = run("clean_data.py", "--dataset", path, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("field count differs from the header", proc.stderr)
        self.assertIn("…", proc.stderr)

    def test_emit_template_bad_path_fails_cleanly(self):
        blocker = self.p("blocker")
        open(blocker, "w").close()
        target = os.path.join(blocker, "recipe.json")
        proc = run("clean_data.py", "--emit-template", target)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("cannot write the template", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_dead_map_keys_are_refused(self):
        data = base_dataset(self.p("data.csv"))
        recipe = self.p("recipe.json")
        with open(recipe, "w", encoding="utf-8") as handle:
            json.dump({"recipe_version": 1, "id_columns": [],
                       "max_drop_fraction": 0.5, "steps": [
                           {"op": "map_values", "column": "city",
                            "map": {"": "未知"}, "unmapped": "keep"}]},
                      handle)
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("never matches", proc.stderr)
        # a na_values entry is just as dead as the empty string
        with open(recipe, "w", encoding="utf-8") as handle:
            json.dump({"recipe_version": 1, "id_columns": [],
                       "max_drop_fraction": 0.5, "na_values": ["", "未记录"],
                       "steps": [
                           {"op": "map_values", "column": "city",
                            "map": {"未记录": "NA"}, "unmapped": "keep"}]},
                      handle)
        proc = run("clean_data.py", "--dataset", data, "--recipe", recipe,
                   "--out", self.p("out2"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("never matches", proc.stderr)


if __name__ == "__main__":
    unittest.main()
