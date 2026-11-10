# -*- coding: utf-8 -*-
"""Tests for scripts/auto_chart_pack.py: manifest v2, N handling, layout, CLI.

Standard-library unittest only (no pytest in this environment).  matplotlib is
forced to the Agg backend so nothing needs a display, and every test builds its
own throw-away workspace through ``_helpers.TempCase``.  No network, no user
corpus: the fixtures are 120 synthetic rows written on the fly.
"""
import json
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempCase, run, write_csv, read_csv

# Child processes must emit UTF-8 on Windows (the default is the console codepage,
# which _helpers.run() would then decode as mojibake).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import matplotlib
matplotlib.use("Agg")

SCRIPT = "auto_chart_pack.py"

# docs/CONTRACTS.md §3 -- the columns a v2 manifest must carry.
MANIFEST_V2 = [
    "id", "question", "chart_type", "variables", "n", "n_scope",
    "png", "pdf", "caption", "dpi", "px_width", "model_id", "data_hash",
    "tiff", "note",
]
REQUIRED_V2 = ["id", "question", "chart_type", "variables", "n", "n_scope",
               "png", "pdf", "caption"]

# Every figure is 15 cm wide (FIG_W = 15/2.54 in) at 600 dpi, so a PNG is 3543 px
# wide whatever the chart type -- including the donut and the Q-Q that used to be
# drawn on a 4.8-inch square canvas (px_width 2880).
WIDTH_FLOOR = 3500

HEADER = ["id", "year", "category", "stage", "region", "outcome_binary",
          "amount", "duration_days", "charge_f"]
CATEGORIES = ["污染环境", "滥伐林木", "非法占用农用地", "非法捕捞水产品", "其他"]
STAGES = ["侦查", "起诉", "审判"]
REGIONS = ["东部", "中部", "西部"]
CHARGES = ["水生资源", "林木资源", "土地资源", "矿产资源"]


