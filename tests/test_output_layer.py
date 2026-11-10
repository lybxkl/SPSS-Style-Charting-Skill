# -*- coding: utf-8 -*-
"""Tests for the delivery layer: qa_outputs.py and export_pdf_hires.py.

Each test pins one defect found in the audit:
- D-02: resolution was judged by pixel width (3000 px = 508 dpi at 15 cm)
- key column contract: a missing key was a warning, so duplicate detection
  silently disappeared
- N contract: funnel charts (N = corpus size) were rejected, forcing callers to
  fake N = min(n, rows)
- caption N: "N = 2 713" (spaces) never matched
- D-01: replace_image left the old 200 dpi bitmap in /Resources
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import (TempCase, make_docx, make_figure_pdf, make_png,  # noqa: E402
                      make_text_pdf, read_csv, run, write_csv)


class QAKeyColumnTest(TempCase):
    def test_rel_path_is_found_automatically(self):
        data = write_csv(self.p("data.csv"), ["rel_path", "in_analysis"],
                         [["a.pdf", 1], ["b.pdf", 1]])
        proc = run("qa_outputs.py", "--data", data)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["checks"]["data"]["key"], "rel_path")
        self.assertEqual(report["checks"]["data"]["rows"], 2)

    def test_missing_key_is_an_error(self):
        data = write_csv(self.p("data.csv"), ["foo", "bar"], [[1, 2]])
        proc = run("qa_outputs.py", "--data", data)
        self.assertEqual(proc.returncode, 2)
        report = json.loads(proc.stdout)
        self.assertTrue(any("key column not found" in e
                            for e in report["checks"]["data"]["errors"]))

    def test_explicit_key_still_wins(self):
        data = write_csv(self.p("data.csv"), ["rel_path", "sample_id"],
                         [["a.pdf", "s1"], ["b.pdf", "s2"]])
        proc = run("qa_outputs.py", "--data", data, "--key", "sample_id")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(report["checks"]["data"]["key"], "sample_id")


class QAManifestTest(TempCase):
    def _manifest(self, rows):
        png = make_png(self.p("fig1.png"), 200, 100)
        header = ["id", "question", "chart_type", "variables", "n", "n_scope",
                  "png", "pdf", "caption"]
        for row in rows:
            row["png"] = png
            row["pdf"] = png
        return write_csv(self.p("chart_manifest.csv"), header, rows)

    def test_range_n_with_corpus_scope_passes(self):
        data = write_csv(self.p("d.csv"), ["rel_path"], [[f"x{i}"] for i in range(5)])
        manifest = self._manifest([{
            "id": "fig1", "question": "样本漏斗", "chart_type": "funnel",
            "variables": "stage", "n": "3 111→2 713", "n_scope": "corpus",
            "caption": "图 1 样本漏斗（N=3111→2713）"}])
        proc = run("qa_outputs.py", "--data", data, "--manifest", manifest)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        report = json.loads(proc.stdout)
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(report["checks"]["manifest"]["range_n"], ["fig1=3 111→2 713"])

    def test_sample_scope_above_rows_is_an_error(self):
        data = write_csv(self.p("d.csv"), ["rel_path"], [[f"x{i}"] for i in range(5)])
        manifest = self._manifest([{
            "id": "fig1", "question": "q", "chart_type": "bar", "variables": "v",
            "n": "100", "n_scope": "sample", "caption": "图 1 分布（N=100）"}])
        proc = run("qa_outputs.py", "--data", data, "--manifest", manifest)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("N>", proc.stdout)

    def test_caption_with_spaced_thousands_separator(self):
        data = write_csv(self.p("d.csv"), ["rel_path"], [[f"x{i}"] for i in range(3000)])
        manifest = self._manifest([{
            "id": "fig2", "question": "q", "chart_type": "bar", "variables": "v",
            "n": "2713", "caption": "图 2 分布（N = 2 713）"}])
        proc = run("qa_outputs.py", "--data", data, "--manifest", manifest)
        report = json.loads(proc.stdout)
        self.assertEqual(report["checks"]["manifest"].get("warnings"), [])

    def test_invalid_n_is_an_error(self):
        manifest = self._manifest([{
            "id": "fig3", "question": "q", "chart_type": "bar", "variables": "v",
            "n": "many", "caption": "图 3 分布"}])
        proc = run("qa_outputs.py", "--manifest", manifest)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("chart N invalid", proc.stdout)


class QAResolutionTest(TempCase):
    """D-02: resolution must be measured, not counted."""

    def test_low_dpi_pdf_is_rejected(self):
        png = make_png(self.p("small.png"), 600, 400)          # ~101 dpi at 15 cm
        pdf = make_figure_pdf(self.p("doc.pdf"), png, width_cm=15.0)
        proc = run("qa_outputs.py", "--pdf", pdf)
        self.assertEqual(proc.returncode, 2)
        report = json.loads(proc.stdout)
        self.assertLess(report["checks"]["pdf"]["dpi_min"], 200)
        self.assertTrue(any("dpi" in e for e in report["checks"]["pdf"]["errors"]))

    def test_high_dpi_pdf_passes(self):
        png = make_png(self.p("big.png"), 3543, 2000)          # 600 dpi at 15 cm
        pdf = make_figure_pdf(self.p("doc.pdf"), png, width_cm=15.0)
        proc = run("qa_outputs.py", "--pdf", pdf)
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:])
        report = json.loads(proc.stdout)
        self.assertGreaterEqual(report["checks"]["pdf"]["dpi_min"], 590)

    def test_figures_dir_checks_dpi(self):
        os.makedirs(self.p("figs"), exist_ok=True)
        make_png(self.p("figs", "fig1.png"), 600, 400)
        proc = run("qa_outputs.py", "--figures", self.p("figs"))
        self.assertEqual(proc.returncode, 2)
        report = json.loads(proc.stdout)
        self.assertEqual(report["checks"]["figures"]["count"], 1)
        self.assertLess(report["checks"]["figures"]["files"][0]["dpi_at_width"], 200)

    def test_figures_dir_accepts_exact_600dpi(self):
        """3543 px at 15 cm is 599.9 dpi -- a rounding artefact, not low-res.

        Regression: the real pack's 44 figures were all exported at exactly
        3543 px and ``--figures`` rejected every one of them with the message
        ``44 figure(s) below 600 dpi ... (600dpi)``.
        """
        os.makedirs(self.p("figs"), exist_ok=True)
        make_png(self.p("figs", "fig1.png"), 3543, 2000)
        proc = run("qa_outputs.py", "--figures", self.p("figs"), "--min-dpi", "600")
        self.assertEqual(proc.returncode, 0, proc.stdout[-800:])
        report = json.loads(proc.stdout)
        self.assertEqual(report["checks"]["figures"]["errors"], [])
        self.assertGreater(report["checks"]["figures"]["files"][0]["dpi_at_width"], 599)

    def test_exit_zero_flag_downgrades(self):
        png = make_png(self.p("small.png"), 600, 400)
        pdf = make_figure_pdf(self.p("doc.pdf"), png, width_cm=15.0)
        proc = run("qa_outputs.py", "--pdf", pdf, "--exit-zero")
        self.assertEqual(proc.returncode, 0)


@unittest.skipUnless(sys.platform == "win32", "Word COM is Windows-only")
class ExportHiresTest(TempCase):
    """D-01: the previous bitmap must not survive the replacement."""

    def test_backfill_removes_old_bitmap(self):
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            self.skipTest("pywin32 missing")
        png = make_png(self.p("big.png"), 3543, 2000)
        docx = make_docx(self.p("m.docx"), ["图 1 测试图", "正文"], image=png, width_cm=15.0)
        fmap = self.p("map.json")
        with open(fmap, "w", encoding="utf-8") as fh:
            json.dump({"图 1": {"title": "测试图", "image": png}}, fh, ensure_ascii=False)
        out = self.p("out.pdf")
        proc = run("export_pdf_hires.py", "--docx", docx, "--out-pdf", out,
                   "--figure-map", fmap, timeout=600)
        if proc.returncode == 2 and "Word export failed" in proc.stderr:
            self.skipTest("Microsoft Word unavailable")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout[-800:])
        import fitz
        doc = fitz.open(out)
        unique = set()
        for page in doc:
            for im in page.get_images(full=True):
                unique.add(im[0])
            if hasattr(page, "get_contents"):
                page.get_contents()  # force content parse
        doc.close()
        self.assertEqual(len(unique), 1, "old 200 dpi bitmap still in /Resources")
        with open(self.p("out_export_report.json"), encoding="utf-8") as fh:
            report = json.load(fh)
        self.assertEqual(len(report["figures_replaced"]), 1)
        self.assertGreaterEqual(report["images"][0]["dpi"], 590)


if __name__ == "__main__":
    unittest.main(verbosity=2)
