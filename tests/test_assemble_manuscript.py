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
    def test_scalar_margin_is_accepted(self):
        """`"margin_cm": 3.17` is natural; it must not crash on .get()."""
        spec = {"page": {"size": "A4", "margin_cm": 3.0},
                "blocks": [{"type": "para", "text": "正文。"}]}
        path = self.p("m_scalar.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False)
        proc = run("assemble_manuscript.py", "--spec", path,
                   "--out", self.p("scalar.docx"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        from docx import Document
        doc = Document(self.p("scalar.docx"))
        self.assertAlmostEqual(doc.sections[0].left_margin.cm, 3.0, places=1)

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

    def test_headings_and_table_captions_keep_with_next(self):
        # a heading or a table caption must never strand at a page bottom
        csv_path = self.table_csv()
        blocks = [
            {"type": "heading", "level": 1, "text": "一、引言"},
            {"type": "table", "csv": csv_path, "caption": "罪名结构", "n": "1,689",
             "columns": [{"col": "charge", "label": "罪名"},
                         {"col": "n", "label": "文书数", "fmt": "{:.0f}"},
                         {"col": "pct", "label": "占比（%）", "fmt": "{:.1f}"}]},
        ]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        from docx import Document
        doc = Document(self.p("out", "manuscript.docx"))
        heading = next(p for p in doc.paragraphs
                       if p.text.strip() == "一、引言")
        self.assertTrue(heading.paragraph_format.keep_with_next)
        caption = next(p for p in doc.paragraphs if p.text.startswith("表 1"))
        self.assertTrue(caption.paragraph_format.keep_with_next)

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


class TestCrossReferences(AssemblerCase):
    def doc_xml(self, blocks):
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            return zf.read("word/document.xml").decode("utf-8")

    def test_xref_becomes_ref_field_with_cached_text(self):
        csv_path = self.table_csv()
        blocks = [
            {"type": "para", "text": "结果见[@tab:1]，细节见[@tab:2]。"},
            {"type": "table", "csv": csv_path, "caption": "其一"},
            {"type": "table", "csv": csv_path, "caption": "其二"},
        ]
        xml = self.doc_xml(blocks)
        self.assertIn('<w:instrText xml:space="preserve"> REF _RefTab1 \\h </w:instrText>', xml)
        self.assertIn('<w:instrText xml:space="preserve"> REF _RefTab2 \\h </w:instrText>', xml)
        # cached display text is a real run, so text readers see 表 1 before F9
        self.assertIn("表1", xml)
        self.assertIn('w:name="_RefTab1"', xml)
        self.assertIn('w:name="_RefTab2"', xml)

    def test_forward_reference_before_the_table_works(self):
        csv_path = self.table_csv()
        blocks = [
            {"type": "para", "text": "先说结论（[@fig:1]）。"},
            {"type": "figure", "png": make_png(self.p("f.png"), 3543, 2000),
             "caption": "主图"},
        ]
        xml = self.doc_xml(blocks)
        self.assertIn('<w:instrText xml:space="preserve"> REF _RefFig1 \\h </w:instrText>', xml)
        self.assertIn('w:name="_RefFig1"', xml)

    def test_xref_to_missing_number_is_fatal(self):
        csv_path = self.table_csv()
        blocks = [
            {"type": "para", "text": "见[@tab:9]。"},
            {"type": "table", "csv": csv_path, "caption": "唯一"},
        ]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("[@tab:9]", result.stderr)
        self.assertIn("表9", result.stderr)

    def test_duplicate_explicit_table_numbers_are_fatal(self):
        csv_path = self.table_csv()
        blocks = [
            {"type": "table", "csv": csv_path, "caption": "a", "number": 3},
            {"type": "table", "csv": csv_path, "caption": "b", "number": 3},
        ]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("used twice", result.stderr)

    def test_explicit_number_drives_bookmark_and_caption(self):
        csv_path = self.table_csv()
        blocks = [
            {"type": "para", "text": "见[@tab:5]。"},
            {"type": "table", "csv": csv_path, "caption": "编号表", "number": 5},
        ]
        xml = self.doc_xml(blocks)
        self.assertIn('w:name="_RefTab5"', xml)
        self.assertIn("表5", xml)

    def test_xref_after_placeholder_resolution(self):
        csv_path = self.table_csv()
        blocks = [
            {"type": "para", "text": "样本 {n_total} 人，见[@tab:1]。"},
            {"type": "table", "csv": csv_path, "caption": "t"},
        ]
        argv = self.spec(blocks, numbers={"n_total": "1,689"})
        result = run("assemble_manuscript.py", *argv)
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn("1,689", xml)
        self.assertIn('<w:instrText xml:space="preserve"> REF _RefTab1 \\h </w:instrText>', xml)


class TestReferences(AssemblerCase):
    def refs_csv(self, rows, name="refs.csv"):
        # each entry is ONE cell; csv.writer.writerow(string) would write
        # every character as its own cell
        return write_csv(self.p(name), ["text"], [[r] for r in rows])

    def test_references_typeset_with_hanging_indent_and_numbering(self):
        csv_path = self.refs_csv([
            "作者A. 标题一[J]. 期刊, 2020, 1(1): 1-10.",
            "作者B. 标题二[M]. 出版社, 2019.",
        ])
        blocks = [{"type": "references", "title": "参考文献", "csv": csv_path}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn('w:hangingChars="200"', xml)
        self.assertIn("参考文献", xml)
        self.assertIn("[1] ", xml)
        self.assertIn("[2] ", xml)

    def test_numbering_none_omits_the_bracket(self):
        csv_path = self.refs_csv(["一条参考文献。"])
        blocks = [{"type": "references", "csv": csv_path, "numbering": "none"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertNotIn("[1] ", xml)
        self.assertIn("一条参考文献", xml)

    def test_reference_text_resolves_placeholders(self):
        csv_path = self.refs_csv(["样本源于 {n_total} 份材料。"])
        blocks = [{"type": "references", "csv": csv_path}]
        argv = self.spec(blocks, numbers={"n_total": "500"})
        result = run("assemble_manuscript.py", *argv)
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn("样本源于 500 份材料", xml)

    def test_empty_reference_row_is_fatal(self):
        csv_path = self.refs_csv(["", "第二条"])
        blocks = [{"type": "references", "csv": csv_path}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("row 2", result.stderr)

    def test_missing_text_column_is_fatal(self):
        csv_path = write_csv(self.p("bad.csv"), ["cite"], [["x"]])
        blocks = [{"type": "references", "csv": csv_path}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("'text' column", result.stderr)

    def test_missing_references_csv_is_fatal(self):
        blocks = [{"type": "references", "csv": "nope.csv"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("nope.csv", result.stderr)

    def test_duplicate_entries_warn_but_build(self):
        csv_path = self.refs_csv(["同一条。", "同一条。"])
        blocks = [{"type": "references", "csv": csv_path}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("identical", result.stderr)


class TestToc(AssemblerCase):
    def test_toc_field_is_written_with_levels(self):
        blocks = [{"type": "toc", "levels": "1-2"},
                  {"type": "heading", "level": 1, "text": "一、引言"},
                  {"type": "para", "text": "正文。"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn('w:instr=" TOC \\o &quot;1-2&quot; \\h \\z \\u "', xml)
        self.assertIn("更新", xml)

    def test_bad_levels_range_is_fatal(self):
        blocks = [{"type": "toc", "levels": "3-1"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("levels", result.stderr)

    def test_toc_hint_does_not_double_the_level_range(self):
        blocks = [{"type": "toc"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.p("out", "manuscript.docx")) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn("域参数 1-3", xml)
        self.assertNotIn("1-1-3", xml)


class TestCrossReferenceStrictness(AssemblerCase):
    """Audit round 1: typo'd markers must fail, not ship as bracket text."""

    def near_miss(self, marker):
        csv_path = self.table_csv()
        blocks = [{"type": "para", "text": f"见{marker}。"},
                  {"type": "table", "csv": csv_path, "caption": "t"}]
        return run("assemble_manuscript.py", *self.spec(blocks))

    def test_uppercase_marker_is_fatal(self):
        result = self.near_miss("[@TAB:1]")
        self.assertEqual(result.returncode, 2)
        self.assertIn("[@TAB:1]", result.stderr)

    def test_marker_with_space_is_fatal(self):
        result = self.near_miss("[@tab: 1]")
        self.assertEqual(result.returncode, 2)
        self.assertIn("[@tab: 1]", result.stderr)

    def test_marker_with_leading_space_is_fatal(self):
        result = self.near_miss("[ @tab:1]")
        self.assertEqual(result.returncode, 2)

    def test_reference_row_xref_to_missing_table_is_fatal(self):
        # references rows are rendered through the same REF machinery but
        # are invisible to the spec-level pre-scan: the runtime guard there
        # is what catches them
        csv_path = self.table_csv()
        refs = write_csv(self.p("refs.csv"), ["text"],
                         [[f"某研究引用了[@tab:9]。"]])
        blocks = [{"type": "references", "csv": refs},
                  {"type": "table", "csv": csv_path, "caption": "t"}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("表9", result.stderr)

    def test_reference_row_typoed_marker_is_fatal(self):
        refs = write_csv(self.p("refs.csv"), ["text"],
                         [[f"另见[@Fig:1]。"]])
        blocks = [{"type": "references", "csv": refs}]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 2)
        self.assertIn("[@Fig:1]", result.stderr)

    def test_mixed_explicit_and_auto_numbering_warns(self):
        csv_path = self.table_csv()
        blocks = [
            {"type": "table", "csv": csv_path, "caption": "a", "number": 5},
            {"type": "table", "csv": csv_path, "caption": "b"},
        ]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("非单调", result.stderr)

    def test_monotonic_explicit_numbering_does_not_warn(self):
        csv_path = self.table_csv()
        blocks = [
            {"type": "table", "csv": csv_path, "caption": "a", "number": 2},
            {"type": "table", "csv": csv_path, "caption": "b", "number": 3},
        ]
        result = run("assemble_manuscript.py", *self.spec(blocks))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("非单调", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
