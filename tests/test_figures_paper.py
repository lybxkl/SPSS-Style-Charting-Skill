#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for figure composition (B1), paper figures (B2) and QA type checks (B3).

Offline and dependency-light: stdlib ``unittest``, synthetic data only, and the
Agg backend so nothing opens a window.
"""
import contextlib
import io
import json
import os
import sys
import unittest
import warnings

import matplotlib

matplotlib.use("Agg")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import (TempCase, run, write_csv, read_csv, make_png,
                        make_figure_pdf)  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402

import pubfig as pf  # noqa: E402  (path set up by _helpers)
import paper_figures as paper  # noqa: E402
import qa_outputs as qa  # noqa: E402

MANIFEST_V2 = ["id", "question", "chart_type", "variables", "n", "n_scope",
               "png", "pdf", "caption", "dpi", "px_width", "model_id",
               "data_hash", "tiff", "note", "section", "status", "palette"]
WIDTH_CM = 15.0


def panel_bar(ax):
    pf.bar_counts(ax, ["甲", "乙", "丙"], [3, 5, 2])


def panel_stack(ax):
    pf.stacked_bar(ax, ["2019", "2020"], [[4, 5], [6, 5]], ["侦查", "起诉"],
                   normalize=True)


def panel_text(ax, size=6.0):
    ax.plot([0, 1], [0, 1])
    ax.text(0.5, 0.5, "6 pt 样本", fontsize=size, ha="center")


def make_pdf(path, fontsize=8.5, width_cm=15.0, height_cm=6.0, text="样本构成"):
    """A single-axes PDF whose text is one known size (what qa_outputs reads)."""
    pf.set_style(width_cm)
    fig, ax = plt.subplots(figsize=(width_cm * pf.CM, height_cm * pf.CM))
    ax.set_axis_off()
    ax.text(0.5, 0.5, text, fontsize=fontsize, ha="center", va="center")
    fig.savefig(path, facecolor="white")
    plt.close(fig)


def make_bitmap_pdf(path, width_cm=15.0, height_cm=9.0, px_width=60):
    """A PDF that is nothing but a raster image: no text layer, no spans.

    ``px_width=3543`` at 15 cm is the real 600 dpi manuscript case; the default
    is a small blurred bitmap (low dpi) for the defect case.
    """
    import numpy as np
    pf.set_style(width_cm)
    rows = max(8, int(px_width * height_cm / width_cm))
    canvas = np.zeros((rows, px_width), dtype=float)
    canvas[:, :] = np.linspace(0.15, 0.85, px_width)[None, :]
    fig, ax = plt.subplots(figsize=(width_cm * pf.CM, height_cm * pf.CM))
    ax.set_axis_off()
    ax.imshow(canvas, cmap="Blues", aspect="auto", interpolation="nearest")
    fig.savefig(path, facecolor="white")
    plt.close(fig)




class BoldFaceTest(unittest.TestCase):
    """A family without a bold face must be reported, not silently downgraded."""

    def test_missing_bold_face_is_reported_on_stderr(self):
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            pf.check_cjk_font("SimSun")
        if not pf.has_bold_face("SimSun"):
            self.assertIn("没有 bold 字重", buffer.getvalue())
        else:
            self.assertEqual(buffer.getvalue(), "")

    def test_a_present_font_is_not_reported_as_missing(self):
        self.assertIsNone(pf.resolve_cjk_font("SimSun")[1])

class ComposeFigureCase(TempCase):
    """B1: panels assembled on one computed canvas."""

    def test_panel_sizes_match_the_usable_grid(self):
        pf.set_style(WIDTH_CM)
        res = pf.compose_figure(
            [{"draw": panel_bar}, {"draw": panel_stack},
             {"draw": panel_bar}, {"draw": panel_stack}],
            nrows=2, ncols=2, width_cm=WIDTH_CM, height_cm=11.0)
        try:
            pars = res["fig"].subplotpars
            usable_w = (float(pars.right) - float(pars.left)) * WIDTH_CM
            usable_h = (float(pars.top) - float(pars.bottom)) * 11.0
            expected_w = usable_w / (2 + float(pars.wspace))
            expected_h = usable_h / (2 + float(pars.hspace))
            self.assertEqual(len(res["panel_sizes_cm"]), 4)
            for width, height in res["panel_sizes_cm"]:
                self.assertAlmostEqual(width, expected_w, delta=0.02 * expected_w)
                self.assertAlmostEqual(height, expected_h, delta=0.02 * expected_h)
            self.assertAlmostEqual(res["width_cm"], WIDTH_CM, places=2)
            self.assertAlmostEqual(res["height_cm"], 11.0, places=2)
            self.assertEqual((res["nrows"], res["ncols"]), (2, 2))
        finally:
            plt.close(res["fig"])

    def test_min_fontsize_catches_an_explicit_6pt_label(self):
        pf.set_style(WIDTH_CM)
        res = pf.compose_figure([{"draw": lambda ax: panel_text(ax, 6.0)}],
                                nrows=1, ncols=1, width_cm=WIDTH_CM, height_cm=6.0)
        try:
            self.assertLess(res["min_fontsize_pt"], 6.2)
            self.assertAlmostEqual(res["min_fontsize_pt"], 6.0, delta=0.05)
        finally:
            plt.close(res["fig"])

    def test_default_fontsize_is_above_the_qa_floor(self):
        pf.set_style(WIDTH_CM)
        res = pf.compose_figure([{"draw": panel_bar, "label": "(a)",
                                  "title": "分罪名"}],
                                nrows=1, ncols=1, width_cm=WIDTH_CM, height_cm=6.0)
        try:
            self.assertGreaterEqual(res["min_fontsize_pt"], 7.2)
        finally:
            plt.close(res["fig"])

    def test_writes_three_formats_at_600_dpi(self):
        pf.set_style(WIDTH_CM)
        res = pf.compose_figure([{"draw": panel_bar}, {"draw": panel_stack}],
                                out_dir=self.p("figs"), name="Figure1",
                                nrows=1, ncols=2, width_cm=WIDTH_CM, height_cm=7.5)
        try:
            self.assertEqual(len(res["paths"]), 3)
            suffixes = sorted(os.path.splitext(p)[1] for p in res["paths"])
            self.assertEqual(suffixes, [".pdf", ".png", ".tiff"])
            for path in res["paths"]:
                self.assertTrue(os.path.isfile(path), path)
            from PIL import Image
            with Image.open(self.p("figs", "Figure1.png")) as image:
                self.assertEqual(image.size[0], res["px_width"])
            self.assertEqual(res["px_width"], 3543)
            measured = res["px_width"] / (WIDTH_CM * pf.CM)
            self.assertAlmostEqual(measured, 600.0, delta=1.0)
        finally:
            plt.close(res["fig"])

    def test_panels_that_do_not_fit_are_rejected(self):
        pf.set_style(WIDTH_CM)
        with self.assertRaises(ValueError):
            pf.compose_figure([{"draw": panel_bar}] * 5, nrows=2, ncols=2)
        with self.assertRaises(TypeError):
            pf.compose_figure([{"label": "(a)"}], nrows=1, ncols=1)

    def test_legend_keeps_its_room(self):
        """A stacked panel puts its legend above the axes; the canvas must grow."""
        pf.set_style(WIDTH_CM)
        res = pf.compose_figure([{"draw": panel_stack, "label": "(a)",
                                  "title": "阶段构成"}],
                                nrows=1, ncols=1, width_cm=WIDTH_CM, height_cm=6.0)
        try:
            self.assertLess(float(res["top"]), 0.95)
            self.assertIn("top=", res["note"])
            legend = res["fig"].axes[0].get_legend()
            self.assertIsNotNone(legend)
            self.assertGreater(float(legend.get_bbox_to_anchor().y0), 1.0)
        finally:
            plt.close(res["fig"])


class PaperFiguresCase(TempCase):
    """B2: paper.json -> FigureN.{png,pdf} + manifest v2."""

    def _spec(self):
        return {"figures": [
            {"id": "Figure1", "question": "样本如何构成", "n": 120,
             "height_cm": 9.0, "caption": "图1 样本构成（N=120）。",
             "sections": ["3"],
             "panels": [
                 {"chart": "bar", "label": "(a)", "title": "分罪名",
                  "data": {"x": ["甲罪", "乙罪", "丙罪"], "y": [42, 31, 25]}},
                 {"chart": "stacked_bar", "label": "(b)", "title": "阶段构成",
                  "data": {"x": ["2019", "2020"],
                           "series": [{"label": "侦查", "values": [4, 5]},
                                      {"label": "起诉", "values": [6, 5]}]}},
             ]},
            {"id": "Figure2", "question": "时间趋势", "n": 118,
             "height_cm": 6.0, "caption": "图2 趋势。N=118。",
             "panels": [
                 {"chart": "line", "label": "(a)",
                  "data": {"x": [2019, 2020, 2021], "y": [12, 15, 19],
                           "low": [10, 13, 17], "high": [14, 17, 21]}},
                 {"chart": "scatter", "label": "(b)",
                  "data": {"x": [1, 2, 3, 4], "y": [2, 1, 4, 3]}},
             ]},
        ]}

    def test_end_to_end_manifest_and_files(self):
        spec = self.p("paper.json")
        with open(spec, "w", encoding="utf-8") as handle:
            json.dump(self._spec(), handle, ensure_ascii=False)
        out = run("paper_figures.py", "--paper", spec, "--out", self.p("out"),
                  "--tiff")
        self.assertEqual(out.returncode, 0, out.stderr)
        rows = read_csv(self.p("out", "paper_figures_manifest.csv"))
        self.assertEqual([r["id"] for r in rows], ["Figure1", "Figure2"])
        for row in rows:
            self.assertEqual(row["status"], "ok")
            for column in MANIFEST_V2:
                self.assertIn(column, row)
            self.assertGreater(int(row["n"]), 0)
            self.assertEqual(row["dpi"], "600")
            self.assertGreaterEqual(int(row["px_width"]), 3500)
            self.assertTrue(row["data_hash"])
            self.assertNotIn("\\", row["png"])          # POSIX, relative paths
            self.assertFalse(os.path.isabs(row["png"]))
            for key in ("png", "pdf", "tiff"):
                path = os.path.join(self.p("out"), row[key])
                self.assertTrue(os.path.isfile(path), f"{row['id']} {key}")
        self.assertIn("N=120", rows[0]["caption"])
        self.assertIn("N=118", rows[1]["caption"])

    def test_caption_n_is_rewritten_from_the_data(self):
        """Every N= that agrees with the manifest is rewritten, not just the first."""
        spec = {"figures": [{"id": "FigA", "question": "q", "n": 2,
                             "caption": "图A N=9,999 与 N=2 两处。",
                             "panels": [{"chart": "bar",
                                         "data": {"x": ["a", "b"], "y": [1, 2]}}]}]}
        path = self.p("one.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        out = run("paper_figures.py", "--paper", path, "--out", self.p("o"))
        self.assertEqual(out.returncode, 0, out.stderr)
        row = read_csv(self.p("o", "paper_figures_manifest.csv"))[0]
        self.assertNotIn("9,999", row["caption"])
        self.assertEqual(row["caption"].count("N=2"), 2)
        self.assertEqual(int(row["n"]), 2)
        self.assertNotIn("n_conflict", row["note"])

    def test_caption_keeps_a_range_n(self):
        """A range keeps its wording: 3 111→2 713 must not collapse to N=3.

        The old producer parsed the manifest cell itself and read ``3`` out of
        ``3 111``; the checker then agreed with the corrupted value.
        """
        spec = {"figures": [{"id": "FigR", "question": "q",
                             "n": "3 111→2 713",
                             "caption": "图R 文书构成。N=3,111 份。",
                             "panels": [{"chart": "bar",
                                         "data": {"x": ["a", "b"], "y": [1, 2]}}]}]}
        path = self.p("r.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        out = run("paper_figures.py", "--paper", path, "--out", self.p("ro"))
        self.assertEqual(out.returncode, 0, out.stderr)
        row = read_csv(self.p("ro", "paper_figures_manifest.csv"))[0]
        self.assertEqual(row["n"], "3 111→2 713")
        self.assertIn("N=3 111→2 713", row["caption"])
        self.assertNotIn("N=3。", row["caption"])

    def test_manifest_columns_match_the_chart_pack(self):
        """Two producers, one manifest contract: the names must match exactly."""
        import auto_chart_pack as acp
        self.assertEqual(paper.MANIFEST_COLUMNS, acp.MANIFEST_COLUMNS)

    def test_forest_panel_reads_a_coef_csv(self):
        write_csv(self.p("coef.csv"), ["term", "beta", "ci_low", "ci_high", "n"],
                  [["amount", -0.42, -0.70, -0.14, 120],
                   ["age", -0.08, -0.20, 0.03, 120]])
        spec = {"figures": [{"id": "FigF", "question": "系数", "n": 120,
                             "palette_kind": "custom-grayscale-with-labels",
                             "caption": "图F 系数（N=120）。",
                             "panels": [{"chart": "forest",
                                         "data": {"coef": self.p("coef.csv")}}]}]}
        path = self.p("f.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        out = run("paper_figures.py", "--paper", path, "--out", self.p("fo"))
        self.assertEqual(out.returncode, 0, out.stderr)
        row = read_csv(self.p("fo", "paper_figures_manifest.csv"))[0]
        self.assertEqual(row["chart_type"], "forest")
        self.assertEqual(row["palette_kind"], "custom-grayscale-with-labels")
        self.assertEqual(row["n"], "120")

    def test_forest_accepts_a_singular_term_key(self):
        """The CSV branch reads ``term``; the array branch must not insist on ``terms``."""
        spec = {"figures": [{"id": "FigT", "question": "系数", "n": 120,
                             "caption": "图T 系数（N=120）。",
                             "panels": [{"chart": "forest",
                                         "data": {"term": ["amount", "age"],
                                                  "estimate": [0.35, 0.12],
                                                  "low": [0.10, 0.02],
                                                  "high": [0.60, 0.22],
                                                  "metric": "beta"}}]}]}
        path = self.p("term.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        out = run("paper_figures.py", "--paper", path, "--out", self.p("tm"))
        self.assertEqual(out.returncode, 0, out.stderr)
        row = read_csv(self.p("tm", "paper_figures_manifest.csv"))[0]
        self.assertEqual(row["chart_type"], "forest")
        self.assertEqual(row["status"], "ok")
        self.assertTrue(os.path.isfile(os.path.join(self.p("tm"), row["png"])))

    def test_missing_n_is_recorded_as_na_not_invented(self):
        """No declared N means NA -- never the row count of the panel data."""
        spec = {"figures": [
            {"id": "FigN", "question": "q", "n": 120, "caption": "图N（N=120）。",
             "panels": [{"chart": "bar", "data": {"x": ["a", "b"], "y": [1, 2]}}]},
            {"id": "FigNoN", "question": "q", "caption": "图无 N。",
             "panels": [{"chart": "bar",
                         "data": {"x": ["a", "b", "c"], "y": [1, 2, 3]}}]},
        ]}
        path = self.p("non.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        out = run("paper_figures.py", "--paper", path, "--out", self.p("no"))
        self.assertEqual(out.returncode, 0, out.stderr)
        rows = read_csv(self.p("no", "paper_figures_manifest.csv"))
        self.assertEqual(rows[0]["n"], "120")
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[1]["n"], "NA")
        self.assertTrue(rows[1]["status"].startswith("skipped"), rows[1]["status"])
        self.assertIn("n_missing", rows[1]["note"])
        self.assertTrue(os.path.isfile(os.path.join(self.p("no"), rows[1]["png"])))

    def test_n_auto_reads_the_analysis_rows_and_says_so(self):
        """n='auto' is the only sanctioned inference, and it must leave a trace."""
        data = self.p("analysis.csv")
        write_csv(data, ["a", "b"], [[1, 2]] * 37)
        spec = {"figures": [{"id": "FigAuto", "question": "q", "n": "auto",
                             "n_scope": "sample", "caption": "图（N=0）。",
                             "panels": [{"chart": "bar",
                                         "data": {"x": ["a", "b"], "y": [1, 2]}}]}]}
        path = self.p("auto.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        out = run("paper_figures.py", "--paper", path, "--data", data,
                  "--out", self.p("au"))
        self.assertEqual(out.returncode, 0, out.stderr)
        row = read_csv(self.p("au", "paper_figures_manifest.csv"))[0]
        self.assertEqual(row["n"], "37")
        self.assertIn("N=37", row["caption"])
        self.assertIn("n_from=data rows", row["note"])

    def test_n_auto_without_data_is_an_error_not_a_guess(self):
        spec = {"figures": [{"id": "FigAuto2", "question": "q", "n": "auto",
                             "caption": "图（N=0）。",
                             "panels": [{"chart": "bar",
                                         "data": {"x": ["a"], "y": [1]}}]}]}
        path = self.p("auto2.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        out = run("paper_figures.py", "--paper", path, "--out", self.p("au2"))
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("no analysis data was given", out.stderr)

    def test_second_different_n_is_kept_and_noted(self):
        """Only the first N= belongs to the figure; a different second one stays."""
        spec = {"figures": [{"id": "FigTwo", "question": "q", "n": 120,
                             "caption": "图（N=120）；其中有效 N=99。",
                             "panels": [{"chart": "bar",
                                         "data": {"x": ["a", "b"], "y": [1, 2]}}]}]}
        path = self.p("two.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        out = run("paper_figures.py", "--paper", path, "--out", self.p("to"))
        self.assertEqual(out.returncode, 0, out.stderr)
        row = read_csv(self.p("to", "paper_figures_manifest.csv"))[0]
        self.assertIn("N=120", row["caption"])
        self.assertIn("N=99", row["caption"], "the second, different N was overwritten")
        self.assertIn("n_conflict", row["note"])
        self.assertIn("N=99", row["note"])

    def test_all_figures_failing_exits_two(self):
        """Every failure mode uses 2 (0 = success); 3 is not in the contract."""
        spec = {"figures": [{"id": "Bad", "question": "q", "n": 5,
                             "caption": "N=5",
                             "panels": [{"chart": "sunburst", "data": {}}]}]}
        path = self.p("bad.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        out = run("paper_figures.py", "--paper", path, "--out", self.p("bo"))
        self.assertEqual(out.returncode, 2, out.stderr)
        self.assertIn("unknown chart type", out.stderr)

    def test_missing_cjk_font_is_replaced_out_loud(self):
        """No SimSun must not stop a Latin-only machine, and must not be silent."""
        candidates = pf.cjk_font_candidates()
        self.assertTrue(candidates, "this machine has no CJK font to substitute")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            paper.set_style(WIDTH_CM, font_cjk="NoSuchFontXYZ")
        message = err.getvalue()
        self.assertIn("NoSuchFontXYZ", message)
        self.assertIn("已改用", message)
        self.assertIn(candidates[0], message)
        self.assertEqual(matplotlib.rcParams["font.sans-serif"][0], candidates[0])

    def test_no_cjk_font_at_all_still_raises(self):
        original = pf.cjk_font_candidates
        pf.cjk_font_candidates = lambda limit=10: []
        try:
            with self.assertRaises(RuntimeError) as caught:
                paper.set_style(WIDTH_CM, font_cjk="NoSuchFontXYZ")
            self.assertIn("NoSuchFontXYZ", str(caught.exception))
            self.assertIn("未发现中文字体", str(caught.exception))
        finally:
            pf.cjk_font_candidates = original

    def test_the_cli_exits_two_when_the_font_is_missing(self):
        spec = {"figures": [{"id": "F", "question": "q", "n": 5, "caption": "N=5",
                             "panels": [{"chart": "bar",
                                         "data": {"x": ["a"], "y": [1]}}]}]}
        path = self.p("f.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)

        def boom(*args, **kwargs):
            raise RuntimeError("中文字体 'NoSuchFontXYZ' 不存在")

        original, original_argv = paper.set_style, sys.argv
        paper.set_style = boom
        sys.argv = ["paper_figures.py", "--paper", path, "--out", self.p("fo")]
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = paper.main()
        finally:
            paper.set_style, sys.argv = original, original_argv
        self.assertEqual(code, 2)
        self.assertIn("NoSuchFontXYZ", err.getvalue())


class QaFontCase(TempCase):
    """B3: type size after placement, read from the PDF text layer."""

    def _report(self, *args):
        out = self.p("qa.json")
        proc = run("qa_outputs.py", *args, "--out", out)
        with open(out, encoding="utf-8") as handle:
            return proc, json.load(handle)

    def test_small_text_in_a_pdf_is_an_error(self):
        make_pdf(self.p("small.pdf"), fontsize=6.2)
        proc, report = self._report("--pdf", self.p("small.pdf"),
                                    "--min-fontsize", "7.2")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        pdf = report["checks"]["pdf"]
        self.assertAlmostEqual(pdf["min_fontsize"], 6.2, delta=0.05)
        self.assertAlmostEqual(pdf["min_fontsize_effective"], 6.2, delta=0.05)
        self.assertGreater(pdf["low_font_count"], 0)
        self.assertTrue(pdf["low_font"])
        self.assertIn("pt after placement", " ".join(pdf["errors"]))

    def test_large_enough_text_passes(self):
        make_pdf(self.p("ok.pdf"), fontsize=8.5)
        proc, report = self._report("--pdf", self.p("ok.pdf"),
                                    "--min-fontsize", "7.2")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(report["error_count"], 0)
        self.assertAlmostEqual(report["checks"]["pdf"]["min_fontsize"], 8.5, delta=0.05)

    def test_placement_scaling_shrinks_the_judgement(self):
        """An 8 pt label on a 20 cm page placed at 15 cm arrives at 6 pt."""
        make_pdf(self.p("wide.pdf"), fontsize=8.0, width_cm=20.0)
        proc, report = self._report("--pdf", self.p("wide.pdf"),
                                    "--min-fontsize", "7.2",
                                    "--target-width-cm", "15")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        pdf = report["checks"]["pdf"]
        self.assertAlmostEqual(pdf["min_fontsize"], 8.0, delta=0.05)
        self.assertAlmostEqual(pdf["min_fontsize_effective"], 6.0, delta=0.15)

    def test_exit_zero_downgrades_the_error(self):
        make_pdf(self.p("small.pdf"), fontsize=6.2)
        proc, report = self._report("--pdf", self.p("small.pdf"),
                                    "--min-fontsize", "7.2", "--exit-zero")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertGreater(report["error_count"], 0)

    def test_figures_directory_checks_the_pdfs_beside_the_pngs(self):
        figs = self.p("figs")
        os.makedirs(figs, exist_ok=True)
        make_pdf(os.path.join(figs, "fig2_case_structure.pdf"), fontsize=6.2)
        pf.set_style(WIDTH_CM)
        res = pf.compose_figure([{"draw": panel_bar}], out_dir=figs, name="fig1",
                                formats=("png",), nrows=1, ncols=1, width_cm=WIDTH_CM)
        plt.close(res["fig"])
        proc, report = self._report("--figures", figs, "--min-fontsize", "7.2")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        figures = report["checks"]["figures"]
        self.assertEqual(figures["pdfs"][0]["file"], "fig2_case_structure.pdf")
        self.assertGreater(figures["low_font_count"], 0)
        self.assertAlmostEqual(figures["min_fontsize"], 6.2, delta=0.05)

    def test_bitmap_figure_is_a_no_text_layer_error(self):
        """A low-dpi bitmap can justify neither its resolution nor its type."""
        png = make_png(self.p("small.png"), 600, 400)
        make_figure_pdf(self.p("raster.pdf"), png, width_cm=15.0)
        proc, report = self._report("--pdf", self.p("raster.pdf"),
                                    "--min-fontsize", "7.2")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        pdf = report["checks"]["pdf"]
        self.assertEqual(pdf["font_spans"], 0)
        self.assertIn("no_text_layer", " ".join(pdf["errors"]))
        self.assertLess(pdf["raster_figures"][0]["dpi"], 200)

    def test_manuscript_bitmap_is_a_warning_when_the_resolution_is_right(self):
        """Word->PDF manuscripts embed 600 dpi PNGs on purpose: warn, do not fail.

        The caller has to say the rasters are expected (``--allow-raster-text``);
        undeclared, the same PDF is an error (see the test below), because a
        bitmap justifies neither its font size nor its figure type.
        """
        make_bitmap_pdf(self.p("manuscript.pdf"), px_width=3543)
        proc, report = self._report("--pdf", self.p("manuscript.pdf"),
                                    "--min-fontsize", "7.2",
                                    "--target-width-cm", "15",
                                    "--allow-raster-text")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        pdf = report["checks"]["pdf"]
        self.assertEqual(pdf["errors"], [])
        message = " ".join(pdf["warnings"])
        self.assertIn("no_text_layer", message)
        self.assertIn("600 dpi", message)
        self.assertIn("source figure PDF", message)
        self.assertGreaterEqual(pdf["raster_figures"][0]["dpi"], 590)

    def test_manuscript_bitmap_without_declaring_it_is_an_error(self):
        """Same PDF, no flag: the type at the real placement size is unverified."""
        make_bitmap_pdf(self.p("manuscript_plain.pdf"), px_width=3543)
        proc, report = self._report("--pdf", self.p("manuscript_plain.pdf"),
                                    "--min-fontsize", "7.2",
                                    "--target-width-cm", "15")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        errors = " ".join(report["checks"]["pdf"]["errors"])
        self.assertIn("unverified", errors)
        self.assertIn("DOCX", errors)

    def test_flattened_figure_pdf_in_a_directory_is_an_error(self):
        """A handed-in figure PDF that lost its text layer is a delivery defect."""
        figs = self.p("flat")
        os.makedirs(figs, exist_ok=True)
        make_bitmap_pdf(os.path.join(figs, "fig1_flat.pdf"), px_width=3543)
        proc, report = self._report("--figures", figs, "--min-fontsize", "7.2")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        figures = report["checks"]["figures"]
        self.assertIn("no_text_layer", " ".join(figures["errors"]))
        self.assertIn("fig1_flat.pdf", " ".join(figures["errors"]))

    def test_allow_raster_text_downgrades_it(self):
        make_bitmap_pdf(self.p("raster2.pdf"))
        proc, report = self._report("--pdf", self.p("raster2.pdf"),
                                    "--min-fontsize", "7.2",
                                    "--allow-raster-text")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        pdf = report["checks"]["pdf"]
        self.assertEqual(pdf["errors"], [])
        self.assertIn("no_text_layer", " ".join(pdf["warnings"]))

    def test_png_only_directory_skips_the_font_check(self):
        """No PDF in the directory: the pt minimum is unverified, and it says so.

        Declaring the rasters expected (``--allow-raster-text``) is what keeps
        that honest statement a warning instead of a delivery error.
        """
        figs = self.p("pngs")
        os.makedirs(figs, exist_ok=True)
        pf.set_style(WIDTH_CM)
        res = pf.compose_figure([{"draw": panel_bar}], out_dir=figs, name="fig1",
                                formats=("png",), nrows=1, ncols=1, width_cm=WIDTH_CM)
        plt.close(res["fig"])
        proc, report = self._report("--figures", figs, "--min-fontsize", "7.2",
                                    "--allow-raster-text")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        figures = report["checks"]["figures"]
        self.assertIn("skipped", figures["font_size_check"])
        self.assertIn("no text layer", " ".join(figures["warnings"]))

    def test_png_only_directory_is_an_error_by_default(self):
        """Without the flag the same directory has no verified font size at all."""
        figs = self.p("pngsdefault")
        os.makedirs(figs, exist_ok=True)
        pf.set_style(WIDTH_CM)
        res = pf.compose_figure([{"draw": panel_bar}], out_dir=figs, name="fig1",
                                formats=("png",), nrows=1, ncols=1, width_cm=WIDTH_CM)
        plt.close(res["fig"])
        proc, report = self._report("--figures", figs, "--min-fontsize", "7.2")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertIn("no text layer",
                      " ".join(report["checks"]["figures"]["errors"]))


class QaManifestNCase(TempCase):
    """A manifest that never states N has not been checked, so it cannot pass."""

    def _manifest(self, n_values, name="m.csv"):
        header = ["id", "question", "chart_type", "variables", "n", "png", "pdf",
                  "caption"]
        # A row that names no output file is now an error of its own, so give
        # every row a real PNG and leave N as the only thing under test.
        png = make_png(self.p("fig.png"))
        rows = [[f"F{i:02d}", "q", "bar", "a", value, png, "", "注：见正文。"]
                for i, value in enumerate(n_values, start=1)]
        write_csv(self.p(name), header, rows)
        return self.p(name)

    def _report(self, path):
        out = run("qa_outputs.py", "--manifest", path, "--out", self.p("qa.json"))
        with open(self.p("qa.json"), encoding="utf-8") as handle:
            return out, json.load(handle)["checks"]["manifest"]

    def test_every_row_missing_n_is_an_error(self):
        out, manifest = self._report(self._manifest(["NA", "NA", "n/a"]))
        self.assertEqual(out.returncode, 2, out.stdout)
        self.assertEqual(manifest["n_na_count"], 3)
        self.assertEqual(manifest["n_total"], 3)
        self.assertTrue(any("没有声明样本量" in e for e in manifest["errors"]),
                        manifest["errors"])

    def test_half_missing_n_stays_a_warning(self):
        out, manifest = self._report(self._manifest(["NA", "120"]))
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertEqual(manifest["n_na_count"], 1)
        self.assertTrue(any("n=NA" in w for w in manifest["warnings"]),
                        manifest["warnings"])
        self.assertEqual(manifest["errors"], [])


class QaPaletteCase(TempCase):
    """B3: grayscale and colour-vision separability of a manifest palette."""

    def _manifest(self, palette, name="m.csv", **fields):
        rows = [{"id": "F01", "question": "q", "chart_type": "bar",
                 "variables": "a; b", "n": "10", "png": make_png(self.p("fig.png")),
                 "pdf": "", "caption": "注：N=10。", "palette": palette}]
        rows[0].update(fields)
        write_csv(self.p(name), list(rows[0]), [rows[0]])
        return self.p(name)

    def test_chart_pack_preserves_palette_purpose_in_csv(self):
        import auto_chart_pack as acp
        import pandas as pd
        pack = acp.ChartPack(pd.DataFrame({"x": range(10)}), self.p("pack"),
                             {}, ["png"], 8, 2)
        fig, ax = plt.subplots(figsize=(15/2.54, 3))
        ax.imshow([list(range(10))], cmap="Blues", aspect="auto")
        pack.save(fig, "gradient", "A", "synthetic gradient", "heatmap", ["x"], 10,
                  "Synthetic N=10", extra={"palette_kind": "sequential"})
        path = pack.write({})
        row = read_csv(path)[0]
        self.assertEqual(row["palette_kind"], "sequential")
        report = qa.check_manifest(path, strict_palette=True)
        self.assertFalse(report["palettes"][0]["pairwise_checked"])

    def test_low_grayscale_separation_is_advisory_by_default(self):
        # Close lightness is a heuristic; line styles/markers may still work.
        path = self._manifest("#5B7F62;#3E8683")
        out = run("qa_outputs.py", "--manifest", path)
        self.assertEqual(out.returncode, 0, out.stdout)
        report = json.loads(out.stdout)
        self.assertEqual(report["checks"]["manifest"]["errors"], [])
        self.assertTrue(report["checks"]["manifest"]["warnings"])
        self.assertIn("grayscale", out.stdout)
        self.assertIn("ΔL*", out.stdout)
        self.assertLess(abs(qa.lightness("#5B7F62") - qa.lightness("#3E8683")), 10.0)

    def test_strict_palette_is_explicit_opt_in(self):
        path = self._manifest("#5B7F62;#3E8683")
        out = run("qa_outputs.py", "--manifest", path, "--strict-palette")
        self.assertEqual(out.returncode, 2, out.stdout)
        report = json.loads(out.stdout)["checks"]["manifest"]
        self.assertTrue(report["strict_palette"])
        self.assertTrue(report["errors"])

    def test_gradients_and_custom_mappings_do_not_use_discrete_pairwise_gate(self):
        for kind in ("sequential", "diverging", "cyclic", "single", "my-study-custom-map"):
            with self.subTest(kind=kind):
                path = self._manifest("#555555;#565656;#575757", palette_kind=kind)
                out = run("qa_outputs.py", "--manifest", path, "--strict-palette", "--colorblind")
                self.assertEqual(out.returncode, 0, out.stdout)
                report = json.loads(out.stdout)["checks"]["manifest"]
                self.assertFalse(report["palettes"][0]["pairwise_checked"])
                self.assertFalse(report["palettes"][0]["strict"])
                self.assertEqual(report["palette_unchecked"], 1)
                self.assertIn("mapping", report["palette_note"])

    def test_colorblind_diagnostics_can_run_without_grayscale_heuristic(self):
        path = self._manifest("#D62728;#2CA02C")
        out = run("qa_outputs.py", "--manifest", path, "--no-graycheck", "--colorblind")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("colour blind", out.stdout)
        self.assertFalse(json.loads(out.stdout)["checks"]["manifest"]["graycheck"])

    def test_palette_advice_does_not_downgrade_invalid_sample_size(self):
        path = self._manifest("#555555;#565656", n="invalid")
        out = run("qa_outputs.py", "--manifest", path)
        self.assertEqual(out.returncode, 2, out.stdout)
        self.assertTrue(json.loads(out.stdout)["checks"]["manifest"]["errors"])

    def test_custom_nine_colour_chart_has_no_default_eight_colour_limit(self):
        colors = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#F0E442",
                  "#56B4E9", "#E69F00", "#111111", "#999999"]
        fig, ax = plt.subplots()
        try:
            pf.stacked_bar(ax, ["A", "B"], [[1, 2]]*9,
                           [f"g{i}" for i in range(9)], colors=colors)
            used = list(dict.fromkeys(matplotlib.colors.to_hex(p.get_facecolor()).upper() for p in ax.patches))
            self.assertEqual(used, colors)
        finally:
            plt.close(fig)
        report = qa.check_palette(colors)
        self.assertEqual(report["errors"], [])

    def test_no_graycheck_disables_it(self):
        path = self._manifest("#5B7F62;#3E8683")
        out = run("qa_outputs.py", "--manifest", path, "--no-graycheck")
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_separated_palette_passes(self):
        path = self._manifest("#2F5C8A;#B45F3C")
        out = run("qa_outputs.py", "--manifest", path)
        self.assertEqual(out.returncode, 0, out.stdout)

    def test_colorblind_simulation_warns_only(self):
        # Red vs green: ΔL* ≈ 11 (fine in print) but ΔE ≈ 7 under deuteranopia.
        path = self._manifest("#D62728;#2CA02C")
        out = run("qa_outputs.py", "--manifest", path, "--colorblind")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("colour blind", out.stdout)

    def test_house_palette_is_grayscale_separable(self):
        """The eight series colours are a 10.6 L* ladder: no two may be closer.

        This is the guard for the future: a "prettier" palette that puts two
        series on the same lightness fails here before it reaches a print.
        """
        self.assertEqual(len(pf.CATEGORICAL), 8)
        self.assertEqual(len(set(pf.CATEGORICAL)), 8, "eight series, eight colours")
        ladder = sorted((qa.lightness(hex_value), name)
                        for name, hex_value in zip(pf.CATEGORICAL, pf.CATEGORICAL))
        gaps = [b[0] - a[0] for a, b in zip(ladder, ladder[1:])]
        self.assertGreaterEqual(min(gaps), 10.0,
                                f"grayscale ladder collapsed: {sorted(ladder)}")
        # INK/GRID are structure (text, rules, gridlines) and stay outside it.
        self.assertLess(qa.lightness(pf.INK), ladder[0][0])
        self.assertGreater(qa.lightness(pf.GRID), ladder[-1][0])
        for hex_value in pf.CATEGORICAL + [pf.INK, pf.GRID]:
            self.assertRegex(hex_value, r"^#[0-9A-F]{6}$", hex_value)

    def test_eight_series_get_eight_colours(self):
        """The cycle used to wrap at six colours; series 7 and 8 repeated 1 and 2."""
        pf.set_style(WIDTH_CM)
        fig, ax = plt.subplots(figsize=(WIDTH_CM * pf.CM, 5))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            pf.stacked_bar(ax, ["2019", "2020"], [[1, 2]] * 8,
                           [f"类别{i}" for i in range(8)], normalize=True)
        used = [m.get_facecolor() for m in ax.patches]
        colours = []
        for rgba in used:
            hex_value = matplotlib.colors.to_hex(rgba).upper()
            if hex_value not in colours:
                colours.append(hex_value)
        plt.close(fig)
        self.assertEqual(len(colours), 8, f"8 series drew {colours}")
        self.assertEqual(colours, [c.upper() for c in pf.CATEGORICAL])
        report = qa.check_palette(colours)
        self.assertEqual(report["errors"], [])
        self.assertGreaterEqual(float(report["min_delta_l"]), 10.0)

    def test_palette_shorter_than_the_series_count_warns(self):
        """Declaring 8 colours for 9 series is the silent-repeat case: say so."""
        rows = [{"id": "F09", "question": "q", "chart_type": "stacked bar",
                 "variables": "a", "n": "10", "png": make_png(self.p("nine.png")),
                 "pdf": "", "caption": "注：N=10。", "n_series": "9",
                 "palette": "|".join(pf.CATEGORICAL)}]
        write_csv(self.p("nine.csv"), list(rows[0]), [rows[0]])
        out = run("qa_outputs.py", "--manifest", self.p("nine.csv"),
                  "--out", self.p("nine.json"))
        self.assertEqual(out.returncode, 0, out.stdout)
        with open(self.p("nine.json"), encoding="utf-8") as handle:
            report = json.load(handle)
        messages = " ".join(report["checks"]["manifest"]["warnings"])
        self.assertIn("share a colour", messages)
        self.assertIn("9 series", messages)

    def test_categorical_cycle_passes_the_gray_check(self):
        """CATEGORICAL is what the charts draw from, so qa must accept it."""
        self.assertGreaterEqual(len(pf.CATEGORICAL), 8)
        report = qa.check_palette(list(pf.CATEGORICAL))
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])
        self.assertGreaterEqual(float(report["min_delta_l"]), 10.0)

    def test_manifest_palette_column_is_read(self):
        """A pipe-separated palette cell must reach _check_palette, not be ignored."""
        path = self._manifest("|".join(pf.CATEGORICAL))
        out = run("qa_outputs.py", "--manifest", path, "--out", self.p("qa.json"))
        self.assertEqual(out.returncode, 0, out.stdout)
        with open(self.p("qa.json"), encoding="utf-8") as handle:
            report = json.load(handle)
        manifest = report["checks"]["manifest"]
        self.assertEqual(manifest["palette_unchecked"], 0)
        self.assertEqual(len(manifest["palettes"]), 1)
        self.assertTrue(manifest["palettes"][0]["declared"])
        self.assertGreaterEqual(float(manifest["palettes"][0]["min_delta_l"]), 10.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
