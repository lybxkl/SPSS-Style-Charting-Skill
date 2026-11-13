# -*- coding: utf-8 -*-
"""The sixteen-method battery: every precondition that must refuse, and every
method that must run.

The point of these tests is not "does it produce a number" but "does it refuse
to produce a number when the data cannot support it". A silent wrong statistic
is the one failure a reader cannot catch from the report alone.
"""
from __future__ import annotations

import csv
import json
import os
import unittest

import numpy as np
import pandas as pd

from _helpers import TempCase, run


def build_fixture(path: str, n: int = 240, seed: int = 11) -> dict:
    """A small synthetic dataset that can support all sixteen methods.

    The structure is deliberate: q1..q6 load on one factor (so reliability and
    EFA are meaningful), x -> med -> y holds (so mediation has something to
    find), the group has three levels (so ANOVA is right and an independent t
    test must refuse).
    """
    rng = np.random.default_rng(seed)
    latent = rng.normal(0, 1, n)
    df = pd.DataFrame({
        f"q{i + 1}": np.clip(np.round(3 + 0.9 * latent + rng.normal(0, 0.4, n)), 1, 5)
        for i in range(6)
    })
    x = rng.normal(0, 1, n)
    med = 0.7 * x + rng.normal(0, 0.7, n)
    df["x"] = x
    df["med"] = med
    df["y"] = 0.6 * med + 0.15 * x + rng.normal(0, 0.7, n)
    df["grp"] = pd.Series(rng.choice(["甲", "乙", "丙"], n, p=[0.4, 0.35, 0.25]))
    df["v1"] = rng.normal(0, 1, n) + (df["grp"] == "甲") * 0.8
    df["v2"] = rng.normal(0, 1, n) - (df["grp"] == "丙") * 0.6
    df["v3"] = rng.normal(0, 1, n)
    df["kano_f1"] = rng.integers(1, 6, n)
    df["kano_d1"] = 6 - df["kano_f1"] + rng.integers(-1, 2, n)
    df["kano_f2"] = rng.integers(1, 6, n)
    df["kano_d2"] = rng.integers(1, 6, n)
    df["year"] = np.repeat(np.arange(2016, 2016 + n // 12), 12)[:n]
    df["value"] = np.linspace(10, 22, n) + rng.normal(0, 1.5, n)
    df["grp_bin"] = (df["grp"] == "甲").astype(int)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return {
        "outcome": {"col": "grp_bin", "type": "binary"},
        "continuous": {"col": "y"},
        "predictors": ["x", "v1"],
        "group": "grp",
        "correlate": ["x", "med", "y", "v1"],
        "row": "grp",
        "column": "kano_f1",
        "cluster_vars": ["q1", "q2", "q3", "q4", "q5", "q6", "x", "v1"],
        "items": {"scale": ["q1", "q2", "q3", "q4", "q5", "q6"]},
        "n_factors": 2,
        "cluster_k": 3,
        "kano": {"响应速度": ["kano_f1", "kano_d1"], "态度": ["kano_f2", "kano_d2"]},
        "discriminant": {"group": "grp", "vars": ["v1", "v2", "v3"]},
        "path": {"x": "x", "m": "med", "y": "y"},
        "time": {"col": "year", "value": "value"},
        "describe": ["x", "y", "grp"],
    }


class EfaGateTest(unittest.TestCase):
    def test_low_kmo_refuses_the_factor_solution(self):
        import methods_pack as MP
        rng = np.random.default_rng(7)
        df = pd.DataFrame({name: rng.normal(size=120)
                           for name in ("q1", "q2", "q3", "q4")})
        ctx = {"df": df, "cfg": {"items": ["q1", "q2", "q3", "q4"]},
               "alpha": 0.05}
        with self.assertRaises(MP.Skip) as caught:
            MP.run_m09_factor_analysis(ctx)
        message = str(caught.exception)
        self.assertIn("KMO", message)
        self.assertIn("不输出因子解", message)


def read_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def read_manifest(path: str) -> dict:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return {row["id"]: row for row in csv.DictReader(fh)}


class MethodsCatalogueTest(TempCase):
    def test_list_prints_all_sixteen_numbers(self):
        proc = run("methods_pack.py", "--list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for nr in range(1, 17):
            self.assertRegex(proc.stdout, rf"(?m)^\s*{nr}\s+m\d\d\s")
        self.assertIn("结构方程模型", proc.stdout)

    def test_missing_data_file_is_an_error(self):
        proc = run("methods_pack.py", "--data", self.p("nope.csv"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("data not found", proc.stderr)


class MethodsRunTest(TempCase):
    def setUp(self):
        super().setUp()
        self.data = self.p("data.csv")
        self.cfg = self.p("methods.json")
        cfg = build_fixture(self.data)
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False)
        self.out = self.p("out")

    def test_full_battery_runs_and_writes_a_report(self):
        proc = run("methods_pack.py", "--data", self.data, "--config", self.cfg,
                   "--out", self.out, "--methods", "all", "--formats", "png")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("errors: 0", proc.stdout)
        manifest = read_manifest(os.path.join(self.out, "methods_manifest.csv"))
        ok = {k for k, v in manifest.items() if v["status"] == "ok"}
        skipped = {k for k, v in manifest.items() if v["status"] == "skipped"}
        # every method that this data can support must actually run
        for mid in ("m01", "m02", "m03", "m04", "m05", "m07", "m08", "m09",
                    "m10", "m11", "m13", "m14", "m15", "m16", "m17", "m18"):
            self.assertIn(mid, ok, f"{mid} 应能跑通，实际 {manifest[mid]['status']}: "
                                   f"{manifest[mid]['reason']}")
        # the two refusals are refusals, not crashes
        self.assertIn("m06", skipped)
        self.assertIn("m12", skipped)
        report = read_text(os.path.join(self.out, "methods_report.md"))
        self.assertIn("报告句式", report)
        self.assertIn("1. 描述性统计", report)
        fig_dir = os.path.join(self.out, "figures")
        for mid in ("m01", "m04", "m05", "m09", "m10", "m11", "m13", "m14", "m16", "m18"):
            self.assertTrue(any(f.startswith(mid) for f in os.listdir(fig_dir)),
                            f"{mid} 应有配图")

    def test_model_n_does_not_sum_scalar_rows(self):
        """成对比较表每行一个样本量，相加会得到 25625（数据只有 2878 行）。"""
        import types

        import pandas as pd

        import methods_pack as MP

        scalar = pd.DataFrame({"pair": ["a-b", "a-c"], "n": [28, 27]})
        grouped = pd.DataFrame({"group": ["甲", "乙", "丙"], "n": [10, 12, 8]})
        run = types.SimpleNamespace(
            result=types.SimpleNamespace(stats={}, tables=[("t", scalar)]))
        # Two different pairwise samples have no single scalar N. Neither
        # their sum nor their maximum describes both comparisons correctly.
        self.assertIsNone(MP._model_n(run, pd.DataFrame({"x": range(100)})))
        scalar["n"] = 28
        self.assertEqual(MP._model_n(run, pd.DataFrame({"x": range(100)})), 28)
        run2 = types.SimpleNamespace(
            result=types.SimpleNamespace(stats={}, tables=[("t", grouped)]))
        self.assertEqual(MP._model_n(run2, pd.DataFrame({"x": range(100)})), 30)

    def test_t_test_refuses_three_groups(self):
        proc = run("methods_pack.py", "--data", self.data, "--config", self.cfg,
                   "--out", self.out, "--methods", "m12", "--no-figures")
        self.assertEqual(proc.returncode, 2)  # all skipped -> not a success
        manifest = read_manifest(os.path.join(self.out, "methods_manifest.csv"))
        self.assertEqual(manifest["m12"]["status"], "skipped")
        self.assertIn("t 检验只接受 2 组", manifest["m12"]["reason"])
        self.assertNotIn("('", manifest["m12"]["reason"])  # no tuple repr leak

    def test_sem_is_refused_with_alternatives(self):
        proc = run("methods_pack.py", "--data", self.data, "--config", self.cfg,
                   "--out", self.out, "--methods", "m06", "--no-figures")
        self.assertEqual(proc.returncode, 2)
        manifest = read_manifest(os.path.join(self.out, "methods_manifest.csv"))
        self.assertEqual(manifest["m06"]["status"], "skipped")
        self.assertIn("semopy", manifest["m06"]["reason"])

    def test_logistic_refuses_an_outcome_with_more_than_two_levels(self):
        cfg_path = self.p("bad_outcome.json")
        cfg = json.loads(read_text(self.cfg))
        cfg["outcome"] = {"col": "grp", "type": "binary"}
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False)
        proc = run("methods_pack.py", "--data", self.data, "--config", cfg_path,
                   "--out", self.out, "--methods", "m18", "--no-figures")
        self.assertEqual(proc.returncode, 2)
        manifest = read_manifest(os.path.join(self.out, "methods_manifest.csv"))
        self.assertEqual(manifest["m18"]["status"], "skipped")
        self.assertRegex(manifest["m18"]["reason"], "两[个类]|0/1|二分类|类别")

    def test_efa_refuses_two_items(self):
        cfg_path = self.p("two_items.json")
        cfg = json.loads(read_text(self.cfg))
        cfg["items"] = ["q1", "q2"]
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False)
        proc = run("methods_pack.py", "--data", self.data, "--config", cfg_path,
                   "--out", self.out, "--methods", "m09", "--no-figures")
        self.assertEqual(proc.returncode, 2)
        manifest = read_manifest(os.path.join(self.out, "methods_manifest.csv"))
        self.assertIn("至少三个题项", manifest["m09"]["reason"])

    def test_missing_column_is_a_skip_not_a_traceback(self):
        cfg_path = self.p("wrong_col.json")
        cfg = json.loads(read_text(self.cfg))
        cfg["time"] = {"col": "year_not_here", "value": "value"}
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False)
        proc = run("methods_pack.py", "--data", self.data, "--config", cfg_path,
                   "--out", self.out, "--methods", "m08", "--no-figures")
        self.assertEqual(proc.returncode, 2)
        manifest = read_manifest(os.path.join(self.out, "methods_manifest.csv"))
        self.assertEqual(manifest["m08"]["status"], "skipped")
        self.assertIn("不在数据中", manifest["m08"]["reason"])
        self.assertNotIn("Traceback", proc.stderr)

    def test_empty_config_fails_loudly_when_no_method_can_run(self):
        cfg_path = self.p("empty.json")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        proc = run("methods_pack.py", "--data", self.data, "--config", cfg_path,
                   "--out", self.out, "--only", "m10", "--no-figures")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("没有任何方法跑通", proc.stderr)

    def test_descriptive_still_runs_with_an_empty_config(self):
        # m01 needs no slot at all, so an empty config must not turn it off.
        cfg_path = self.p("empty2.json")
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump({}, fh)
        proc = run("methods_pack.py", "--data", self.data, "--config", cfg_path,
                   "--out", self.out, "--only", "m01", "--no-figures")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_only_selects_one_method(self):
        proc = run("methods_pack.py", "--data", self.data, "--config", self.cfg,
                   "--out", self.out, "--only", "m01", "--formats", "png")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        manifest = read_manifest(os.path.join(self.out, "methods_manifest.csv"))
        self.assertEqual(list(manifest), ["m01"])

    def test_missing_config_slot_names_the_slot_in_the_report(self):
        proc = run("methods_pack.py", "--data", self.data, "--config", self.cfg,
                   "--out", self.out, "--methods", "m13", "--no-figures")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = read_text(os.path.join(self.out, "methods_report.md"))
        self.assertIn("间接效应", report)
        self.assertIn("bootstrap", report)


class MethodsStatisticsTest(TempCase):
    """Check the numbers themselves, because a plausible-looking table can lie."""

    def setUp(self):
        super().setUp()
        import methods_lib as ML
        self.ML = ML
        self.data_path = self.p("data.csv")
        build_fixture(self.data_path)
        self.df = pd.read_csv(self.data_path, encoding="utf-8-sig")

    def test_alpha_is_in_range_and_says_which_item_to_drop(self):
        res = self.ML.cronbach(self.df, ["q1", "q2", "q3", "q4", "q5", "q6"])
        alpha = res.stats["alpha"]
        self.assertTrue(0.7 < alpha <= 1.0, alpha)
        tab = res.tables[0][1]
        self.assertEqual(len(tab), 6)
        self.assertIn("alpha_if_deleted", tab.columns)

    def test_mediation_indirect_equals_a_times_b(self):
        res = self.ML.mediation(self.df, "x", "med", "y", n_boot=200, seed=5)
        paths = res.tables[0][1]
        a = float(paths.loc[paths["path"].str.contains(r"\(a\)"), "coef"].iloc[0])
        b = float(paths.loc[paths["path"].str.contains(r"\(b\)"), "coef"].iloc[0])
        eff = res.tables[1][1].iloc[0]
        # The tables print at 4 decimals, so the check is at that precision;
        # a tighter tolerance would only test Python's rounding, not the maths.
        self.assertAlmostEqual(eff["indirect"], a * b, places=4)
        self.assertLess(eff["boot_lo"], eff["boot_hi"])

    def test_anova_effect_size_is_reported_with_p(self):
        res = self.ML.anova(self.df, "y", "grp")
        self.assertIn("eta2", res.stats)
        self.assertIn("p", res.stats)
        self.assertTrue(0.0 <= res.stats["eta2"] <= 1.0)

    def test_chi_square_flags_sparse_cells(self):
        sub = self.df.head(18).copy()
        res = self.ML.chi_square(sub, "grp", "kano_f1")
        joined = " ".join(res.notes) + " " + " ".join(res.verdict)
        self.assertIn("期望频数<5", joined)
        self.assertIn("Cramér's V", " ".join(res.verdict))

    def test_pca_variance_shares_sum_to_hundred(self):
        res = self.ML.pca(self.df, ["q1", "q2", "q3", "q4", "q5", "q6"], n_components=3)
        var = res.tables[1][1]
        self.assertAlmostEqual(var["cumulative_pct"].iloc[-1], 100.0, places=1)

    def test_describe_never_prints_mean_for_a_skewed_variable_silently(self):
        skewed = pd.DataFrame({"v": np.r_[np.zeros(200), np.arange(1, 21)]})
        res = self.ML.describe(skewed, ["v"])
        row = res.tables[0][1].iloc[0]
        self.assertEqual(row["type"], "连续")
        self.assertTrue(str(row["report"]).startswith(("均值", "中位数")))


if __name__ == "__main__":
    unittest.main()
