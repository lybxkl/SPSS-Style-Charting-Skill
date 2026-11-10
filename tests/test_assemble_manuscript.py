#!/usr/bin/env python3
"""Stage 6: the manuscript has to come out of a script, not out of retyping.

These cases pin the properties that make a Word manuscript acceptable to a journal
editor — rules, unbreakable rows, a repeating header row, real East Asian fonts,
indent measured in characters, a caption that cannot be separated from its
figure — plus the refusals: a placeholder with no value, a missing column, a PDF
where Word needs a PNG, a figure wider than the text column.
"""

from __future__ import annotations

import csv
import json
import os
import unittest
import zipfile

from _helpers import TempCase, make_png, run, write_csv

SPEC_MIN = {
    "blocks": [
        {"type": "title", "text": "题目"},
        {"type": "heading", "level": 1, "text": "一、引言"},
        {"type": "para", "text": "正文。"},
    ]
}


class AssemblerCase(TempCase):
    def spec(self, blocks, name="spec.json", numbers=None, style=None, page=None):
        spec = {"blocks": blocks}
        if style:
            spec["style"] = style
        if page:
            spec["page"] = page
        path = self.p(name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False)
        argv = ["--spec", path, "--out", self.p("out", "manuscript.docx")]
        if numbers is not None:
            numbers_path = self.p("numbers.csv")
            with open(numbers_path, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["key", "value"])
                for key, value in numbers.items():
                    writer.writerow([key, value])
            argv += ["--numbers", numbers_path]
        return argv

    def table_csv(self, name="t.csv"):
        return write_csv(
            self.p(name),
            ["charge", "n", "pct"],
            [["水生资源", 976, 33.9], ["森林资源", 713, 24.8]],
        )