def synthetic_rows(n: int = 120) -> list[dict]:
    """Deterministic 120-row analysis table: categoricals, a 0/1 outcome, numerics."""
    rows = []
    for i in range(n):
        rows.append({
            "id": f"C{i + 1:03d}",
            "year": 2019 + (i % 4),
            "category": CATEGORIES[i % len(CATEGORIES)],
            "stage": STAGES[i % len(STAGES)],
            "region": REGIONS[(i // 2) % len(REGIONS)],
            "outcome_binary": 1 if (i * 7) % 10 < 4 else 0,
            "amount": round(1200.0 + (i * 337) % 45000, 2),
            "duration_days": 15 + (i * 13) % 380,
            "charge_f": CHARGES[i % len(CHARGES)],
        })
    return rows


class PackCLICase(TempCase):
    """Exercise the script through argparse/exit codes, like a user would."""

    def setUp(self):
        super().setUp()
        self.data = write_csv(self.p("x.csv"), HEADER, synthetic_rows())

    def out(self, name: str = "out") -> str:
        return self.p(name)

    def manifest(self, out_dir: str) -> list[dict]:
        path = os.path.join(out_dir, "chart_manifest.csv")
        self.assertTrue(os.path.isfile(path), f"missing manifest: {path}")
        return read_csv(path)

    def test_config_naming_missing_columns_lists_what_exists(self):
        """A borrowed config must fail with the column names, not with a NameError."""
        cfg = self.p("cfg.json")
        with open(cfg, "w", encoding="utf-8") as handle:
            json.dump({"outcome": "no_such_outcome", "group": "no_such_group",
                       "filter_query": "no_such_flag == 1"}, handle, ensure_ascii=False)
        proc = run(SCRIPT, "--data", self.data, "--config", cfg,
                   "--out", self.out("cfg"), "--max-charts", 1)
        self.assertEqual(proc.returncode, 2, proc.stdout[-800:])
        self.assertIn("no_such_outcome", proc.stderr)
        self.assertIn("no_such_group", proc.stderr)
        self.assertIn("available (first 25)", proc.stderr)
        # the filter error must never surface as a bare pandas NameError
        self.assertNotIn("Traceback", proc.stderr)

    def test_filter_query_with_unknown_column_suggests_a_name(self):
        cfg = self.p("cfg2.json")
        with open(cfg, "w", encoding="utf-8") as handle:
            json.dump({"filter_query": "outcome_binaryy == 1"}, handle,
                      ensure_ascii=False)
        proc = run(SCRIPT, "--data", self.data, "--config", cfg,
                   "--out", self.out("cfg2"), "--max-charts", 1)
        self.assertEqual(proc.returncode, 2, proc.stdout[-800:])
        self.assertIn("outcome_binaryy", proc.stderr)
        self.assertIn("did you mean", proc.stderr)

    def test_manifest_v2_fields(self):
        """A normal run writes manifest v2 with real dpi/px_width/data_hash."""
        out = self.out()
        # --max-charts keeps the suite inside its 120 s budget (the full 43-chart
        # pack takes ~80 s); it does not change how a single row is written.
        proc = run(SCRIPT, "--data", self.data, "--out", out,
                   "--top-n", 4, "--min-n", 3, "--max-charts", 14)
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        rows = self.manifest(out)
        self.assertGreaterEqual(len(rows), 8)

        header = list(rows[0].keys())
        for col in REQUIRED_V2:
            self.assertIn(col, header)
        for col in MANIFEST_V2:
            self.assertIn(col, header)

        ok = [r for r in rows if r["status"] == "ok"]
        self.assertGreaterEqual(len(ok), 8)
        self.assertLessEqual(len(ok), 14)                 # --max-charts honoured
        for row in ok:
            with self.subTest(chart=row["id"]):
                self.assertEqual(int(row["dpi"]), 600)
                self.assertIn(row["n_scope"], {"sample", "corpus", "subgroup"})
                self.assertRegex(row["data_hash"], r"^[0-9a-f]{8}$")
                self.assertIn("N=", row["caption"])
                self.assertIn("top=", row["note"])        # adjust() recorded
                self.assertTrue(int(row["n"]) > 0)
                # Paths are relative to the manifest directory, POSIX style.
                for key in ("png", "pdf", "tiff"):
                    self.assertFalse(os.path.isabs(row[key]), row[key])
                    self.assertNotIn("\\", row[key])
                    self.assertTrue(os.path.isfile(os.path.join(out, row[key])),
                                    row[key])
                # Uniform 15 cm canvas: no more 2880-px square charts.
                self.assertGreaterEqual(int(row["px_width"]), WIDTH_FLOOR, row["id"])

        donuts = [r for r in ok if r["chart_type"] in {"donut", "pie"}]
        self.assertTrue(donuts, "the pack should still draw the treatment donut")
        for row in donuts:
            self.assertGreaterEqual(int(row["dpi"]), 590)

        self.assertEqual(len({r["data_hash"] for r in rows}), 1,
                         "one dataset must hash to one data_hash")
        self.assertIn("data_hash", proc.stdout)

    def test_manifest_paths_survive_moving_the_output(self):
        """The whole output directory can be moved: no absolute paths in the CSV."""
        out = self.out("movable")
        proc = run(SCRIPT, "--data", self.data, "--out", out,
                   "--top-n", 4, "--min-n", 3, "--max-charts", 2)
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        ok = [r for r in self.manifest(out) if r["status"] == "ok"]
        self.assertTrue(ok)

        moved = self.p("moved-pack")
        shutil.move(out, moved)
        rows = self.manifest(moved)
        for row in rows:
            if not row["png"]:
                continue
            for key in ("png", "pdf", "tiff"):
                self.assertTrue(os.path.isfile(os.path.join(moved, row[key])),
                                f"{key} broke after moving: {row[key]}")

    def test_pack_counts_match_manifest(self):
        """chart_pack.json counts never contradict the manifest or chart_pack.md."""
        out = self.out("counts")
        proc = run(SCRIPT, "--data", self.data, "--out", out,
                   "--top-n", 4, "--min-n", 3, "--max-charts", 4)
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])

        rows = self.manifest(out)
        with open(os.path.join(out, "chart_pack.json"), encoding="utf-8") as fh:
            pack = json.load(fh)
        counts = pack["counts"]

        self.assertEqual(counts["ok"], len([r for r in rows if r["status"] == "ok"]))
        self.assertEqual(counts["error"], 0)
        self.assertEqual(len(pack["skipped"]), counts["skipped_total"])
        self.assertGreaterEqual(counts["skipped_total"], counts["skipped"])

        with open(os.path.join(out, "chart_pack.md"), encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn(f"图表数：{counts['ok']}", md)
        self.assertIn(f"跳过：{counts['skipped_total']}", md)

    def test_list_charts_exits_zero(self):
        """--list-charts prints the catalogue and needs no data file."""
        proc = run(SCRIPT, "--list-charts")
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        for token in ("图型清单", "missingness", "group_treatment_stacked",
                      "forest_{}", "survival_km", "pareto_group"):
            self.assertIn(token, proc.stdout)

    def test_only_limits_output(self):
        """--only emits exactly the requested chart (and says what it filtered)."""
        out = self.out("only")
        # --no-tiff rides along here: one extra flag on a 1-chart run, no extra run.
        proc = run(SCRIPT, "--data", self.data, "--out", out,
                   "--top-n", 4, "--min-n", 3, "--only", "treatment_donut",
                   "--no-tiff")
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])
        rows = self.manifest(out)
        ok = [r for r in rows if r["status"] == "ok"]
        self.assertEqual(len(ok), 1, [r["png"] for r in ok])
        self.assertIn("treatment_donut", os.path.basename(ok[0]["png"]))
        figures = [f for f in os.listdir(os.path.join(out, "figures"))
                   if f.endswith(".png")]
        self.assertEqual(len(figures), 1)
        self.assertIn("filtered", proc.stdout)
        # tiff is on by default (P-09); --no-tiff has to switch it off cleanly.
        self.assertEqual(ok[0]["tiff"], "")
        self.assertFalse([f for f in os.listdir(os.path.join(out, "figures"))
                          if f.endswith(".tiff")])

    def test_forest_keeps_mixed_logit_and_ols_rows(self):
        """One coef CSV, two families: no row may vanish from the forest plot."""
        coef = write_csv(
            self.p("coef_mixed.csv"),
            ["model", "term", "metric", "or", "or_low", "or_high",
             "beta", "ci_low", "ci_high", "n"],
            [
                {"model": "M1 主模型", "term": "amount", "metric": "OR",
                 "or": 1.8, "or_low": 1.2, "or_high": 2.7,
                 "beta": 0.588, "ci_low": 0.182, "ci_high": 0.993, "n": 120},
                {"model": "M1 主模型", "term": "year", "metric": "OR",
                 "or": 1.1, "or_low": 0.9, "or_high": 1.3,
                 "beta": 0.095, "ci_low": -0.105, "ci_high": 0.262, "n": 120},
                {"model": "M1 主模型", "term": "charge_f[T.土地资源]", "metric": "OR",
                 "or": 0.6, "or_low": 0.4, "or_high": 0.9,
                 "beta": -0.511, "ci_low": -0.916, "ci_high": -0.105, "n": 120},
                # OLS rows: or/OR columns are blank, only beta/CI are filled.
                {"model": "M2 OLS", "term": "amount", "metric": "b",
                 "or": "", "or_low": "", "or_high": "",
                 "beta": 0.42, "ci_low": 0.11, "ci_high": 0.73, "n": 118},
                {"model": "M2 OLS", "term": "age", "metric": "b",
                 "or": "", "or_low": "", "or_high": "",
                 "beta": -0.08, "ci_low": -0.2, "ci_high": 0.04, "n": 118},
            ])
        out = self.out("forest")
        proc = run(SCRIPT, "--data", self.data, "--out", out, "--top-n", 4,
                   "--min-n", 3, "--coef", coef, "--only", "forest_")
        self.assertEqual(proc.returncode, 0, proc.stderr[-3000:])

        ok = [r for r in self.manifest(out) if r["status"] == "ok"]
        self.assertEqual(len(ok), 2, [r["id"] for r in ok])
        self.assertEqual({r["model_id"] for r in ok}, {"M1 主模型", "M2 OLS"})
        # N comes from the coef file's n column: 120 (logit) and 118 (OLS).
        self.assertEqual(sorted(int(r["n"]) for r in ok), [118, 120])
        for row in ok:
            self.assertEqual(row["chart_type"], "forest plot")

        with open(os.path.join(out, "chart_pack.json"), encoding="utf-8") as fh:
            charts = json.load(fh)["charts"]
        meta = {c["model_id"]: c for c in charts}
        self.assertEqual(meta["M1 主模型"]["rows_plotted"], 3)
        self.assertEqual(meta["M2 OLS"]["rows_plotted"], 2)
        self.assertEqual(sum(c["rows_plotted"] for c in charts), 5,
                         "every coefficient row must reach a figure")
        for chart in charts:
            self.assertEqual(chart["rows_dropped"], 0)
            self.assertIn(chart["metric"], {"OR", "β"})


