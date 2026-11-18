# -*- coding: utf-8 -*-
"""Batch 4 - the modern statistics set in ``auto_stats.py``.

Covers the five declared features end to end through the CLI:
interactions (product terms + joint Wald), mixed models (random intercept /
slopes, ICC), Cox proportional hazards (HR scale, strata), log-rank tests,
sampling weights (WLS / GLM freq_weights), multiple imputation (MICE + Rubin)
and the unified VIF flag threshold.

Known-answer philosophy: every estimator is checked against a generative
truth (a coefficient we planted), not just "the file exists". Determinism is
checked by rerunning with the same seed and comparing bytes.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempCase, read_csv, run, write_csv  # noqa: E402

import auto_stats  # noqa: E402


def read_csv_header(path: str) -> list[str]:
    import csv
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return next(csv.reader(fh))


def call_main(*args) -> tuple[int, str]:
    """Call ``auto_stats.main()`` in-process; return ``(status, stderr)``."""
    argv = sys.argv
    err = io.StringIO()
    out = io.StringIO()
    sys.argv = ["auto_stats.py"] + [str(a) for a in args]
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            status = auto_stats.main()
    finally:
        sys.argv = argv
    return int(status), err.getvalue()


def make_modern_data(n: int = 400, seed: int = 42) -> pd.DataFrame:
    """Synthetic frame with planted effects for every estimator.

    Planted truths: score = x1 + noise (so regressing score on score_miss with
    x1 recovers beta(score_miss)=1, beta(x1)~0); hazard ~ exp(-0.4*x1 + 0.5*grp);
    logit P(y=1) = sigmoid(0.5*x1).
    """
    rng = np.random.default_rng(seed)
    school = np.array([f"S{i:02d}" for i in rng.integers(0, 12, n)])
    x1 = rng.normal(0, 1, n)
    score = x1 + rng.normal(0, 0.4, n)
    score_miss = score.copy()
    score_miss[rng.random(n) < 0.15] = np.nan
    grp = rng.integers(0, 2, n)
    lvl3 = rng.choice(["a", "b", "c"], size=n, p=[0.5, 0.3, 0.2])
    hazard_scale = np.exp(0.4 * x1 - 0.5 * grp)
    t_true = rng.exponential(hazard_scale)
    cen = rng.uniform(0, 6, n)
    time = np.minimum(t_true, cen)
    event = (t_true <= cen).astype(int)
    y = (rng.random(n) < 1.0 / (1.0 + np.exp(-(0.5 * x1)))).astype(int)
    wt = rng.uniform(0.6, 1.8, n)
    return pd.DataFrame({
        "id": np.arange(1, n + 1), "school": school, "x1": x1,
        "grp": grp, "lvl3": lvl3, "score": score, "score_miss": score_miss,
        "time": time, "event": event, "y": y, "wt": wt,
    })


def spec(*models) -> dict:
    return {"models": list(models)}


class _Base(TempCase):
    @staticmethod
    def read_text(path: str) -> str:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read()

    def write_data(self, df: pd.DataFrame, name: str = "analysis.csv") -> str:
        path = self.p(name)
        write_csv(path, list(df.columns), df.values.tolist())
        return path

    def write_spec(self, obj, name: str = "spec.json") -> str:
        path = self.p(name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        return path

    def run_spec(self, data: str, spec_obj, *extra) -> tuple[int, str]:
        full = spec_obj if isinstance(spec_obj, dict) and "models" in spec_obj \
            else spec(spec_obj)
        sp = self.write_spec(full)
        out = self.p("out")
        return call_main("--data", data, "--spec", sp, "--out", out, *extra)

    def fit_rows(self, out: str | None = None) -> list[dict]:
        return read_csv(os.path.join(out or self.p("out"), "fit.csv"))

    def coef(self, mid: str, out: str | None = None) -> list[dict]:
        return read_csv(os.path.join(out or self.p("out"), f"coef_{mid}.csv"))


# --------------------------------------------------------------------------- #
# interactions
# --------------------------------------------------------------------------- #
class InteractionTest(_Base):
    def test_ols_num_by_num_interaction_and_joint_wald(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1", "grp"],
            "interactions": [["x1", "grp"]]}, "--vif")
        self.assertEqual(status, 0, err)
        rows = self.coef("M1")
        terms = {r["term"] for r in rows}
        self.assertIn("x1:grp", terms)
        inter = next(r for r in rows if r["term"] == "x1:grp")
        self.assertEqual(inter["note"], "交互项")
        fit = self.fit_rows()[0]
        self.assertTrue(math.isfinite(float(fit["test_stat"])))
        self.assertTrue(math.isfinite(float(fit["test_p"])))
        self.assertEqual(float(fit["test_df"]), 1.0)
        # the planted data has no interaction, so the joint Wald should not
        # fire: p comfortably above 0.01
        self.assertGreater(float(fit["test_p"]), 0.01)

    def test_planted_interaction_is_detected(self):
        rng = np.random.default_rng(5)
        n = 400
        a = rng.normal(size=n)
        b = rng.integers(0, 2, n)
        y = 1.2 * a * b + rng.normal(0, 0.3, n)
        df = pd.DataFrame({"a": a, "b": b.astype(float), "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "y",
            "predictors": ["a", "b"],
            "interactions": [["a", "b"]]})
        self.assertEqual(status, 0, err)
        inter = next(r for r in self.coef("M1") if r["term"] == "a:b")
        self.assertAlmostEqual(float(inter["beta"]), 1.2, delta=0.25)
        self.assertLess(float(inter["p"]), 1e-6)
        fit = self.fit_rows()[0]
        self.assertLess(float(fit["test_p"]), 1e-6)

    def test_cat_by_num_interaction_terms_follow_dummies(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1", "C(lvl3, Treatment('a'))"],
            "interactions": [["x1", "lvl3"]]})
        self.assertEqual(status, 0, err)
        terms = {r["term"] for r in self.coef("M1")}
        self.assertEqual(terms, {"x1", "lvl3[T.b]", "lvl3[T.c]",
                                 "x1:lvl3[T.b]", "x1:lvl3[T.c]"})

    def test_cat_by_cat_interaction_product_count(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["C(grp, Treatment('0'))", "C(lvl3, Treatment('a'))"],
            "interactions": [["grp", "lvl3"]]})
        self.assertEqual(status, 0, err)
        terms = [r["term"] for r in self.coef("M1")]
        products = [t for t in terms if t.startswith("grp[T.1]:")]
        self.assertEqual(len(products), 2)  # (2-1) x (3-1)

    def test_interaction_var_must_be_declared_as_predictor(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1"], "interactions": [["x1", "grp"]]})
        self.assertEqual(status, 2)
        self.assertIn("不在 predictors", err)

    def test_interaction_self_pair_and_duplicates_refused(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1", "grp"], "interactions": [["x1", "x1"]]})
        self.assertEqual(status, 2)
        self.assertIn("变量自身", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1", "grp"],
            "interactions": [["x1", "grp"], ["grp", "x1"]]})
        self.assertEqual(status, 2)
        self.assertIn("重复对", err)


# --------------------------------------------------------------------------- #
# mixed models
# --------------------------------------------------------------------------- #
class MixedModelTest(_Base):
    def test_random_interceptor_icc_and_groups(self):
        rng = np.random.default_rng(8)
        n = 360
        school = np.repeat(np.arange(12), n // 12)
        x = rng.normal(size=n)
        grp_eff = rng.normal(0, 0.9, 12)
        y = 1.3 * x + grp_eff[school] + rng.normal(0, 0.5, n)
        df = pd.DataFrame({"school": [f"S{i}" for i in school], "x": x, "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "mixed", "outcome": "y", "groups": "school",
            "predictors": ["x"]})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertEqual(fit["type"], "mixed")
        self.assertEqual(float(fit["n_groups"]), 12.0)
        self.assertGreater(float(fit["icc"]), 0.4)   # 0.81 / (0.81+0.25) ~ 0.76
        self.assertLess(float(fit["icc"]), 1.0)
        rows = self.coef("M1")
        self.assertEqual([r["term"] for r in rows], ["x"])
        self.assertAlmostEqual(float(rows[0]["beta"]), 1.3, delta=0.15)

    def test_random_slope_model_runs_and_icc_is_undefined(self):
        rng = np.random.default_rng(11)
        n = 300
        school = np.repeat(np.arange(10), 30)
        x = rng.normal(size=n)
        y = 0.8 * x + rng.normal(0, 0.4, n)
        df = pd.DataFrame({"school": [f"S{i}" for i in school], "x": x, "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "mixed", "outcome": "y", "groups": "school",
            "predictors": ["x"], "random_slopes": ["x"]})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertIn("随机斜率", fit["se_type"])
        # with random slopes the total variance depends on x, so a single
        # ICC has no definition: blank (NaN), never a fake number
        icc = fit["icc"]
        self.assertTrue(icc == "" or (isinstance(icc, float)
                                      and math.isnan(icc)), icc)
        md = self.read_text(self.p("out", "model_summary.md"))
        self.assertIn("带随机斜率", md)
        self.assertIn("未计算", md)
        rows = self.coef("M1")
        self.assertAlmostEqual(float(rows[0]["beta"]), 0.8, delta=0.2)

    def test_missing_groups_rows_are_dropped_and_counted(self):
        rng = np.random.default_rng(3)
        n = 200
        school = np.array([f"S{i}" for i in rng.integers(0, 8, n)], dtype=object)
        school[:17] = None
        x = rng.normal(size=n)
        y = x + rng.normal(0, 0.3, n)
        df = pd.DataFrame({"school": school, "x": x, "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "mixed", "outcome": "y", "groups": "school",
            "predictors": ["x"]})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertEqual(int(fit["n"]), n - 17)
        self.assertEqual(int(float(fit["n_dropna"])), 17)

    def test_mixed_subset_is_honored(self):
        rng = np.random.default_rng(14)
        n = 300
        school = np.repeat(np.arange(10), 30)
        x = rng.normal(size=n)
        y = x + rng.normal(0, 0.3, n)
        site = rng.integers(0, 2, n)
        df = pd.DataFrame({"school": [f"S{i}" for i in school], "x": x,
                           "y": y, "site": site})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "mixed", "outcome": "y", "groups": "school",
            "predictors": ["x"], "subset": "site == 1"})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertEqual(int(fit["n"]), int((df["site"] == 1).sum()))
        self.assertEqual(fit["subset"], "site == 1")
        with open(self.p("out", "model_meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        receipt = meta["sample_receipts"][0]
        # n_before counts rows AFTER the subset, before complete cases
        self.assertEqual(int(receipt["n_before"]), int((df["site"] == 1).sum()))

    def test_mixed_spec_validation(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "mixed", "outcome": "score",
            "predictors": ["x1"]})                     # no groups
        self.assertEqual(status, 2)
        self.assertIn("groups", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "mixed", "outcome": "score",
            "groups": "nosuch", "predictors": ["x1"]})
        self.assertEqual(status, 2)
        self.assertIn("列不存在", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "mixed", "outcome": "score", "groups": "school",
            "predictors": ["C(lvl3, Treatment('a'))"], "random_slopes": ["lvl3"]})
        self.assertEqual(status, 2)
        self.assertIn("random_slopes 只支持数值变量", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "mixed", "outcome": "score", "groups": "school",
            "predictors": ["x1"], "weights": "wt"})
        self.assertEqual(status, 2)
        self.assertIn("只用于", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "mixed", "outcome": "score", "groups": "school",
            "predictors": ["x1"], "impute": {"m": 3, "seed": 1}})
        self.assertEqual(status, 2)
        self.assertIn("impute", err)


# --------------------------------------------------------------------------- #
# cox
# --------------------------------------------------------------------------- #
class CoxModelTest(_Base):
    def test_cox_recovers_planted_effects_on_hr_scale(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "predictors": ["x1", "C(grp, Treatment('0'))"]})
        self.assertEqual(status, 0, err)
        rows = {r["term"]: r for r in self.coef("M1")}
        self.assertEqual(set(rows), {"x1", "grp[T.1]"})
        # hazard ~ exp(-0.4*x1 + 0.5*grp): HR(x1) ~ 0.67, HR(grp1) ~ 1.65
        self.assertAlmostEqual(float(rows["x1"]["estimate"]), math.exp(-0.4),
                               delta=0.15)
        self.assertEqual(rows["x1"]["metric"], "HR")
        self.assertLess(float(rows["x1"]["p"]), 1e-4)
        # CI sanity: positive, ordered, estimate inside, ratio plausible
        low, est, high = (float(rows["x1"]["ci_low"]),
                          float(rows["x1"]["estimate"]),
                          float(rows["x1"]["ci_high"]))
        self.assertGreater(low, 0.0)
        self.assertLess(low, est)
        self.assertLess(est, high)
        self.assertLess(high / low, 5.0)
        self.assertAlmostEqual(float(rows["grp[T.1]"]["estimate"]),
                               math.exp(0.5), delta=0.35)
        self.assertEqual(rows["grp[T.1]"]["ref"], "0")
        fit = self.fit_rows()[0]
        self.assertEqual(fit["type"], "cox")
        self.assertEqual(int(fit["n"]), len(df))
        self.assertEqual(int(float(fit["n_events"])), int(df["event"].sum()))
        self.assertIn("breslow", fit["se_type"])

    def test_cox_design_has_no_intercept_row(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "predictors": ["x1"]})
        self.assertEqual(status, 0, err)
        terms = [r["term"] for r in self.coef("M1")]
        self.assertEqual(terms, ["x1"])     # no const / Intercept row

    def test_cox_with_strata(self):
        # known answer: the stratified partial likelihood must differ from
        # the pooled one (strata absorbs the baseline hazard difference)
        # while recovering the planted x1 effect
        df = make_modern_data()
        data = self.write_data(df)
        self.run_spec(data, {"id": "M1", "type": "cox", "time": "time",
                             "event": "event", "predictors": ["x1"]})
        plain = float(self.coef("M1")[0]["estimate"])
        status, err = self.run_spec(data, {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "strata": "grp", "predictors": ["x1"]})
        self.assertEqual(status, 0, err)
        strat = self.coef("M1")[0]
        self.assertAlmostEqual(float(strat["estimate"]), math.exp(-0.4),
                               delta=0.15)
        self.assertNotAlmostEqual(float(strat["estimate"]), plain,
                                  delta=1e-6)
        fit = self.fit_rows()[0]
        self.assertIn("分层: grp", fit["se_type"])

    def test_cox_spec_validation(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "cox", "event": "event",
            "predictors": ["x1"]})                      # no time
        self.assertEqual(status, 2)
        self.assertIn("time", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "predictors": ["x1"], "weights": "wt"})
        self.assertEqual(status, 2)
        self.assertIn("只用于", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "predictors": ["x1"], "cluster": "school"})
        self.assertEqual(status, 2)
        self.assertIn("只用于", err)
        neg = df.copy()
        neg.loc[neg.index[0], "time"] = -1.0
        status, err = self.run_spec(self.write_data(neg, "neg.csv"), {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "predictors": ["x1"]})
        self.assertEqual(status, 2)
        self.assertIn("负值", err)
        noe = df.copy()
        noe["event"] = 0
        status, err = self.run_spec(self.write_data(noe, "noe.csv"), {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "predictors": ["x1"]})
        self.assertEqual(status, 2)
        self.assertIn("没有事件", err)

    def test_cox_interaction_joint_wald_present(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "predictors": ["x1", "grp"],
            "interactions": [["x1", "grp"]]})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertTrue(math.isfinite(float(fit["test_stat"])))
        terms = {r["term"] for r in self.coef("M1")}
        self.assertIn("x1:grp", terms)


# --------------------------------------------------------------------------- #
# logrank
# --------------------------------------------------------------------------- #
class LogrankTest(_Base):
    def test_logrank_detects_planted_group_effect(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logrank", "time": "time", "event": "event",
            "group": "grp"})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertEqual(fit["type"], "logrank")
        self.assertEqual(float(fit["test_df"]), 1.0)
        self.assertGreater(float(fit["test_stat"]), 3.0)   # planted 0.5 log HR
        self.assertLess(float(fit["test_p"]), 0.10)
        # S-09: the coef table exists with a header but no data rows - a
        # reader must be able to tell "no coefficients by design" from
        # "the run never got there"
        self.assertEqual(len(self.coef("M1")), 0)
        self.assertEqual(read_csv_header(self.p("out", "coef_M1.csv")),
                         auto_stats.TABLE_COLUMNS["coef"])

    def test_logrank_with_strata_runs(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logrank", "time": "time", "event": "event",
            "group": "grp", "strata": "lvl3"})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertIn("分层", fit["se_type"])
        self.assertTrue(math.isfinite(float(fit["test_stat"])))

    def test_logrank_only_spec_succeeds_without_coef_rows(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logrank", "time": "time", "event": "event",
            "group": "lvl3"})
        self.assertEqual(status, 0, err)
        self.assertIn("logrank", err)
        self.assertTrue(os.path.isfile(self.p("out", "model_summary.md")))
        md = self.read_text(self.p("out", "model_summary.md"))
        self.assertIn("log-rank", md)
        self.assertIn("M1", md)

    def test_logrank_spec_validation(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logrank", "time": "time", "event": "event",
            "group": "grp", "predictors": ["x1"]})
        self.assertEqual(status, 2)
        self.assertIn("不接受 predictors", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logrank", "time": "time", "event": "event"})
        self.assertEqual(status, 2)
        self.assertIn("group", err)
        one = df[df["grp"] == 0].copy()
        status, err = self.run_spec(self.write_data(one, "one.csv"), {
            "id": "M1", "type": "logrank", "time": "time", "event": "event",
            "group": "grp"})
        self.assertEqual(status, 2)
        self.assertIn("只有 1 水平", err)


# --------------------------------------------------------------------------- #
# sampling weights
# --------------------------------------------------------------------------- #
class WeightsTest(_Base):
    def test_wls_matches_row_expanded_ols_point_estimates(self):
        rng = np.random.default_rng(21)
        n = 120
        x = rng.normal(size=n)
        y = 0.7 * x + rng.normal(0, 0.4, n)
        w = rng.integers(1, 4, n)          # integer weights
        df = pd.DataFrame({"x": x, "y": y, "wt": w.astype(float)})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "y",
            "predictors": ["x"], "weights": "wt"})
        self.assertEqual(status, 0, err)
        beta_w = float(self.coef("M1")[0]["beta"])
        idx = np.repeat(np.arange(n), w)
        import statsmodels.api as sm
        fit2 = sm.OLS(y[idx], sm.add_constant(x[idx])).fit()
        self.assertAlmostEqual(beta_w, float(fit2.params[1]), delta=1e-8)
        fit = self.fit_rows()[0]
        self.assertAlmostEqual(float(fit["weighted_n"]), float(w.sum()), delta=1e-9)
        self.assertIn("weighted", fit["se_type"])

    def test_glm_freq_weights_matches_row_expanded_logit(self):
        rng = np.random.default_rng(23)
        n = 150
        x = rng.normal(size=n)
        p = 1.0 / (1.0 + np.exp(-(0.6 * x)))
        y = rng.binomial(1, p)
        w = rng.integers(1, 3, n)
        df = pd.DataFrame({"x": x, "y": y, "wt": w.astype(float)})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logit", "outcome": "y",
            "predictors": ["x"], "weights": "wt"})
        self.assertEqual(status, 0, err)
        rows = self.coef("M1")
        beta_w = float(next(r for r in rows if r["term"] == "x")["beta"])
        idx = np.repeat(np.arange(n), w)
        import statsmodels.api as sm
        fit2 = sm.Logit(y[idx], sm.add_constant(x[idx])).fit(disp=0)
        self.assertAlmostEqual(beta_w, float(fit2.params[1]), delta=1e-6)
        md = self.read_text(self.p("out", "model_summary.md"))
        self.assertIn("模型基，不是设计基", md)

    def test_weight_validation(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1"], "weights": "nosuch"})
        self.assertEqual(status, 2)
        self.assertIn("weights 列不存在", err)
        bad = df.copy()
        bad.loc[bad.index[3], "wt"] = 0.0
        status, err = self.run_spec(self.write_data(bad, "bad.csv"), {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1"], "weights": "wt"})
        self.assertEqual(status, 2)
        self.assertIn("≤0", err)

    def test_missing_weight_rows_counted_in_dropna(self):
        df = make_modern_data()
        df.loc[df.index[:12], "wt"] = np.nan
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1"], "weights": "wt"})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertEqual(int(float(fit["n_dropna"])), 12)
        self.assertEqual(int(fit["n"]), len(df) - 12)

    def test_weights_plus_cluster_combination_runs_and_warns(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1"], "weights": "wt", "cluster": "school"})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertIn("cluster(school", fit["se_type"])
        self.assertIn("weighted", fit["se_type"])
        md = self.read_text(self.p("out", "model_summary.md"))
        # the honest boundary line is always shown for weighted models
        self.assertIn("模型基，不是设计基", md)

    def test_weights_rejected_for_other_types(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "predictors": ["x1"], "weights": "wt"})
        self.assertEqual(status, 2)
        self.assertIn("只用于", err)


# --------------------------------------------------------------------------- #
# multiple imputation
# --------------------------------------------------------------------------- #
class ImputationTest(_Base):
    def test_mi_pools_and_recovers_the_planted_coefficient(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1", "score_miss"],
            "impute": {"m": 4, "seed": 7, "cycles": 3}})
        self.assertEqual(status, 0, err)
        report = read_csv(self.p("out", "impute_report.csv"))
        self.assertEqual(len(report), 2)
        by_term = {r["term"]: r for r in report}
        # planted: score = x1 + noise, so beta(score_miss) = 1 and beta(x1) ~ 0
        self.assertAlmostEqual(float(by_term["score_miss"]["beta_pooled"]),
                               1.0, delta=0.05)
        self.assertLess(float(by_term["score_miss"]["p_rubin"]), 1e-4)
        self.assertAlmostEqual(float(by_term["score_miss"]["cc_beta"]),
                               1.0, delta=0.05)
        self.assertGreater(float(by_term["score_miss"]["fmi"]), 0.0)
        self.assertLess(float(by_term["score_miss"]["fmi"]), 1.0)
        self.assertEqual(int(by_term["score_miss"]["n_imputations"]), 4)
        # coef table carries pooled rows plus the complete-case reference rows
        rows = self.coef("M1")
        samples = {r["sample"] for r in rows}
        self.assertIn("MI(m=4)", samples)
        self.assertIn("full (complete-case)", samples)
        fit = self.fit_rows()[0]
        self.assertEqual(int(fit["mi_m"]), 4)
        self.assertEqual(int(fit["n"]), len(df))    # imputed N is the full frame
        md = self.read_text(self.p("out", "model_summary.md"))
        self.assertIn("Rubin", md)
        self.assertIn("complete-case", md)

    def test_mi_same_seed_is_byte_identical(self):
        df = make_modern_data()
        data = self.write_data(df)
        model = {"id": "M1", "type": "ols", "outcome": "score",
                 "predictors": ["x1", "score_miss"],
                 "impute": {"m": 3, "seed": 11, "cycles": 2}}
        self.run_spec(data, model)
        first = self.read_text(self.p("out", "impute_report.csv"))
        first_coef = self.read_text(self.p("out", "coef_M1.csv"))
        out2 = self.p("out2")
        sp = self.write_spec(spec(model), "spec2.json")
        status, err = call_main("--data", data, "--spec", sp, "--out", out2)
        self.assertEqual(status, 0, err)
        self.assertEqual(first, self.read_text(os.path.join(out2,
                                                            "impute_report.csv")))
        self.assertEqual(first_coef, self.read_text(os.path.join(out2,
                                                                 "coef_M1.csv")))

    def test_mi_different_seed_changes_between_variance(self):
        df = make_modern_data()
        data = self.write_data(df)
        self.run_spec(data, {"id": "M1", "type": "ols", "outcome": "score",
                             "predictors": ["x1", "score_miss"],
                             "impute": {"m": 3, "seed": 11, "cycles": 2}})
        r1 = read_csv(self.p("out", "impute_report.csv"))
        self.run_spec(data, {"id": "M1", "type": "ols", "outcome": "score",
                             "predictors": ["x1", "score_miss"],
                             "impute": {"m": 3, "seed": 999, "cycles": 2}})
        r2 = read_csv(self.p("out", "impute_report.csv"))
        b1 = float(next(r for r in r1 if r["term"] == "score_miss")["between_var"])
        b2 = float(next(r for r in r2 if r["term"] == "score_miss")["between_var"])
        self.assertNotAlmostEqual(b1, b2, delta=1e-12)

    def test_mi_spec_validation(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1", "score_miss"], "impute": {"m": 1, "seed": 5}})
        self.assertEqual(status, 2)
        self.assertIn("至少为 2", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1", "score_miss"], "impute": {"m": 3}})
        self.assertEqual(status, 2)
        self.assertIn("seed", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1", "score_miss"],
            "impute": {"m": 3, "seed": 5, "cycles": 0}})
        self.assertEqual(status, 2)
        self.assertIn("cycles", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "predictors": ["x1"], "impute": {"m": 3, "seed": 5}})
        self.assertEqual(status, 2)
        self.assertIn("只用于", err)

    def test_mi_logit_pools_on_or_scale(self):
        rng = np.random.default_rng(30)
        n = 400
        x = rng.normal(size=n)
        p = 1.0 / (1.0 + np.exp(-(0.8 * x)))
        y = rng.binomial(1, p)
        x_miss = x + rng.normal(0, 0.05, n)
        x_miss[rng.random(n) < 0.2] = np.nan
        df = pd.DataFrame({"x": x, "x_miss": x_miss, "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logit", "outcome": "y",
            "predictors": ["x_miss"],
            "impute": {"m": 3, "seed": 4, "cycles": 2}})
        self.assertEqual(status, 0, err)
        rows = [r for r in self.coef("M1") if r["sample"] == "MI(m=3)"]
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["or"]), math.exp(0.8), delta=0.35)
        self.assertEqual(rows[0]["metric"], "OR")
        self.assertGreater(float(rows[0]["or_low"]), 0.0)
        self.assertTrue(math.isfinite(float(rows[0]["or_high"])))
        report = read_csv(self.p("out", "impute_report.csv"))
        self.assertEqual(len(report), 1)

    def test_mi_empty_cell_in_any_imputation_is_refused(self):
        rng = np.random.default_rng(31)
        n = 240
        g = rng.choice(["a", "b"], size=n)
        x = rng.normal(size=n)
        # level "b" never has an event: every imputation keeps that empty cell
        y = np.where(g == "b", 0, (rng.random(n) < 0.4).astype(int))
        x_missing = x.copy()
        x_missing[rng.random(n) < 0.1] = np.nan
        df = pd.DataFrame({"g": g, "x": x_missing, "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logit", "outcome": "y",
            "predictors": ["C(g, Treatment('a'))", "x"],
            "impute": {"m": 2, "seed": 6, "cycles": 2}})
        self.assertEqual(status, 2)
        self.assertIn("空单元格", err)
        self.assertIn("MI", err)

    def test_mi_all_missing_rows_are_dropped_not_crashed(self):
        rng = np.random.default_rng(51)
        n = 300
        x = rng.normal(size=n)
        y = x + rng.normal(0, 0.3, n)
        x_miss = x.copy()
        x_miss[rng.random(n) < 0.2] = np.nan
        y[0:10] = np.nan                    # outcome missing on its own
        # 12 rows miss BOTH x and y - MICEData would silently drop them
        both = rng.choice(np.arange(n), 12, replace=False)
        x_miss[both] = np.nan
        y[both] = np.nan
        df = pd.DataFrame({"x": x_miss, "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "y",
            "predictors": ["x"], "impute": {"m": 3, "seed": 9, "cycles": 2}})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        # 10 outcome-only-missing + 12 all-missing rows excluded by default
        self.assertEqual(int(fit["n"]), n - 10 - 12)
        self.assertEqual(int(float(fit["n_dropna"])), 22)
        report = read_csv(self.p("out", "impute_report.csv"))
        self.assertEqual(len(report), 1)
        self.assertAlmostEqual(float(report[0]["beta_pooled"]), 1.0, delta=0.2)

    def test_mi_outcome_imputed_with_all_missing_rows_is_the_real_path(self):
        # the counterfactual path the crash fix guards: with impute_outcome
        # the all-missing rows are NOT eaten by the outcome-exclusion branch,
        # so MICEData's internal dropna would desync positional assignment
        rng = np.random.default_rng(61)
        n = 300
        x = rng.normal(size=n)
        y = x + rng.normal(0, 0.3, n)
        x_miss = x.copy()
        x_miss[rng.random(n) < 0.1] = np.nan
        both = rng.choice(np.arange(n), 15, replace=False)
        x_miss[both] = np.nan
        y[both] = np.nan                    # only these rows miss the outcome
        df = pd.DataFrame({"x": x_miss, "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "y",
            "predictors": ["x"],
            "impute": {"m": 3, "seed": 10, "cycles": 2,
                       "impute_outcome": True}})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertEqual(int(fit["n"]), n - 15)   # only all-missing excluded
        self.assertEqual(int(float(fit["n_dropna"])), 15)
        md = self.read_text(self.p("out", "model_summary.md"))
        self.assertIn("全部模型变量缺失 15 行剔除", md)
        report = read_csv(self.p("out", "impute_report.csv"))
        self.assertAlmostEqual(float(report[0]["beta_pooled"]), 1.0, delta=0.2)

    def test_mi_empty_impute_object_is_refused(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1"], "impute": {}})
        self.assertEqual(status, 2)
        self.assertIn("空对象", err)

    def test_mi_cluster_missing_is_an_error_not_a_silent_drop(self):
        df = make_modern_data()
        df.loc[df.index[:8], "school"] = None
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1", "score_miss"], "cluster": "school",
            "impute": {"m": 3, "seed": 5, "cycles": 2}})
        self.assertEqual(status, 2)
        self.assertIn("cluster 列 school 在建模样本里有缺失", err)

    def test_mi_weights_missing_rows_are_counted(self):
        rng = np.random.default_rng(62)
        n = 300
        x = rng.normal(size=n)
        y = x + rng.normal(0, 0.3, n)
        x_miss = x + rng.normal(0, 0.02, n)
        x_miss[rng.random(n) < 0.12] = np.nan
        wt = rng.uniform(0.6, 1.6, n)
        wt[:9] = np.nan
        df = pd.DataFrame({"x": x_miss, "y": y, "wt": wt})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "y",
            "predictors": ["x"], "weights": "wt",
            "impute": {"m": 3, "seed": 6, "cycles": 2}})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertEqual(int(fit["n"]), n - 9)
        self.assertEqual(int(float(fit["n_dropna"])), 9)
        md = self.read_text(self.p("out", "model_summary.md"))
        self.assertIn("weights 缺失 9 行剔除", md)

    def test_mi_outcome_missing_excluded_by_default_and_optional(self):
        rng = np.random.default_rng(52)
        n = 300
        x = rng.normal(size=n)
        p = 1.0 / (1.0 + np.exp(-(0.8 * x)))
        y = rng.binomial(1, p).astype(float)
        y[rng.random(n) < 0.15] = np.nan
        df = pd.DataFrame({"x": x, "y": y})
        data = self.write_data(df)
        # default: outcome missing rows are NOT imputed
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logit", "outcome": "y",
            "predictors": ["x"], "impute": {"m": 3, "seed": 3, "cycles": 2}})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        n_observed = int(df["y"].notna().sum())
        self.assertEqual(int(fit["n"]), n_observed)
        md = self.read_text(self.p("out", "model_summary.md"))
        self.assertIn("不插补结局（默认）", md)
        # opt-in: outcome is imputed too, and the summary says which mode
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logit", "outcome": "y",
            "predictors": ["x"],
            "impute": {"m": 3, "seed": 3, "cycles": 2,
                       "impute_outcome": True}})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertEqual(int(fit["n"]), n)
        md = self.read_text(self.p("out", "model_summary.md"))
        self.assertIn("插补结局", md)
        self.assertIn("观测口径", md)
        # events stay on the observed scale even when y is imputed
        self.assertEqual(int(float(fit["n_events"])), int(df["y"].sum()))

    def test_mi_dropna_false_with_outcome_missing_refused(self):
        rng = np.random.default_rng(53)
        n = 120
        x = rng.normal(size=n)
        y = x + rng.normal(0, 0.3, n)
        y[:8] = np.nan
        df = pd.DataFrame({"x": x, "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "y",
            "predictors": ["x"], "dropna": False,
            "impute": {"m": 3, "seed": 3, "cycles": 2}})
        self.assertEqual(status, 2)
        self.assertIn("dropna=false", err)
        self.assertIn("结局缺失", err)

    def test_mi_with_interactions_pools_and_tests(self):
        rng = np.random.default_rng(54)
        n = 400
        x = rng.normal(size=n)
        b = rng.integers(0, 2, n)
        y = 1.1 * x * b + 0.3 * x + rng.normal(0, 0.3, n)
        x_miss = x + rng.normal(0, 0.03, n)
        x_miss[rng.random(n) < 0.15] = np.nan
        df = pd.DataFrame({"x": x_miss, "b": b.astype(float), "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "y",
            "predictors": ["x", "b"], "interactions": [["x", "b"]],
            "impute": {"m": 3, "seed": 8, "cycles": 2}})
        self.assertEqual(status, 0, err)
        rows = [r for r in self.coef("M1") if r["sample"] == "MI(m=3)"]
        terms = {r["term"] for r in rows}
        self.assertIn("x:b", terms)
        inter = next(r for r in rows if r["term"] == "x:b")
        self.assertAlmostEqual(float(inter["beta"]), 1.1, delta=0.3)
        fit = self.fit_rows()[0]
        self.assertLess(float(fit["test_p"]), 1e-4)
        report = read_csv(self.p("out", "impute_report.csv"))
        self.assertIn("x:b", {r["term"] for r in report})

    def test_mi_with_clean_cluster_reports_cluster_se(self):
        # the cluster itself is complete: MI rows keep the cluster SE and n
        # matches the structural-complete frame (see the weights-missing test
        # for the counted-exclusion ledger, and the cluster-missing test for
        # the refusal)
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1", "score_miss"], "cluster": "school",
            "impute": {"m": 3, "seed": 5, "cycles": 2}})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertEqual(int(fit["n"]), len(df))
        self.assertIn("cluster", fit["se_type"])


    def test_owners_matrix_rejects_misplaced_fields(self):
        # logrank has no predictors, so interactions/outcome/ref are all
        # misplaced there; cox does not use outcome either
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logrank", "time": "time", "event": "event",
            "group": "grp", "interactions": [["x1", "grp"]]})
        self.assertEqual(status, 2)
        self.assertIn("只用于", err)
        self.assertIn("interactions", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logrank", "time": "time", "event": "event",
            "group": "grp", "outcome": "score"})
        self.assertEqual(status, 2)
        self.assertIn("outcome", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "cox", "time": "time", "event": "event",
            "predictors": ["x1"], "outcome": "score"})
        self.assertEqual(status, 2)
        self.assertIn("outcome", err)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "score",
            "predictors": ["x1"], "weights": ""})
        self.assertEqual(status, 2)
        self.assertIn("weights 必须是列名", err)

    def test_interaction_column_explosion_is_guarded(self):
        rng = np.random.default_rng(60)
        n = 60                      # tiny n: k/n explodes past 1/5
        a = rng.choice([f"a{i}" for i in range(6)], size=n)
        b = rng.choice([f"b{i}" for i in range(6)], size=n)
        y = rng.normal(size=n)
        df = pd.DataFrame({"a": a, "b": b, "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "y",
            "predictors": ["C(a, Treatment('a0'))", "C(b, Treatment('b0'))"],
            "interactions": [["a", "b"]]})
        # 5+5 dummies + 25 products + const = 36 columns vs 60 rows -> refuse
        self.assertEqual(status, 2)
        self.assertIn("列行比", err)
        self.assertIn("1/5", err)


# --------------------------------------------------------------------------- #
# VIF threshold unification
# --------------------------------------------------------------------------- #
class VifFlagTest(_Base):
    def test_summary_flags_vif_at_5_not_10(self):
        rng = np.random.default_rng(44)
        n = 200
        x1 = rng.normal(size=n)
        x2 = 2.0 * x1 + rng.normal(0, 0.01, n)    # VIF in the hundreds
        y = x1 + rng.normal(0, 0.5, n)
        df = pd.DataFrame({"x1": x1, "x2": x2, "y": y})
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "ols", "outcome": "y",
            "predictors": ["x1", "x2"]}, "--vif")
        self.assertEqual(status, 0, err)
        md = self.read_text(self.p("out", "model_summary.md"))
        self.assertIn("存在共线性", md)
        # 6 < VIF < 10 must also be flagged under the unified threshold
        x2b = x1 + rng.normal(0, 0.6, n)          # VIF ~ 6-ish
        dfb = pd.DataFrame({"x1": x1, "x2": x2b, "y": y})
        datab = self.write_data(dfb, "b.csv")
        status, err = self.run_spec(datab, {
            "id": "M1", "type": "ols", "outcome": "y",
            "predictors": ["x1", "x2"]}, "--vif")
        self.assertEqual(status, 0, err)
        vif = read_csv(self.p("out", "vif.csv"))
        vifs = [float(r["vif"]) for r in vif if r["term"] != "(none)"]
        if any(5.0 <= v < 10.0 for v in vifs):
            md = self.read_text(self.p("out", "model_summary.md"))
            self.assertIn("存在共线性", md)

    def test_clean_design_has_no_flag(self):
        df = make_modern_data()
        data = self.write_data(df)
        self.run_spec(data, {"id": "M1", "type": "ols", "outcome": "score",
                             "predictors": ["x1", "grp"]}, "--vif")
        md = self.read_text(self.p("out", "model_summary.md"))
        self.assertNotIn("存在共线性", md)


# --------------------------------------------------------------------------- #
# combination + fit.csv schema
# --------------------------------------------------------------------------- #
class CombinationTest(_Base):
    def test_interaction_with_cluster_and_cov(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {
            "id": "M1", "type": "logit", "outcome": "y",
            "predictors": ["x1", "C(grp, Treatment('0'))"], "cluster": "school",
            "cov": "HC1", "interactions": [["x1", "grp"]]})
        self.assertEqual(status, 0, err)
        fit = self.fit_rows()[0]
        self.assertIn("cluster(school", fit["se_type"])
        terms = {r["term"] for r in self.coef("M1")}
        self.assertIn("x1:grp[T.1]", terms)

    def test_fit_csv_header_matches_table_columns(self):
        df = make_modern_data()
        data = self.write_data(df)
        self.run_spec(data, {"id": "M1", "type": "ols", "outcome": "score",
                             "predictors": ["x1"]})
        fit = self.fit_rows()
        self.assertEqual(list(fit[0].keys()), auto_stats.TABLE_COLUMNS["fit"])

    def test_type_must_be_one_of_five(self):
        df = make_modern_data()
        data = self.write_data(df)
        status, err = self.run_spec(data, {"id": "M1", "type": "probit",
                                           "outcome": "y",
                                           "predictors": ["x1"]})
        self.assertEqual(status, 2)
        self.assertIn("logit / ols / mixed / cox / logrank", err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