class TestBuild(AssemblerCase):
    def test_minimal_manuscript_builds(self):
        result = run("assemble_manuscript.py", *self.spec(SPEC_MIN["blocks"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(self.p("out", "manuscript.docx")))

    def test_three_line_table_and_unbreakable_rows(self):
        csv_path = self.table_csv()
        blocks = [
            {"type": "table", "csv": csv_path, "caption": "罪名结构", "n": "1,689",
             "columns": [{"col": "charge", "label": "罪名"},
                         {"col": "n", "label": "文书数", "fmt": "{:.0f}"},
                         {"col": "pct", "label": "占比（%）", "fmt": "{:.1f}"}]},
        ]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn("<w:tblBorders>", xml)
        self.assertIn('<w:top w:val="single" w:sz="12"', xml)  # 1.5 pt top rule
        self.assertIn('<w:bottom w:val="single" w:sz="12"', xml)  # 1.5 pt bottom rule
        self.assertNotIn('<w:insideV w:val="single"', xml)  # no vertical lines
        self.assertIn('<w:bottom w:val="single" w:sz="6"', xml)  # 0.75 pt header rule
        self.assertIn("cantSplit", xml)
        self.assertIn("tblHeader", xml)
        self.assertIn("表 1", xml)
        self.assertIn("N=1,689", xml)

    def test_caption_n_comes_from_dollars_and_numbers_file(self):
        csv_path = self.table_csv()
        blocks = [
            {"type": "table", "csv": csv_path, "caption": "罪名结构", "n": "{n_analysis}",
             "columns": [{"col": "charge"}, {"col": "n"}]},
        ]
        argv = self.spec(blocks, numbers={"n_analysis": "2,713"})
        result = run("assemble_manuscript.py", *argv)
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(self.p("out", "manuscript_numbers.csv"), encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual([r["key"] for r in rows], ["table1_n"])
        self.assertEqual(rows[0]["value"], "2,713")

    def test_unknown_placeholder_is_fatal(self):
        blocks = [{"type": "para", "text": "样本为 {n_missing} 份。"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("n_missing", result.stderr)
        self.assertIn("numbers.csv", result.stderr)

    def test_missing_column_lists_what_is_available(self):
        csv_path = self.table_csv()
        blocks = [{"type": "table", "csv": csv_path, "caption": "x",
                   "columns": [{"col": "no_such_column"}]}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("no_such_column", result.stderr)
        self.assertIn("charge", result.stderr)

    def test_missing_csv_is_fatal(self):
        blocks = [{"type": "table", "csv": "nope.csv", "caption": "x"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("nope.csv", result.stderr)

    def test_empty_table_is_fatal_not_an_empty_table(self):
        path = write_csv(self.p("empty.csv"), ["a", "b"], [])
        blocks = [{"type": "table", "csv": path, "caption": "x"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("no rows", result.stderr)


class TestFigure(AssemblerCase):
    def test_figure_is_embedded_at_the_configured_width(self):
        png = make_png(self.p("fig.png"), 3543, 2000)
        blocks = [{"type": "figure", "png": png, "caption": "结构", "n": "2,713",
                   "note": "注：横轴为类别。"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn("graphicData", xml)
        # 14.66 cm of text column at 21 cm page / 3.17 cm margins.
        self.assertRegex(xml, r'cx="5\d{6}"')
        with open(self.p("out", "figure_map.json"), encoding="utf-8") as fh:
            mapping = json.load(fh)
        self.assertEqual(mapping[0]["tag"], "图1")
        self.assertEqual(mapping[0]["title"], "结构")
        self.assertTrue(mapping[0]["image"].endswith("fig.png"))

    def test_pdf_figure_is_refused_with_a_reason(self):
        pdf = self.p("fig.pdf")
        with open(pdf, "wb") as fh:
            fh.write(b"%PDF-1.4\n")
        blocks = [{"type": "figure", "png": pdf, "caption": "结构"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot embed", result.stderr)

    def test_figure_wider_than_the_column_is_refused(self):
        png = make_png(self.p("fig.png"), 3543, 2000)
        blocks = [{"type": "figure", "png": png, "caption": "结构", "width_cm": 18}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("14.66", result.stderr)

    def test_low_resolution_figure_warns_but_builds(self):
        png = make_png(self.p("small.png"), 600, 400)
        blocks = [{"type": "figure", "png": png, "caption": "结构"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("600 dpi floor", result.stderr)


class TestSpecSurface(AssemblerCase):
    def test_unknown_block_type_is_named(self):
        result = run("assemble_manuscript.py", *self.spec([{"type": "chart"}]))
        self.assertEqual(result.returncode, 2)
        self.assertIn("chart", result.stderr)

    def test_empty_blocks_is_fatal(self):
        result = run("assemble_manuscript.py", *self.spec([]))
        self.assertEqual(result.returncode, 2)
        self.assertIn("non-empty", result.stderr)

    def test_bad_json_is_fatal(self):
        path = self.p("bad.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        result = run("assemble_manuscript.py", "--spec", path,
                     "--out", self.p("out", "m.docx"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("valid JSON", result.stderr)

    def test_duplicate_number_keys_are_fatal(self):
        path = self.p("dup.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("key,value\nn,1\nn,2\n")
        blocks = [{"type": "para", "text": "{n}"}]
        spec_path = self.p("spec.json")
        with open(spec_path, "w", encoding="utf-8") as fh:
            json.dump({"blocks": blocks}, fh)
        result = run("assemble_manuscript.py", "--spec", spec_path,
                     "--out", self.p("out", "m.docx"), "--numbers", path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("repeats key", result.stderr)

    def test_dry_run_writes_nothing(self):
        argv = self.spec(SPEC_MIN["blocks"]) + ["--dry-run"]
        result = run("assemble_manuscript.py", *argv)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(os.path.exists(self.p("out", "manuscript.docx")))
        self.assertIn("dry run", result.stdout)

    def test_east_asian_font_is_written_not_only_latin(self):
        result = run("assemble_manuscript.py", *self.spec(SPEC_MIN["blocks"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn("w:eastAsia", xml)
        self.assertIn("宋体", xml)

    def test_first_line_indent_is_in_characters(self):
        result = run("assemble_manuscript.py", *self.spec(SPEC_MIN["blocks"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn('w:firstLineChars="200"', xml)


if __name__ == "__main__":
    unittest.main(verbosity=2)