class ScopeAndNCase(TempCase):
    """n / n_scope semantics, driven through the ChartPack API directly."""

    def pack(self, out: str | None = None, rows: int = 40):
        import pandas as pd
        import auto_chart_pack as acp
        df = pd.DataFrame({
            "y": [0, 1] * (rows // 2),
            "g": [f"g{i % 4}" for i in range(rows)],
        })
        return acp.ChartPack(df, out or self.p("out"), {"outcome": "y"},
                             ["png"], top_n=4, min_n=3)

    @staticmethod
    def figure():
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(["a", "b", "c"], [3, 5, 2])
        return fig

    def test_corpus_scope_allows_n_above_row_count(self):
        """n_scope='corpus' is the only scope allowed to exceed the row count."""
        pack = self.pack()
        n_rows = len(pack.df)
        pack.save(self.figure(), "corpus_probe", "A 数据质量",
                  "语料级 N 可以大于数据行数吗？", "horizontal bar", ["y"],
                  n=n_rows + 500, n_scope="corpus",
                  caption="注：N=9,999；语料级计数；数据来源：分析数据集。")
        row = pack.manifest[-1]
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["n_scope"], "corpus")
        self.assertEqual(row["n"], n_rows + 500)
        self.assertEqual(pack.errors, 0)
        self.assertTrue(os.path.isfile(os.path.join(pack.out_dir, row["png"])))
        self.assertIn(f"N={n_rows + 500:,}", row["caption"])
        self.assertNotIn("9,999", row["caption"])

    def test_sample_scope_rejects_n_above_row_count(self):
        """The same N under the default scope is an error row, not a silent skip."""
        pack = self.pack()
        pack.save(self.figure(), "sample_probe", "A 数据质量",
                  "样本级 N 能否超过行数？", "horizontal bar", ["y"],
                  n=len(pack.df) + 500)
        row = pack.manifest[-1]
        self.assertTrue(row["status"].startswith("error"), row["status"])
        self.assertEqual(pack.errors, 1)
        self.assertEqual(row["png"], "")

    def test_zero_n_is_recorded_not_dropped(self):
        """n<=0 keeps a manifest row with the reason and prints it to stdout."""
        import contextlib
        import io
        pack = self.pack()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pack.save(self.figure(), "zero_probe", "B 单变量",
                      "N=0 时会静默丢弃吗？", "bar", ["y"], n=0)
        row = pack.manifest[-1]
        self.assertEqual(row["status"], "skipped: n<=0")
        self.assertIn("skipped: n<=0", buf.getvalue())
        self.assertEqual(len(pack.manifest), 1)
        self.assertTrue(pack.skipped)

    def test_caption_n_is_rewritten_everywhere(self):
        """Both N= tokens in a caption follow the parsed N (no count=1 leak)."""
        import auto_chart_pack as acp
        caption = "注：N=1,200；漏斗：原始 N=999、完整案例 N=1,180；数据来源：分析数据集。"
        out = acp.fill_caption_n(caption, "2,713")
        self.assertNotIn("1,200", out)
        self.assertNotIn("999", out)
        self.assertEqual(out.count("N=2,713"), 3)

    def test_parse_n_accepts_range_and_prefix(self):
        """CONTRACTS §3 N formats: int, thousands separator, range, N= prefix."""
        import auto_chart_pack as acp
        self.assertEqual(acp.parse_n(2713), (2713, "2,713"))
        self.assertEqual(acp.parse_n("2,713"), (2713, "2,713"))
        self.assertEqual(acp.parse_n("3111→2713"), (3111, "3111→2713"))
        self.assertEqual(acp.parse_n("3111-2713"), (3111, "3111-2713"))
        self.assertEqual(acp.parse_n("N=2713"), (2713, "2,713"))
        self.assertIsNone(acp.parse_n("n/a")[0])


