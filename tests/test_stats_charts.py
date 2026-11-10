# -*- coding: utf-8 -*-
"""Offline tests for the statistics/figure base: auto_stats.py + pubfig.py.

Everything here is generated locally (synthetic 200-row frame, no network, no
user corpus).  Figures use ASCII labels on purpose: the test box has no CJK
font installed, and a missing glyph would emit a ``UserWarning`` that would
mask the layout warnings these tests are checking for.

Two tests drive the CLI through ``_helpers.run`` (so argparse, the exit code and
the on-disk layout are covered end to end); the remaining command-line cases
call ``auto_stats.main()`` in-process, because every subprocess pays a ~9 s
statsmodels/pandas import and the whole suite must stay under two minutes.

Run with::

    python -m unittest discover -s tests -p "test_stats_charts*.py" -v
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import re
import sys
import unittest
import warnings

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import NullFormatter, NullLocator

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempCase, read_csv, run, write_csv  # noqa: E402

import auto_stats  # noqa: E402
import pubfig  # noqa: E402

REF_CHARGE = "森林资源"
LEVELS = [REF_CHARGE, "土地资源", "其他"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
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


def make_model_data(n: int = 200, seed: int = 7) -> pd.DataFrame:
    """200 rows, 3 predictors (2 numeric + 1 categorical) plus a province."""
    rng = np.random.default_rng(seed)
    gongyi = rng.integers(0, 2, n)
    year_c = rng.integers(-4, 5, n)
    charge = rng.choice(LEVELS, size=n, p=[0.45, 0.35, 0.20])
    province = np.array([f"省{i}" for i in rng.integers(1, 9, n)])
    eta = -0.6 + 0.9 * gongyi + 0.18 * year_c + np.where(charge == "其他", 0.8, 0.0)
    prob = 1.0 / (1.0 + np.exp(-eta))
    y = rng.binomial(1, prob)
    return pd.DataFrame({
        "case_id": np.arange(1, n + 1),
        "restore_any": y,
        "gongyi": gongyi,
        "year_c": year_c,
        "charge_f": charge,
        "province": province,
    })


def logit_spec(**overrides) -> dict:
    model = {
        "id": "M1",
        "type": "logit",
        "outcome": "restore_any",
        "predictors": ["gongyi", "year_c",
                       f"C(charge_f, Treatment('{REF_CHARGE}'))"],
        "ref": {},
        "cluster": "province",
        "cov": "HC1",
        "dropna": True,
    }
    model.update(overrides)
    return {"models": [model]}


class _Base(TempCase):
    @staticmethod
    def read_text(path: str) -> str:
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def write_data(self, df: pd.DataFrame, name: str = "analysis.csv") -> str:
        path = self.p(name)
        write_csv(path, list(df.columns), df.values.tolist())
        return path

    def write_json(self, obj, name: str) -> str:
        path = self.p(name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        return path


# --------------------------------------------------------------------------- #
# S-01 / S-03: multivariate entry point
# --------------------------------------------------------------------------- #
class MultivariateSpecTest(_Base):
    def test_logit_spec_writes_coef_csv_with_declared_reference(self):
        df = make_model_data()
        self.assertGreater(int(df["restore_any"].sum()), 10)
        data = self.write_data(df)
        spec = self.write_json(logit_spec(), "spec.json")
        out = self.p("out")

        proc = run("auto_stats.py", "--data", data, "--spec", spec, "--out", out,
                   "--vif", "--roc")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        coef = os.path.join(out, "coef_M1.csv")
        self.assertTrue(os.path.isfile(coef))
        rows = read_csv(coef)
        self.assertEqual(len(rows), 4)      # gongyi + year_c + 2 charge dummies
        header = set(rows[0])
        for col in ["model", "term", "beta", "se", "ci_low", "ci_high", "p",
                    "or", "or_low", "or_high", "n", "outcome", "ref", "note"]:
            self.assertIn(col, header)

        by_term = {r["term"]: r for r in rows}
        self.assertEqual(set(by_term), {"gongyi", "year_c",
                                        "charge_f[T.土地资源]", "charge_f[T.其他]"})
        for term in ["charge_f[T.土地资源]", "charge_f[T.其他]"]:
            self.assertEqual(by_term[term]["ref"], REF_CHARGE)
        for row in rows:
            self.assertEqual(row["model"], "M1")
            self.assertEqual(row["outcome"], "restore_any")
            self.assertEqual(int(float(row["n"])), 200)
            # auto_chart_pack --coef consumes term/or/ci_low/ci_high: the CI must
            # be on the OR scale for a logit model.
            self.assertAlmostEqual(float(row["ci_low"]), float(row["or_low"]))
            self.assertLess(float(row["ci_low"]), float(row["or_high"]))
            self.assertLess(math.log(float(row["or_high"])),
                            math.log(float(row["or_low"])) + 10)

        with open(os.path.join(out, "model_summary.md"), encoding="utf-8") as fh:
            summary = fh.read()
        self.assertIn("参照", summary)
        self.assertIn(REF_CHARGE, summary)

        vif = read_csv(os.path.join(out, "vif.csv"))
        self.assertTrue(vif)
        self.assertTrue(all(r["model"] == "M1" for r in vif))
        self.assertTrue(all(float(r["vif"]) >= 1.0 - 1e-6 for r in vif))

        roc = read_csv(os.path.join(out, "roc.csv"))
        self.assertEqual(len(roc), 1)
        auc = float(roc[0]["auc"])
        self.assertTrue(0.0 < auc < 1.0)
        self.assertLessEqual(float(roc[0]["ci_low"]), auc)
        self.assertGreaterEqual(float(roc[0]["ci_high"]), auc)

    def test_ols_spec_reports_beta_scale_and_ref_dict(self):
        data = self.write_data(make_model_data())
        spec = self.write_json({"models": [{
            "id": "M2", "type": "ols", "outcome": "year_c",
            "predictors": ["gongyi", "charge_f"],
            "ref": {"charge_f": "土地资源"},
            "cov": "HC3", "dropna": True,
        }]}, "spec_ols.json")
        out = self.p("out_ols")
        status, err = call_main("--data", data, "--spec", spec, "--out", out)
        self.assertEqual(status, 0, err)

        rows = read_csv(os.path.join(out, "coef_M2.csv"))
        self.assertTrue(rows)
        self.assertEqual({r["term"] for r in rows},
                         {"gongyi", "charge_f[T.森林资源]", "charge_f[T.其他]"})
        dummy = [r for r in rows if r["term"].startswith("charge_f")]
        self.assertTrue(all(r["ref"] == "土地资源" for r in dummy))
        for row in rows:
            self.assertEqual(row["metric"], "beta")
            self.assertLess(float(row["ci_low"]), float(row["ci_high"]))
            self.assertTrue(math.isnan(float(row["or"] or "nan")))

    def test_categorical_without_reference_is_rejected(self):
        data = self.write_data(make_model_data())
        spec = self.write_json({"models": [{
            "id": "X1", "type": "logit", "outcome": "restore_any",
            "predictors": ["C(charge_f)"], "dropna": True,
        }]}, "spec_bad.json")
        status, err = call_main("--data", data, "--spec", spec,
                                "--out", self.p("out_bad"))
        self.assertEqual(status, 2)
        self.assertIn("参照", err)

    def test_vif_without_spec_exits_2(self):
        data = self.write_data(make_model_data())
        status, err = call_main("--data", data, "--vif",
                                "--out", self.p("out_nospec"))
        self.assertEqual(status, 2)
        self.assertIn("--spec", err)


# --------------------------------------------------------------------------- #
# S-02: empty-cell pre-check for the multivariate branch
# --------------------------------------------------------------------------- #
class SeparationTest(_Base):
    def _data_with_empty_cell(self) -> str:
        df = make_model_data()
        idx = df.index[:8]
        df.loc[idx, "charge_f"] = "稀有类型"
        df.loc[idx, "restore_any"] = 0
        return self.write_data(df, "rare.csv")

    def test_drop_reports_separation_and_avoids_huge_or(self):
        data = self._data_with_empty_cell()
        spec = self.write_json(logit_spec(), "spec.json")
        out = self.p("out_drop")
        proc = run("auto_stats.py", "--data", data, "--spec", spec,
                   "--out", out, "--separation", "drop")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        report = read_csv(os.path.join(out, "separation_report.csv"))
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0]["level"], "稀有类型")
        self.assertEqual(report[0]["action"], "dropped")
        self.assertEqual(int(float(report[0]["events"])), 0)

        rows = read_csv(os.path.join(out, "coef_M1.csv"))
        self.assertFalse(any("稀有类型" in r["term"] for r in rows))
        max_or = max(float(r["or"]) for r in rows)
        self.assertLess(max_or, 100.0)          # no OR≈1e9 leaking into the table
        with open(os.path.join(out, "model_summary.md"), encoding="utf-8") as fh:
            self.assertIn("稀有类型", fh.read())

    def test_error_policy_exits_2(self):
        data = self._data_with_empty_cell()
        spec = self.write_json(logit_spec(), "spec.json")
        proc = run("auto_stats.py", "--data", data, "--spec", spec,
                   "--out", self.p("out_err"), "--separation", "error")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("空单元格", proc.stderr)

    def test_merge_reports_merged_level(self):
        data = self._data_with_empty_cell()
        spec = self.write_json(logit_spec(), "spec.json")
        out = self.p("out_merge")
        status, err = call_main("--data", data, "--spec", spec,
                                "--out", out, "--separation", "merge")
        self.assertEqual(status, 0, err)
        report = read_csv(os.path.join(out, "separation_report.csv"))
        self.assertEqual(report[0]["action"], "merged")
        rows = read_csv(os.path.join(out, "coef_M1.csv"))
        self.assertIn("合并水平", " ".join(r["note"] for r in rows))


# --------------------------------------------------------------------------- #
# S-10 / --only
# --------------------------------------------------------------------------- #
class GuardTest(_Base):
    def test_filter_query_injection_is_rejected(self):
        data = self.write_data(make_model_data())
        cfg = self.write_json(
            {"filter_query": "restore_any == 1 and __import__('os')"}, "cfg.json")
        status, err = call_main("--data", data, "--config", cfg,
                                "--out", self.p("out_inj"))
        self.assertEqual(status, 2)
        self.assertIn("filter_query", err)
        self.assertIn("禁止", err)

    def test_sections_only_descriptives(self):
        data = self.write_data(make_model_data())
        out = self.p("out_sec")
        status, err = call_main("--data", data, "--out", out,
                                "--only", "descriptives")
        self.assertEqual(status, 0, err)
        self.assertTrue(os.path.isfile(os.path.join(out, "descriptives.csv")))
        self.assertFalse(os.path.exists(os.path.join(out, "coef_M1.csv")))

    def test_only_models_without_spec_exits_2(self):
        data = self.write_data(make_model_data())
        status, err = call_main("--data", data, "--out", self.p("out_m"),
                                "--only", "models")
        self.assertEqual(status, 2)
        self.assertIn("--spec", err)

    def test_wilson_ci_matches_pubfig(self):
        for k, n in [(0, 10), (5, 10), (20, 20), (1, 3), (0, 0)]:
            low, high = auto_stats.wilson_ci(k, n)
            plow, phigh = pubfig.wilson_ci(k, n)
            if n == 0:
                self.assertTrue(math.isnan(low) and math.isnan(high))
                continue
            self.assertAlmostEqual(low, plow, places=12)
            self.assertAlmostEqual(high, phigh, places=12)

    def test_bh_adjust_is_monotone(self):
        raw = [0.01, 0.04, 0.03, 0.20, 0.001]
        adj = auto_stats.bh_adjust(raw)
        self.assertEqual(len(adj), len(raw))
        paired = sorted(zip(raw, adj))
        self.assertEqual([p for p, _ in paired], sorted(raw))
        self.assertTrue(all(0.0 <= a <= 1.0 for a in adj))
        self.assertGreaterEqual(min(adj), min(raw) - 1e-12)


# --------------------------------------------------------------------------- #
# P-07: log axis ticks
# --------------------------------------------------------------------------- #
class LogAxisTest(TempCase):
    def setUp(self):
        super().setUp()
        self.fig, self.ax = plt.subplots(figsize=(6, 3))

    def tearDown(self):
        plt.close(self.fig)
        super().tearDown()

    def test_forest_plot_log_axis_has_no_minor_ticks(self):
        pubfig.forest_plot(self.ax, ["a", "b", "c", "d"],
                           [0.8, 1.2, 2.5, 6.0], [0.5, 1.0, 1.5, 3.0],
                           [1.2, 1.5, 4.0, 12.0], xlabel="OR (95% CI)")
        self.assertEqual(self.ax.get_xscale(), "log")
        self.assertIsInstance(self.ax.xaxis.get_minor_locator(), NullLocator)
        self.assertIsInstance(self.ax.xaxis.get_minor_formatter(), NullFormatter)
        self.assertEqual(len(self.ax.xaxis.get_minorticklocs()), 0)
        texts = [t.get_text() for t in self.ax.get_xticklabels() if t.get_text()]
        self.assertTrue(texts)
        for text in texts:
            self.assertNotIn("e+", text.lower())
            float(text)                       # every label is a plain number

    def test_huge_ci_is_clipped_with_note(self):
        pubfig.forest_plot(self.ax, ["a", "b", "rare"],
                           [0.9, 1.4, 1e3], [0.6, 1.1, 1e-3], [1.3, 1.8, 1e9],
                           xlabel="OR (95% CI)")
        lo, hi = self.ax.get_xlim()
        self.assertLessEqual(math.log10(hi) - math.log10(lo), 8.0 + 1e-9)
        notes = [t.get_text() for t in self.ax.texts]
        self.assertTrue(any("CI" in s for s in notes))

    def test_scatter_fit_log_axis_ticks(self):
        x = np.linspace(1, 100, 30)
        pubfig.scatter_fit(self.ax, x, 2 * x + 1, logx=True, logy=True)
        self.assertEqual(len(self.ax.xaxis.get_minorticklocs()), 0)
        self.assertEqual(len(self.ax.yaxis.get_minorticklocs()), 0)


# --------------------------------------------------------------------------- #
# P-01/P-02/P-04/P-05/P-06: layout
# --------------------------------------------------------------------------- #
class LayoutTest(TempCase):
    def test_stacked_bar_legend_stays_inside(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            top = pubfig.stacked_bar(
                ax, ["A", "B", "C", "D"],
                [[3, 4, 2, 5], [2, 1, 3, 1], [1, 1, 2, 1]],
                ["forest", "land", "other"], normalize=True)
            fig.canvas.draw()
        plt.close(fig)
        self.assertIsNotNone(top)
        self.assertLess(fig.subplotpars.top, 0.95)
        layout_warnings = [str(w.message) for w in caught
                           if any(k in str(w.message).lower()
                                  for k in ("legend", "tight", "outside", "bbox"))]
        self.assertEqual(layout_warnings, [])

    def test_stacked_area_legend_returns_top(self):
        fig, ax = plt.subplots(figsize=(6, 4))
        top = pubfig.stacked_area(ax, [1, 2, 3, 4],
                                  [[1, 2, 3, 4], [2, 1, 2, 1]],
                                  ["series a", "series b"])
        plt.close(fig)
        self.assertIsNotNone(top)
        self.assertLess(top, 0.98)

    def test_save_fig_writes_600dpi_15cm_png(self):
        from PIL import Image
        fig, ax = plt.subplots(figsize=(15 / 2.54, 9 / 2.54))
        ax.plot([0, 1], [0, 1])
        paths = pubfig.save_fig(fig, self.p("figs"), "width", formats=["png"])
        self.assertEqual(len(paths), 1)
        with Image.open(paths[0]) as im:
            width, height = im.size
            dpi = im.info.get("dpi", (0, 0))[0]
        self.assertLessEqual(abs(width - 3543), 30)   # 15 cm at 600 dpi
        self.assertGreaterEqual(dpi, 590)

    def test_save_fig_pad_insets_axes(self):
        fig, ax = plt.subplots(figsize=(15 / 2.54, 9 / 2.54))
        ax.plot([0, 1], [0, 1])
        before = float(fig.subplotpars.left)
        paths = pubfig.save_fig(fig, self.p("figs_pad2"), "pad2",
                                formats=["png"], pad=0.1)
        self.assertEqual(len(paths), 1)
        self.assertGreater(float(fig.subplotpars.left), before)

    def test_bar_with_ci_headroom_and_annotation(self):
        fig, ax = plt.subplots(figsize=(5, 3))
        pubfig.bar_with_ci(ax, ["a", "b", "c"], [0.2, 0.4, 0.3],
                           [0.1, 0.3, 0.2], [0.3, 0.5, 0.4], annotate=True)
        lo, hi = ax.get_ylim()
        plt.close(fig)
        self.assertAlmostEqual(lo, 0.0)
        self.assertGreater(hi, 0.5)
        self.assertLessEqual(hi, 0.5 * 1.12)

    def test_pie_chart_merges_small_slices(self):
        fig, ax = plt.subplots(figsize=(4, 4))
        pubfig.pie_chart(ax, ["A", "B", "C", "D"], [80, 10, 6, 4],
                         label_threshold=0.07)
        legend_texts = [t.get_text() for t in ax.get_legend().get_texts()]
        plt.close(fig)
        self.assertEqual(len(legend_texts), 3)
        self.assertTrue(any("A" in t for t in legend_texts))

    def test_lift_chart_decile_one_is_highest_risk(self):
        rng = np.random.default_rng(3)
        y = rng.binomial(1, 0.4, 400)
        # Perfect ranking plus a tiny jitter: deterministic, no ties.
        score = y + rng.uniform(0, 1e-3, 400)
        fig, ax = plt.subplots(figsize=(5, 3))
        table = pubfig.lift_chart(ax, y, score, bins=5)
        labels = [t.get_text() for t in ax.get_xticklabels()
                  if t.get_text().startswith("D")]
        plt.close(fig)
        self.assertEqual(labels, ["D1", "D2", "D3", "D4", "D5"])
        self.assertEqual(len(table), 5)
        lifts = table["lift"].to_numpy(dtype=float)
        self.assertGreater(lifts[0], lifts[-1])
        self.assertAlmostEqual(float(table["event_rate"].iloc[0]), 1.0, places=6)


# --------------------------------------------------------------------------- #
# P-03 / wilson: pure helpers
# --------------------------------------------------------------------------- #
class HelperTest(TempCase):
    def test_short_label_keeps_dummy_level(self):
        self.assertEqual(pubfig.short_label("court_f[T.中级]"), "court_f：中级")
        self.assertEqual(pubfig.short_label("charge_f[T.森林资源]"),
                         "charge_f：森林资源")
        self.assertEqual(pubfig.short_label("gongyi"), "gongyi")
        long_name = "very_long_variable_name_that_will_not_fit"
        out = pubfig.short_label(long_name)
        self.assertTrue(out.endswith("…"))
        self.assertLessEqual(len(out), 24)

    def test_short_label_budget_is_respected(self):
        out = pubfig.short_label("charge_f[T.森林资源]", max_chars=12)
        self.assertLessEqual(len(out), 12)
        self.assertIn("森林资源", out)

    def test_wilson_ci_bounds_are_monotone(self):
        prev = (-1.0, -1.0)
        for k in range(0, 21):
            low, high = pubfig.wilson_ci(k, 20)
            self.assertGreaterEqual(low, 0.0)
            self.assertLessEqual(high, 1.0)
            self.assertLessEqual(low, high)
            self.assertGreaterEqual(low, prev[0] - 1e-12)
            prev = (low, high)


# --------------------------------------------------------------------------- #
# A3: subset / coef_all.csv / fit.csv, and C2: sample-flow reconciliation
# --------------------------------------------------------------------------- #
class ModelTablesTest(_Base):
    def _run_models(self, spec, *extra, data=None):
        data = data or self.write_data(make_model_data())
        spec_path = self.write_json(spec, "spec.json")
        out = self.p("out")
        status, err = call_main("--data", data, "--spec", spec_path, "--out", out,
                                "--only", "models", *extra)
        return status, err, out

    def test_subset_narrows_sample_and_records_it(self):
        spec = logit_spec()
        spec["models"][0]["subset"] = "year_c >= 0"
        status, err, out = self._run_models(spec)
        self.assertEqual(status, 0, err)
        coef = read_csv(os.path.join(out, "coef_M1.csv"))
        self.assertTrue(coef)
        self.assertEqual({r["sample"] for r in coef}, {"year_c >= 0"})
        n_model = int(float(coef[0]["n"]))
        self.assertLess(n_model, 200)
        self.assertGreater(n_model, 20)
        fit = read_csv(os.path.join(out, "fit.csv"))
        self.assertEqual(fit[0]["subset"], "year_c >= 0")
        with open(os.path.join(out, "model_meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
        self.assertEqual(meta["subsets"]["M1"], "year_c >= 0")
        summary = self.read_text(os.path.join(out, "model_summary.md"))
        self.assertIn("子样本", summary)
        self.assertIn("year_c >= 0", summary)

    def test_subset_empty_sample_exits_2(self):
        spec = logit_spec()
        spec["models"][0]["subset"] = "year_c > 999"
        status, err, _ = self._run_models(spec)
        self.assertEqual(status, 2)
        self.assertIn("M1", err)
        self.assertIn("year_c > 999", err)

    def test_subset_injection_is_rejected(self):
        spec = logit_spec()
        spec["models"][0]["subset"] = "__import__('os')"
        status, err, _ = self._run_models(spec)
        self.assertEqual(status, 2)
        self.assertIn("subset", err)
        self.assertIn("禁止", err)

    def test_coef_all_columns_labels_and_declaration_order(self):
        m1 = logit_spec()["models"][0]
        m2 = dict(m1, id="M2", cluster=None, cov=None,
                  predictors=["gongyi", "year_c"],
                  labels={"gongyi": "一审子样本公益"})
        spec = {"labels": {"gongyi": "公益诉讼", "charge_f": "案由"},
                "models": [m2, m1]}
        status, err, out = self._run_models(spec)
        self.assertEqual(status, 0, err)
        rows = read_csv(os.path.join(out, "coef_all.csv"))
        self.assertEqual(list(rows[0].keys()), auto_stats.TABLE_COLUMNS["coef_all"])
        self.assertEqual([r["model"] for r in rows],
                         ["M2", "M2", "M1", "M1", "M1", "M1"])
        self.assertEqual([r["term"] for r in rows if r["model"] == "M1"],
                         ["gongyi", "year_c",
                          "charge_f[T.土地资源]", "charge_f[T.其他]"])
        labels = {r["term"]: r["label"] for r in rows if r["model"] == "M1"}
        self.assertEqual(labels["gongyi"], "公益诉讼")
        self.assertEqual(labels["charge_f[T.土地资源]"], "案由：土地资源")
        m2_labels = {r["term"]: r["label"] for r in rows if r["model"] == "M2"}
        self.assertEqual(m2_labels["gongyi"], "一审子样本公益")
        for row in rows:
            self.assertEqual(row["stars"], auto_stats._stars(float(row["p"])))

    def test_stars_thresholds(self):
        cases = [(0.0009, "***"), (0.009, "**"), (0.04, "*"), (0.09, "."),
                 (0.2, ""), (float("nan"), "")]
        for p, expected in cases:
            self.assertEqual(auto_stats._stars(p), expected, p)

    def test_fit_csv_llr_and_pseudo_r2_match_summary(self):
        status, err, out = self._run_models(logit_spec())
        self.assertEqual(status, 0, err)
        fit = read_csv(os.path.join(out, "fit.csv"))
        self.assertEqual(list(fit[0].keys()), auto_stats.TABLE_COLUMNS["fit"])
        row = fit[0]
        self.assertNotEqual(row["llr_p"], "")
        self.assertGreater(float(row["llr"]), 0.0)
        self.assertGreaterEqual(float(row["llr_p"]), 0.0)
        self.assertLessEqual(float(row["llr_p"]), 1.0)
        self.assertEqual(int(float(row["llr_df"])), int(float(row["k"])) - 1)
        coef_all = read_csv(os.path.join(out, "coef_all.csv"))
        self.assertEqual(len(coef_all), 4)
        self.assertEqual(coef_all[0]["sample"], "full")
        summary = self.read_text(os.path.join(out, "model_summary.md"))
        match = re.search(r"McFadden R²=([0-9.]+)", summary)
        self.assertIsNotNone(match)
        self.assertAlmostEqual(float(row["pseudo_r2"]), float(match.group(1)), places=2)

    def test_sample_flow_match_and_mismatch(self):
        data = self.write_data(make_model_data())
        spec = logit_spec()
        spec["models"][0]["flow_stage"] = "M1"
        spec_path = self.write_json(spec, "spec.json")
        out = self.p("out")
        status, err = call_main("--data", data, "--spec", spec_path, "--out", out,
                                "--only", "models")
        self.assertEqual(status, 0, err)
        n_model = int(float(read_csv(os.path.join(out, "coef_M1.csv"))[0]["n"]))
        flow = self.p("flow.csv")

        write_csv(flow, ["stage", "n", "note"], [["M1", n_model, ""]])
        status, err = call_main("--data", data, "--spec", spec_path, "--out", out,
                                "--only", "models", "--sample-flow", flow)
        self.assertEqual(status, 0, err)
        summary = self.read_text(os.path.join(out, "model_summary.md"))
        self.assertIn("flow 校验", summary)
        self.assertIn("✓", summary)
        fit = read_csv(os.path.join(out, "fit.csv"))
        self.assertEqual(fit[0]["flow_match"], "TRUE")
        self.assertEqual(int(float(fit[0]["flow_n"])), n_model)

        # A mismatch is a warning only: exit code stays 0.
        write_csv(flow, ["stage", "n", "note"], [["M1", n_model + 1, ""]])
        status, err = call_main("--data", data, "--spec", spec_path, "--out", out,
                                "--only", "models", "--sample-flow", flow)
        self.assertEqual(status, 0, err)
        self.assertIn("WARN", err)
        self.assertIn(str(n_model + 1), err)
        summary = self.read_text(os.path.join(out, "model_summary.md"))
        self.assertIn("≠", summary)
        fit = read_csv(os.path.join(out, "fit.csv"))
        self.assertEqual(fit[0]["flow_match"], "FALSE")

    def test_undeclared_flow_stage_is_not_checked(self):
        data = self.write_data(make_model_data())
        spec_path = self.write_json(logit_spec(), "spec.json")
        out = self.p("out")
        flow = self.p("flow.csv")
        write_csv(flow, ["stage", "n", "note"], [["M1", 200, ""]])
        status, err = call_main("--data", data, "--spec", spec_path, "--out", out,
                                "--only", "models", "--sample-flow", flow)
        self.assertEqual(status, 0, err)
        self.assertNotIn("WARN", err)
        fit = read_csv(os.path.join(out, "fit.csv"))
        self.assertEqual(fit[0]["flow_n"], "")
        self.assertEqual(fit[0]["flow_match"], "")
        summary = self.read_text(os.path.join(out, "model_summary.md"))
        self.assertNotIn("flow 校验", summary)
        self.assertIn("flow 说明", summary)

    def test_declared_missing_stage_exits_2(self):
        data = self.write_data(make_model_data())
        spec = logit_spec()
        spec["models"][0]["flow_stage"] = "不存在的漏斗行"
        spec_path = self.write_json(spec, "spec.json")
        flow = self.p("flow.csv")
        write_csv(flow, ["stage", "n", "note"], [["M1", 200, ""]])
        status, err = call_main("--data", data, "--spec", spec_path,
                                "--out", self.p("out"),
                                "--only", "models", "--sample-flow", flow)
        self.assertEqual(status, 2)
        self.assertIn("flow_stage", err)
        self.assertIn("不存在的漏斗行", err)
        self.assertIn("M1", err)

    def test_md_formats_llr_p_underflow_as_floor(self):
        self.assertEqual(auto_stats._fmt_llr_p(1e-320), "<1e-300")
        self.assertEqual(auto_stats._fmt_llr_p(0.0), "<1e-300")
        self.assertNotIn("<1e-300", auto_stats._fmt_llr_p(0.03))
        frame = pd.DataFrame([{"term": "x", "beta": 0.1, "se": 0.1,
                               "ci_low": 0.9, "ci_high": 1.2, "p": 0.5,
                               "or": 1.1, "metric": "OR", "ref": "", "note": ""}])
        info = {"mid": "M1", "mtype": "logit", "outcome": "y", "n": 100,
                "n_dropped": 3, "n_removed_separation": 0, "subset": None,
                "n_events": 40, "se_type": "HC1", "llf": -50.0, "llnull": -60.0,
                "llr": 20.0, "llr_df": 3, "llr_p": 0.0, "aic": 106.0,
                "predictors": [], "outcome_map": {}, "excluded": [],
                "rsquared": float("nan"), "rsquared_adj": float("nan"),
                "f_pvalue": float("nan"), "label": None, "note": None}
        text = "\n".join(auto_stats._render_model_summary(
            frame, info, [], [], None))
        self.assertIn("LLR χ²", text)
        self.assertIn("p=<1e-300", text)

    def test_sample_flow_requires_spec(self):
        data = self.write_data(make_model_data())
        flow = self.p("flow.csv")
        write_csv(flow, ["stage", "n", "note"], [["M1", 200, ""]])
        status, err = call_main("--data", data, "--out", self.p("out"),
                                "--sample-flow", flow)
        self.assertEqual(status, 2)
        self.assertIn("--spec", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