class ShortLabelCase(unittest.TestCase):
    """Dummy-coded terms must stay distinguishable on an axis."""

    def test_dummy_levels_do_not_collapse(self):
        import auto_chart_pack as acp
        labels = [
            acp.short_label("C(charge_f)[T.水生资源]"),
            acp.short_label("C(charge_f)[T.林木资源]"),
            acp.short_label("C(charge_f)[T.土地资源]"),
            acp.short_label("charge_f[T.矿产资源]"),
        ]
        self.assertEqual(len(set(labels)), len(labels), labels)
        for label, level in zip(labels, ["水生资源", "林木资源", "土地资源", "矿产资源"]):
            self.assertIn("charge_f", label)
            self.assertIn(level, label)
            self.assertIn("：", label)

    def test_label_keeps_the_data_text(self):
        """No character is scrubbed out of a label (the old code deleted 「罪」)."""
        import auto_chart_pack as acp
        label = acp.short_label("C(charge_f)[T.污染环境罪]")
        self.assertIn("罪", label)
        self.assertIn("污染环境罪", label)

    def test_plain_and_long_values(self):
        """Long labels are truncated with an ellipsis; short ones pass through."""
        import auto_chart_pack as acp
        self.assertEqual(acp.short_label("侦查"), "侦查")
        self.assertEqual(acp.short_label("amount"), "amount")
        # pubfig's budget: 16 glyphs for CJK labels, 24 for ASCII ones.
        long_cjk = acp.short_label("某" * 60)
        self.assertLessEqual(len(long_cjk), 16)
        self.assertTrue(long_cjk.endswith("…"), long_cjk)
        long_ascii = acp.short_label("very_long_english_variable_name_here")
        self.assertLessEqual(len(long_ascii), 24)
        self.assertTrue(long_ascii.endswith("…"), long_ascii)

    def test_delegates_to_pubfig(self):
        """One label implementation, not a local copy that drifts (no copy fork)."""
        import auto_chart_pack as acp
        import pubfig
        # The local wrapper only strips the C(...) shell before handing over.
        self.assertEqual(acp.short_label("C(x)[T.甲]"), "x：甲")
        for value in ("charge_f[T.水生资源]", "侦查", "amount", "某" * 40):
            self.assertEqual(acp.short_label(value), pubfig.short_label(value), value)


class DegenerateCorrespondenceCase(TempCase):
    """CA on data with a single non-trivial dimension must skip, not crash.

    Regression: a 7x2 table from a real corpus gave ``sv = [0.220, 9.8e-17]``.
    The biplot then had a y-axis whose data span was ~1e-16, so the per-point
    ``ax.text`` coordinates overflowed int64 at 600 dpi and matplotlib raised
    ``TypeError: _set_transform(): incompatible function arguments`` -- which
    killed the whole pack before the manifest was written.
    """

    def pack(self, out: str | None = None):
        """A 5x2 table: with only two columns the second dimension is exactly 0."""
        import pandas as pd
        import auto_chart_pack as acp
        rows = []
        for i, (cat, stage, n) in enumerate(
                [("a", "术前", 40), ("b", "术前", 12), ("c", "术后", 25),
                 ("d", "术后", 9), ("e", "术后", 18)]):
            rows += [{"cat": cat, "stage": stage}] * n
        return acp.ChartPack(pd.DataFrame(rows), out or self.p("out"), {},
                             ["png"], top_n=8, min_n=3)

    def test_single_dimension_is_skipped(self):
        pack = self.pack()
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            pack.correspondence("cat", "stage")
        self.assertEqual(pack.manifest, [])                     # nothing drawn
        self.assertEqual(len(pack.skipped), 1)
        self.assertIn("退化", pack.skipped[0]["reason"])
        self.assertEqual(pack.errors, 0)                        # a skip, not an error

    def test_zero_inertia_is_skipped_before_the_dimension_check(self):
        """Independence means nothing to plot -- and the first guard must catch it.

        A table whose rows are proportional to each other has total inertia 0, so
        every singular value is 0 and even ``sv[1]`` is "not small".  Without the
        zero-inertia guard the code falls through to the dimension check and, on a
        later refactor, would divide by zero instead of skipping.
        """
        import pandas as pd
        import auto_chart_pack as acp
        cells = {("g1", "s1"): 10, ("g1", "s2"): 20,
                 ("g2", "s1"): 20, ("g2", "s2"): 40}     # exactly proportional
        rows = []
        for (g, s), n in cells.items():
            rows += [{"cat": g, "stage": s}] * n
        pack = acp.ChartPack(pd.DataFrame(rows), self.p("out_zero"), {}, ["png"],
                             top_n=6, min_n=3)
        pack.correspondence("cat", "stage")
        self.assertEqual(pack.manifest, [])
        self.assertEqual(len(pack.skipped), 1, pack.skipped)
        self.assertIn("惰性", pack.skipped[0]["reason"])
        self.assertEqual(pack.errors, 0)

    def test_healthy_table_still_plots(self):
        """The guard must not swallow a table that really has two dimensions."""
        import pandas as pd
        import auto_chart_pack as acp
        cells = {("g1", "s1"): 34, ("g1", "s2"): 6, ("g1", "s3"): 5,
                 ("g2", "s1"): 7, ("g2", "s2"): 31, ("g2", "s3"): 9,
                 ("g3", "s1"): 6, ("g3", "s2"): 8, ("g3", "s3"): 33}
        rows = []
        for (g, s), n in cells.items():
            rows += [{"cat": g, "stage": s}] * n
        pack = acp.ChartPack(pd.DataFrame(rows), self.p("out2"), {},
                             ["png"], top_n=6, min_n=3)
        pack.correspondence("cat", "stage")
        self.assertEqual(len(pack.manifest), 1, pack.skipped)
        self.assertEqual(pack.manifest[0]["status"], "ok")
        self.assertEqual(pack.errors, 0)
        png = os.path.join(pack.out_dir, pack.manifest[0]["png"])
        self.assertTrue(os.path.isfile(png), png)

    def test_failed_save_is_recorded_and_does_not_raise(self):
        """A drawing failure becomes an error row instead of ending the pack."""
        import contextlib
        import io
        from unittest import mock
        import auto_chart_pack as acp

        pack = self.pack(self.p("out3"))
        fig = self.figure()
        buf = io.StringIO()
        with mock.patch.object(acp, "save_fig", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(buf):
            pack.save(fig, "probe", "G 附录", "绘图失败会中断整包吗？",
                      "bar", ["cat"], n=10)
        self.assertEqual(len(pack.manifest), 1)
        self.assertTrue(pack.manifest[0]["status"].startswith("error"),
                        pack.manifest[0]["status"])
        self.assertIn("boom", pack.manifest[0]["status"])
        self.assertEqual(pack.errors, 1)
        self.assertIn("boom", buf.getvalue())

    @staticmethod
    def figure():
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(["a", "b", "c"], [3, 5, 2])
        return fig


if __name__ == "__main__":
    unittest.main()
