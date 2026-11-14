# -*- coding: utf-8 -*-
"""Final-placement layout checks (A38/A39, R09 item 6).

The fixtures are real artefacts: DOCX built with python-docx, PDF built with
PyMuPDF, images built with Pillow.  Expected values are computed here from the
DPI formula, never by calling the function under test and comparing it with
itself.

What is covered:

* a 1200 px figure placed at 8.5 cm / 15 cm is reported below 600 dpi, and only
  a 2.5 cm placement clears 1200 dpi;
* a 6000 px source passes at its 25.4 cm design width but fails when stretched
  to 30 cm - "the source file is fine" is not "the placement is fine";
* DOCX and PDF are matched by decoded image content (same image, other name and
  other order still matches; a different image is reported unmatched);
* a missing caption fails, an adjacent one passes;
* a table without ``tblHeader`` is caught, one with it passes;
* a bitmap figure in the PDF has no text layer: ``no_text_layer`` lands in
  ``unverifiable`` and the check is ``unassessed``, never ``passed``;
* the record lands in ``output/v2/layout_check.jsonl`` and passes
  ``contract_v2.validate_record``.
"""
import json
import os
import shutil

from _helpers import SCRIPTS, TempCase, run

import contract_v2 as C
import layout_check as L


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def make_png(path, width=1200, height=800, color=(31, 97, 143)):
    from PIL import Image
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.new("RGB", (width, height), color).save(path)
    return path


def make_pdf(path, placements, *, blank_pages=0):
    """Build a real PDF.

    ``placements`` items: ``{"png", "width_cm", "x_pt", "y_pt", "texts"}`` where
    ``texts`` is a list of ``(text, size_pt, dx_pt, dy_pt)`` inserted *inside*
    the image box (a vector figure's labels).
    """
    import fitz
    from PIL import Image
    widths = []
    for item in placements:
        with Image.open(item["png"]) as im:
            pw, ph = im.size
        w = item["width_cm"] / 2.54 * 72
        widths.append((item["x_pt"], w + 60))
    page_width = max([595] + [right for _, right in widths])
    doc = fitz.open()
    page = doc.new_page(width=page_width, height=842)
    for item in placements:
        with Image.open(item["png"]) as im:
            pw, ph = im.size
        w = item["width_cm"] / 2.54 * 72
        h = w * ph / pw
        rect = fitz.Rect(item["x_pt"], item["y_pt"],
                         item["x_pt"] + w, item["y_pt"] + h)
        page.insert_image(rect, filename=item["png"])
        for text, size, dx, dy in item.get("texts", []):
            page.insert_text((rect.x0 + dx, rect.y0 + dy), text, fontsize=size)
    for _ in range(blank_pages):
        doc.new_page(width=page_width, height=842)
    doc.save(path)
    doc.close()
    return path


def make_text_pdf(path, text="方法", pages=1):
    import fitz
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), text, fontname="china-s", fontsize=12)
    doc.save(path)
    doc.close()
    return path


def make_docx(path, png=None, width_cm=15.0, *, caption=None,
              before="正文见图 1。", keep_caption_next=False,
              other_texts=()):
    from docx import Document
    from docx.shared import Cm
    doc = Document()
    if before:
        doc.add_paragraph(before)
    for text in other_texts:
        doc.add_paragraph(text)
    if png:
        doc.add_picture(png, width=Cm(width_cm))
        if caption is not None:
            paragraph = doc.add_paragraph(caption)
            if keep_caption_next:
                paragraph.paragraph_format.keep_with_next = True
    doc.save(path)
    return path


def set_row_flags(table, *, header, cant_split):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    if header:
        tr_pr = table.rows[0]._tr.get_or_add_trPr()
        if tr_pr.find(qn("w:tblHeader")) is None:
            tr_pr.append(OxmlElement("w:tblHeader"))
    if cant_split:
        for row in table.rows:
            tr_pr = row._tr.get_or_add_trPr()
            if tr_pr.find(qn("w:cantSplit")) is None:
                tr_pr.append(OxmlElement("w:cantSplit"))


def make_table_docx(path, *, header=True, cant_split=True):
    from docx import Document
    doc = Document()
    doc.add_paragraph("表 1  描述统计")
    table = doc.add_table(rows=3, cols=2)
    for r, row in enumerate(table.rows):
        for c, cell in enumerate(row.cells):
            cell.text = f"r{r}c{c}"
    set_row_flags(table, header=header, cant_split=cant_split)
    doc.save(path)
    return path


def set_run_fonts(run):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    r_pr = run._r.get_or_add_rPr()
    fonts = OxmlElement("w:rFonts")
    for key in ("ascii", "hAnsi", "eastAsia"):
        fonts.set(qn(f"w:{key}"), "Times New Roman")
    r_pr.append(fonts)


def find_check(result, name, figure_id=None):
    for check in result["checks"]:
        if check["check"] != name:
            continue
        if figure_id is not None and check.get("figure_id") != figure_id:
            continue
        return check
    raise AssertionError(
        f"no {name!r} check (figure_id={figure_id!r}) in "
        f"{[c['check'] for c in result['checks']]}")


def placement(self, png, width_cm, *, caption="图 1  测试图题（N=120）",
              text_size=8.0, docx_name="t.docx", pdf_name="t.pdf"):
    """One DOCX + one PDF at the same width; returns check_placement()."""
    docx = make_docx(self.p(docx_name), png, width_cm, caption=caption)
    pdf = make_pdf(self.p(pdf_name),
                   [{"png": png, "width_cm": width_cm, "x_pt": 60, "y_pt": 80,
                     "texts": [("label", text_size, 8, 30)]}])
    return L.check_placement(docx, pdf, figures=[{
        "figure_id": "f1", "png": png, "caption": caption}]), docx, pdf


# ---------------------------------------------------------------------------
# 1. the dpi formula itself
# ---------------------------------------------------------------------------
class TestEffectiveDpi(TempCase):
    def test_formula_is_pixels_over_placed_inches(self):
        # 1200 px / (8.5 cm / 2.54) = 358.588... dpi; computed here, not borrowed.
        self.assertAlmostEqual(L.effective_dpi(1200, 8.5),
                               1200 * 2.54 / 8.5, places=6)
        self.assertAlmostEqual(L.effective_dpi(1200, 8.5), 358.5882, places=3)
        self.assertAlmostEqual(L.effective_dpi(1200, 2.5), 1219.2, places=6)

    def test_design_width_at_600_dpi(self):
        # 3543.3 px are needed for 15 cm at 600 dpi, so 3543 px measures 599.9.
        self.assertAlmostEqual(L.effective_dpi(3543, 15.0), 599.948, places=2)
        self.assertLess(L.effective_dpi(3543, 15.0), 600)

    def test_narrower_placement_raises_dpi(self):
        self.assertGreater(L.effective_dpi(1200, 2.5), L.effective_dpi(1200, 8.5))
        self.assertGreater(L.effective_dpi(1200, 8.5), L.effective_dpi(1200, 15.0))

    def test_bad_dimensions_are_rejected(self):
        with self.assertRaises(ValueError):
            L.effective_dpi(1200, 0)
        with self.assertRaises(ValueError):
            L.effective_dpi(0, 8.5)


# ---------------------------------------------------------------------------
# 2. a qualified source can still fail after placement
# ---------------------------------------------------------------------------
class TestShrunkPlacement(TempCase):
    def test_1200px_at_8_5cm_and_15cm_fails_2_5cm_passes(self):
        png = make_png(self.p("double.png"), 1200, 800)
        for width, expected, should_pass in (
                (8.5, 1200 * 2.54 / 8.5, False),        # two-column slot
                (15.0, 1200 * 2.54 / 15.0, False),      # full text width
                (2.5, 1200 * 2.54 / 2.5, True)):        # narrow inset
            with self.subTest(width_cm=width):
                result, _, _ = placement(self, png, width)
                check = find_check(result, "placed_dpi", "f1")
                self.assertAlmostEqual(check["effective_dpi"], expected, delta=0.5)
                self.assertAlmostEqual(check["occurrences"][0]["width_cm"], width,
                                       places=3)
                self.assertEqual(check["ok"], should_pass,
                                 f"{width} cm: {check['detail']}")
                self.assertEqual(result["ok"], should_pass,
                                 [c["detail"] for c in result["checks"]
                                  if not c["ok"]])

    def test_same_png_gets_a_different_verdict_per_placement(self):
        png = make_png(self.p("two_slots.png"), 1200, 800)
        wide, _, _ = placement(self, png, 8.5, docx_name="a.docx",
                               pdf_name="a.pdf")
        narrow = L.check_placement(
            make_docx(self.p("b.docx"), png, 2.5, caption="图 1  测试图题（N=120）"),
            make_pdf(self.p("b.pdf"), [{"png": png, "width_cm": 2.5,
                                        "x_pt": 60, "y_pt": 80,
                                        "texts": [("label", 8.0, 8, 30)]}]),
            figures=[{"figure_id": "f1", "png": png,
                      "caption": "图 1  测试图题（N=120）"}])
        self.assertFalse(find_check(wide, "placed_dpi", "f1")["ok"])
        self.assertTrue(find_check(narrow, "placed_dpi", "f1")["ok"])

    def test_one_bad_figure_fails_the_whole_set(self):
        from docx import Document
        from docx.shared import Cm
        good = make_png(self.p("good_set.png"), 6000, 4000)
        bad = make_png(self.p("bad_set.png"), 1200, 800, color=(200, 30, 30))
        docx = self.p("set.docx")
        doc = Document()
        doc.add_paragraph("正文见图 1 和图 2。")
        doc.add_picture(good, width=Cm(10.0))
        doc.add_paragraph("图 1  甲（N=1）")
        doc.add_picture(bad, width=Cm(8.5))
        doc.add_paragraph("图 2  乙（N=2）")
        doc.save(docx)
        pdf = make_pdf(self.p("set.pdf"), [
            {"png": good, "width_cm": 10.0, "x_pt": 60, "y_pt": 80,
             "texts": [("l", 8.0, 8, 30)]},
            {"png": bad, "width_cm": 8.5, "x_pt": 60, "y_pt": 400,
             "texts": [("l", 8.0, 8, 30)]},
        ])
        result = L.check_placement(docx, pdf, figures=[
            {"figure_id": "f1", "png": good, "caption": "图 1  甲（N=1）"},
            {"figure_id": "f2", "png": bad, "caption": "图 2  乙（N=2）"},
        ])
        self.assertTrue(find_check(result, "placed_dpi", "f1")["ok"])
        self.assertFalse(find_check(result, "placed_dpi", "f2")["ok"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["images"]), 2)


# ---------------------------------------------------------------------------
# 3. source resolution vs placed resolution
# ---------------------------------------------------------------------------
class TestSourceVsPlacement(TempCase):
    def test_6000px_source_is_fine_at_25cm_but_not_at_30cm(self):
        png = make_png(self.p("hires.png"), 6000, 4000)
        design_width_cm = 6000 / 600 * 2.54        # 25.4 cm at 600 dpi
        self.assertAlmostEqual(L.effective_dpi(6000, design_width_cm), 600.0,
                               places=6)

        cases = ((5.0, 3048.0, True),
                 (25.0, 609.6, True),
                 (30.0, 508.0, False))
        for width, expected, should_pass in cases:
            with self.subTest(width_cm=width):
                result, _, _ = placement(self, png, width, docx_name=f"{width}.docx",
                                         pdf_name=f"{width}.pdf")
                check = find_check(result, "placed_dpi", "f1")
                self.assertAlmostEqual(check["effective_dpi"], expected, delta=0.5)
                self.assertEqual(check["ok"], should_pass, check["detail"])
                self.assertEqual(result["ok"], should_pass)

        # the source image is identical in all three cases: only the placement
        # differs, which is exactly the point ("源图合格 ≠ 安置合格").
        five, _, _ = placement(self, png, 5.0, docx_name="c5.docx",
                               pdf_name="c5.pdf")
        thirty, _, _ = placement(self, png, 30.0, docx_name="c30.docx",
                                 pdf_name="c30.pdf")
        self.assertEqual(five["images"][0]["sha256"], thirty["images"][0]["sha256"])
        self.assertTrue(five["ok"])
        self.assertFalse(thirty["ok"])

    def test_stretched_figure_reports_the_failing_width(self):
        png = make_png(self.p("wide.png"), 6000, 4000)
        result, _, _ = placement(self, png, 30.0)
        check = find_check(result, "placed_dpi", "f1")
        self.assertIn("30", check["detail"])
        self.assertLess(check["effective_dpi"], 600)
        self.assertAlmostEqual(check["occurrences"][0]["width_cm"], 30.0, places=3)


# ---------------------------------------------------------------------------
# 4. DOCX <-> PDF identity is image content, not name or order
# ---------------------------------------------------------------------------
class TestImageMatching(TempCase):
    def test_same_content_matches_across_formats(self):
        png = make_png(self.p("one.png"), 1200, 800)
        docx = make_docx(self.p("m.docx"), png, 15.0, caption="图 1  甲（N=10）")
        pdf = make_pdf(self.p("m.pdf"), [{"png": png, "width_cm": 15.0,
                                          "x_pt": 60, "y_pt": 80}])
        docx_info = L.inspect_docx(docx)
        pdf_info = L.inspect_pdf(pdf)
        match = L.match_images(docx_info, pdf_info)
        self.assertTrue(match["ok"], match["docx_only"] + match["pdf_only"])
        self.assertEqual(match["counts"]["matched"], 1)
        self.assertEqual(match["matched"][0]["sha256"],
                         docx_info["images"][0]["sha256"])
        self.assertEqual(match["matched"][0]["sha256"],
                         pdf_info["pages"][0]["images"][0]["sha256"])
        self.assertTrue(match["matched"][0]["placement_consistent"])

    def test_match_ignores_name_and_order(self):
        first = make_png(self.p("first.png"), 1200, 800, color=(20, 120, 40))
        second = make_png(self.p("second.png"), 1200, 800, color=(160, 30, 30))
        renamed = self.p("whatever_else.png")
        shutil.copyfile(first, renamed)
        docx = make_docx(self.p("order.docx"), first, 15.0, caption="图 1  甲")
        # second image is inserted first: order must not decide the mapping
        pdf = make_pdf(self.p("order.pdf"), [
            {"png": second, "width_cm": 15.0, "x_pt": 60, "y_pt": 80},
            {"png": renamed, "width_cm": 15.0, "x_pt": 60, "y_pt": 400},
        ])
        match = L.match_images(L.inspect_docx(docx), L.inspect_pdf(pdf))
        matched_sha = [m["sha256"] for m in match["matched"]]
        docx_sha = L.inspect_docx(docx)["images"][0]["sha256"]
        self.assertIn(docx_sha, matched_sha)
        # the unrelated image is reported, not silently paired
        self.assertEqual(len(match["pdf_only"]), 1)
        self.assertFalse(match["ok"])

    def test_different_image_in_pdf_is_unmatched(self):
        source = make_png(self.p("source.png"), 1200, 800, color=(10, 60, 120))
        other = make_png(self.p("other.png"), 1200, 800, color=(220, 120, 10))
        docx = make_docx(self.p("x.docx"), source, 15.0, caption="图 1  甲")
        pdf = make_pdf(self.p("x.pdf"), [{"png": other, "width_cm": 15.0,
                                          "x_pt": 60, "y_pt": 80}])
        docx_info = L.inspect_docx(docx)
        pdf_info = L.inspect_pdf(pdf)
        match = L.match_images(docx_info, pdf_info)
        self.assertFalse(match["ok"])
        self.assertEqual([entry["sha256"] for entry in match["docx_only"]],
                         [docx_info["images"][0]["sha256"]])
        self.assertEqual([entry["sha256"] for entry in match["pdf_only"]],
                         [pdf_info["pages"][0]["images"][0]["sha256"]])

    def test_same_image_at_a_different_pdf_size_is_not_consistent(self):
        png = make_png(self.p("sized.png"), 1200, 800)
        docx = make_docx(self.p("s.docx"), png, 15.0, caption="图 1  甲")
        pdf = make_pdf(self.p("s.pdf"), [{"png": png, "width_cm": 8.5,
                                          "x_pt": 60, "y_pt": 80}])
        match = L.match_images(L.inspect_docx(docx), L.inspect_pdf(pdf))
        self.assertTrue(match["matched"])
        self.assertFalse(match["matched"][0]["placement_consistent"])
        self.assertFalse(match["ok"])

    def test_declared_png_missing_from_docx_is_loud_and_unverifiable(self):
        embedded = make_png(self.p("real.png"), 1200, 800, color=(10, 20, 30))
        declared = make_png(self.p("declared.png"), 1200, 800,
                            color=(200, 10, 10))
        docx = make_docx(self.p("loud.docx"), embedded, 2.5, caption="图 1  甲")
        pdf = make_pdf(self.p("loud.pdf"), [{"png": embedded, "width_cm": 2.5,
                                             "x_pt": 60, "y_pt": 80,
                                             "texts": [("l", 8.0, 8, 30)]}])
        result = L.check_placement(
            docx, pdf, figures=[{"figure_id": "f1", "png": declared,
                                 "caption": "图 1  甲"}])
        self.assertFalse(find_check(result, "figure_in_docx", "f1")["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["ok"])
        self.assertEqual(
            sorted(item["check"] for item in result["unverifiable"]),
            ["caption", "docx_pdf_size_match", "min_fontsize", "placed_dpi"])


# ---------------------------------------------------------------------------
# 5. captions
# ---------------------------------------------------------------------------
class TestCaption(TempCase):
    def test_adjacent_caption_passes(self):
        png = make_png(self.p("cap.png"), 1200, 800)
        result, _, _ = placement(self, png, 2.5)
        check = find_check(result, "caption", "f1")
        self.assertTrue(check["ok"], check["detail"])
        self.assertFalse(check["floating"])

    def test_missing_caption_fails(self):
        png = make_png(self.p("nocap.png"), 1200, 800)
        docx = make_docx(self.p("nocap.docx"), png, 2.5, caption=None)
        pdf = make_pdf(self.p("nocap.pdf"), [{"png": png, "width_cm": 2.5,
                                              "x_pt": 60, "y_pt": 80,
                                              "texts": [("label", 8.0, 8, 30)]}])
        result = L.check_placement(
            docx, pdf, figures=[{"figure_id": "f1", "png": png,
                                 "caption": "图 1  测试图题（N=120）"}])
        check = find_check(result, "caption", "f1")
        self.assertFalse(check["ok"])
        self.assertEqual(result["ok"], False)
        info = L.inspect_docx(docx)
        # nothing follows the image paragraph: there is no caption paragraph
        self.assertEqual(info["images"][0]["next_text"], "")
        self.assertFalse(any("测试图题" in candidate
                             for candidate in check["candidates"]))

    def test_wrong_caption_text_fails(self):
        png = make_png(self.p("wrong.png"), 1200, 800)
        docx = make_docx(self.p("wrong.docx"), png, 2.5, caption="图 1  甲图")
        pdf = make_pdf(self.p("wrong.pdf"), [{"png": png, "width_cm": 2.5,
                                              "x_pt": 60, "y_pt": 80,
                                              "texts": [("label", 8.0, 8, 30)]}])
        result = L.check_placement(
            docx, pdf, figures=[{"figure_id": "f1", "png": png,
                                 "caption": "图 2  乙图（N=99）"}])
        self.assertFalse(find_check(result, "caption", "f1")["ok"])

    def test_caption_with_note_line_still_matches(self):
        png = make_png(self.p("note.png"), 1200, 800)
        docx = make_docx(self.p("note.docx"), png, 2.5,
                         caption="图 1  测试图题（N=120）注：误差线为 95% CI。")
        pdf = make_pdf(self.p("note.pdf"), [{"png": png, "width_cm": 2.5,
                                             "x_pt": 60, "y_pt": 80,
                                             "texts": [("label", 8.0, 8, 30)]}])
        result = L.check_placement(
            docx, pdf, figures=[{"figure_id": "f1", "png": png,
                                 "caption": "图 1  测试图题（N=120）"}])
        self.assertTrue(find_check(result, "caption", "f1")["ok"])


# ---------------------------------------------------------------------------
# 6. structure: tables, keepNext, cross references, fonts, blank pages
# ---------------------------------------------------------------------------
class TestStructure(TempCase):
    def test_table_without_tblHeader_is_caught(self):
        docx = make_table_docx(self.p("noheader.docx"), header=False,
                               cant_split=False)
        pdf = make_text_pdf(self.p("noheader.pdf"))
        result = L.check_structure(docx, pdf)
        header = find_check(result, "table_header_repeat")
        self.assertFalse(header["ok"], header["detail"])
        self.assertIn("[0]", header["detail"])
        self.assertFalse(find_check(result, "table_cantSplit")["ok"])
        self.assertFalse(result["ok"])

    def test_table_with_flags_passes(self):
        docx = make_table_docx(self.p("header.docx"), header=True,
                               cant_split=True)
        pdf = make_text_pdf(self.p("header.pdf"))
        result = L.check_structure(docx, pdf)
        self.assertTrue(find_check(result, "table_header_repeat")["ok"])
        self.assertTrue(find_check(result, "table_cantSplit")["ok"])
        self.assertTrue(result["ok"], [c["detail"] for c in result["checks"]
                                       if not c["ok"]])

    def test_no_table_is_not_applicable_not_passed(self):
        docx = make_docx(self.p("plain.docx"), caption=None, before="只有正文。")
        pdf = make_text_pdf(self.p("plain.pdf"))
        result = L.check_structure(docx, pdf)
        header = find_check(result, "table_header_repeat")
        self.assertEqual(header["status"], "not_applicable")
        self.assertIn("table_header_repeat", result["not_applicable"])

    def test_caption_keep_next(self):
        png = make_png(self.p("keep.png"), 1200, 800)
        loose = make_docx(self.p("loose.docx"), png, 2.5,
                          caption="图 1  甲（N=1）")
        tight = make_docx(self.p("tight.docx"), png, 2.5,
                          caption="图 1  甲（N=1）", keep_caption_next=True)
        pdf = make_pdf(self.p("keep.pdf"), [{"png": png, "width_cm": 2.5,
                                             "x_pt": 60, "y_pt": 80}])
        self.assertFalse(find_check(L.check_structure(loose, pdf),
                                    "caption_keepNext")["ok"])
        self.assertTrue(find_check(L.check_structure(tight, pdf),
                                   "caption_keepNext")["ok"])

    def test_cross_reference_with_missing_object(self):
        docx = make_docx(self.p("ref.docx"), caption=None,
                         before="如图 9 所示，结果稳定。")
        pdf = make_text_pdf(self.p("ref.pdf"))
        result = L.check_structure(docx, pdf)
        check = find_check(result, "cross_references")
        self.assertFalse(check["ok"])
        self.assertEqual(check["missing"], {"图": [9], "表": []})

    def test_cross_reference_resolved_by_caption(self):
        png = make_png(self.p("goodref.png"), 1200, 800)
        docx = make_docx(self.p("goodref.docx"), png, 2.5,
                         caption="图 1  甲（N=1）", before="见图 1。")
        pdf = make_pdf(self.p("goodref.pdf"), [{"png": png, "width_cm": 2.5,
                                                "x_pt": 60, "y_pt": 80}])
        check = find_check(L.check_structure(docx, pdf), "cross_references")
        self.assertTrue(check["ok"], check["detail"])
        self.assertEqual(check["objects"]["图"], [1])

    def test_runs_without_eastAsia_are_a_warning_not_a_failure(self):
        docx = make_table_docx(self.p("fontless.docx"))
        pdf = make_text_pdf(self.p("fontless.pdf"))
        result = L.check_structure(docx, pdf)
        fonts = find_check(result, "run_fonts")
        self.assertFalse(fonts["ok"])
        self.assertEqual(fonts["severity"], "warning")
        self.assertGreater(fonts["font_report"]["missing_eastAsia"], 0)
        self.assertTrue(result["warnings"])
        # a warning must not be disguised as a passed check, but it must not
        # fail the document either
        self.assertEqual(fonts["status"], "failed")
        self.assertTrue(result["ok"])

    def test_runs_with_all_three_font_attributes_pass(self):
        from docx import Document
        docx_path = self.p("fullfont.docx")
        doc = Document()
        run = doc.add_paragraph().add_run("方法")
        set_run_fonts(run)
        doc.save(docx_path)
        result = L.check_structure(docx_path, make_text_pdf(self.p("fullfont.pdf")))
        fonts = find_check(result, "run_fonts")
        self.assertTrue(fonts["ok"])
        self.assertEqual(fonts["font_report"]["missing_eastAsia"], 0)

    def test_blank_pdf_page_is_reported(self):
        png = make_png(self.p("blank.png"), 1200, 800)
        docx = make_docx(self.p("blank.docx"), png, 2.5,
                         caption="图 1  甲（N=1）")
        pdf = make_pdf(self.p("blank.pdf"), [{"png": png, "width_cm": 2.5,
                                              "x_pt": 60, "y_pt": 80}],
                       blank_pages=1)
        result = L.check_structure(docx, pdf)
        check = find_check(result, "pdf_pages")
        self.assertFalse(check["ok"])
        self.assertEqual(check["blank_pages"], [2])
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["pages_reviewed"]), 2)


# ---------------------------------------------------------------------------
# 7. a bitmap figure has no text layer: unassessed, never passed
# ---------------------------------------------------------------------------
class TestNoTextLayer(TempCase):
    def test_bitmap_figure_is_unverifiable_not_passed(self):
        png = make_png(self.p("bitmap.png"), 1200, 800)
        docx = make_docx(self.p("bitmap.docx"), png, 2.5,
                         caption="图 1  测试图题（N=120）")
        pdf = make_pdf(self.p("bitmap.pdf"),
                       [{"png": png, "width_cm": 2.5, "x_pt": 60, "y_pt": 80}])
        result = L.check_placement(
            docx, pdf, figures=[{"figure_id": "f1", "png": png,
                                 "caption": "图 1  测试图题（N=120）"}])
        # resolution is fine, so the only reason is the missing text layer
        self.assertTrue(find_check(result, "placed_dpi", "f1")["ok"])
        check = find_check(result, "min_fontsize", "f1")
        self.assertEqual(check["status"], "unassessed")
        self.assertFalse(check["ok"])
        self.assertIn("no_text_layer", check["detail"])
        self.assertEqual([item["check"] for item in result["unverifiable"]],
                         ["min_fontsize"])
        self.assertIn("no_text_layer", result["unverifiable"][0]["reason"])
        # no fake pass: unassessed forces ok False and the status is not passed
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "unassessed")

    def test_source_pdf_fontsize_is_only_a_diagnostic(self):
        png = make_png(self.p("source.png"), 1200, 800)
        # source figure PDF designed 15 cm wide with 8 pt type
        source = make_pdf(self.p("source_fig.pdf"),
                          [{"png": png, "width_cm": 15.0, "x_pt": 60, "y_pt": 80,
                            "texts": [("label", 8.0, 8, 30)]}])
        docx = make_docx(self.p("src.docx"), png, 2.5,
                         caption="图 1  测试图题（N=120）")
        pdf = make_pdf(self.p("src.pdf"),
                       [{"png": png, "width_cm": 2.5, "x_pt": 60, "y_pt": 80}])
        result = L.check_placement(
            docx, pdf, figures=[{"figure_id": "f1", "png": png,
                                 "pdf": source,
                                 "caption": "图 1  测试图题（N=120）"}])
        check = find_check(result, "min_fontsize", "f1")
        self.assertEqual(check["status"], "unassessed")
        estimate = check["source_pdf_diagnostic"]
        # 8 pt at 15 cm printed at 2.5 cm -> 8 * 2.5 / 15 = 1.33 pt
        self.assertAlmostEqual(estimate["estimated_placed_fontsize_pt"], 1.33,
                               places=2)
        self.assertIn("not measured in the final PDF", estimate["basis"])

    def test_type_gate_can_be_disabled_explicitly(self):
        png = make_png(self.p("off.png"), 1200, 800)
        docx = make_docx(self.p("off.docx"), png, 2.5,
                         caption="图 1  测试图题（N=120）")
        pdf = make_pdf(self.p("off.pdf"),
                       [{"png": png, "width_cm": 2.5, "x_pt": 60, "y_pt": 80}])
        result = L.check_placement(
            docx, pdf, figures=[{"figure_id": "f1", "png": png,
                                 "caption": "图 1  测试图题（N=120）"}],
            min_fontsize=0)
        check = find_check(result, "min_fontsize", "f1")
        self.assertEqual(check["status"], "not_applicable")
        self.assertTrue(result["ok"])
        self.assertEqual(result["unverifiable"], [])

    def test_vector_text_inside_the_placed_figure_is_measured(self):
        png = make_png(self.p("vector.png"), 1200, 800)
        docx = make_docx(self.p("vector.docx"), png, 2.5,
                         caption="图 1  测试图题（N=120）")
        pdf = make_pdf(self.p("vector.pdf"),
                       [{"png": png, "width_cm": 2.5, "x_pt": 60, "y_pt": 80,
                         "texts": [("axis", 8.0, 8, 30),
                                   ("tick", 6.0, 8, 45)]}])
        result = L.check_placement(
            docx, pdf, figures=[{"figure_id": "f1", "png": png,
                                 "caption": "图 1  测试图题（N=120）"}])
        check = find_check(result, "min_fontsize", "f1")
        self.assertEqual(check["observed"], 6.0)
        self.assertFalse(check["ok"])                  # 6 pt < 7.2 pt
        self.assertEqual(result["unverifiable"], [])


# ---------------------------------------------------------------------------
# 8. the v2 record
# ---------------------------------------------------------------------------
class TestRecord(TempCase):
    def _passing_result(self):
        png = make_png(self.p("rec.png"), 1200, 800)
        result, docx, pdf = placement(self, png, 2.5)
        self.assertTrue(result["ok"], [c["detail"] for c in result["checks"]
                                       if not c["ok"]])
        return result, docx, pdf

    def test_record_is_written_and_validates(self):
        result, docx, pdf = self._passing_result()
        project = C.Project(self.tmp)
        record = L.record_check(project, result, docx_rel="t.docx",
                                pdf_rel="t.pdf")
        ledger = os.path.join(self.tmp, "output", "v2", "layout_check.jsonl")
        self.assertTrue(os.path.isfile(ledger))
        with open(ledger, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        self.assertEqual(len(rows), 1)
        stored = rows[0]
        C.validate_record(stored)                      # raises on any violation
        self.assertEqual(stored["kind"], "layout_check")
        self.assertEqual(stored["status"], "passed")
        self.assertEqual(record["revision"], 1)
        for field in ("docx", "pdf", "images", "checks", "pages_reviewed"):
            self.assertIn(field, stored["data"])
        self.assertEqual(stored["data"]["docx"], "t.docx")
        self.assertEqual(stored["data"]["pdf"], "t.pdf")
        # pages_reviewed is real page data, not a placeholder
        self.assertEqual(len(stored["data"]["pages_reviewed"]), 1)
        self.assertEqual(stored["data"]["pages_reviewed"][0]["page"], 1)
        self.assertGreater(stored["data"]["pages_reviewed"][0]["text_chars"], 0)
        self.assertGreater(stored["data"]["pages_reviewed"][0]["images"], 0)
        # the record is bound to the artefacts' bytes, not only to their names
        refs = {ref["kind"]: ref for ref in stored["input_refs"]}
        self.assertEqual(set(refs), {"docx", "pdf"})
        for ref in refs.values():
            self.assertEqual(len(ref["sha256"]), 64, ref)

    def test_failed_result_records_failed(self):
        png = make_png(self.p("lowdpi.png"), 1200, 800)
        result, _, _ = placement(self, png, 8.5)
        project = C.Project(self.tmp)
        record = L.record_check(project, result, docx_rel="t.docx",
                                pdf_rel="t.pdf")
        self.assertEqual(record["status"], "failed")
        C.validate_record(record)
        self.assertEqual(record["data"]["checks"],
                         json.loads(json.dumps(result["checks"],
                                               ensure_ascii=False)))

    def test_unverifiable_is_carried_into_the_failed_record(self):
        png = make_png(self.p("bitmap2.png"), 1200, 800)
        docx = make_docx(self.p("bitmap2.docx"), png, 2.5,
                         caption="图 1  测试图题（N=120）")
        pdf = make_pdf(self.p("bitmap2.pdf"),
                       [{"png": png, "width_cm": 2.5, "x_pt": 60, "y_pt": 80}])
        result = L.check_placement(
            docx, pdf, figures=[{"figure_id": "f1", "png": png,
                                 "caption": "图 1  测试图题（N=120）"}])
        record = L.record_check(C.Project(self.tmp), result, docx_rel="b.docx",
                                pdf_rel="b.pdf")
        self.assertEqual(record["status"], "failed")
        self.assertIn("no_text_layer", record["data"]["notes"])
        C.validate_record(record)

    def test_revision_advances_on_re_record(self):
        result, _, _ = self._passing_result()
        project = C.Project(self.tmp)
        first = L.record_check(project, result, docx_rel="t.docx", pdf_rel="t.pdf")
        second = L.record_check(project, result, docx_rel="t.docx", pdf_rel="t.pdf")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["revision"], 2)
        C.validate_record(second)
        self.assertEqual(len(project.revisions("layout_check", first["id"])), 2)

    def test_empty_pages_reviewed_is_refused(self):
        result, _, _ = self._passing_result()
        empty = dict(result)
        empty["pages_reviewed"] = []
        with self.assertRaises(L.LayoutError):
            L.record_check(C.Project(self.tmp), empty, docx_rel="t.docx",
                           pdf_rel="t.pdf")
        self.assertEqual(C.Project(self.tmp).read("layout_check"), [])


# ---------------------------------------------------------------------------
# 9. CLI
# ---------------------------------------------------------------------------
class TestCli(TempCase):
    def test_inspect_dumps_placements(self):
        png = make_png(self.p("cli.png"), 1200, 800)
        docx = make_docx(self.p("cli.docx"), png, 8.5, caption="图 1  甲")
        pdf = make_pdf(self.p("cli.pdf"), [{"png": png, "width_cm": 8.5,
                                            "x_pt": 60, "y_pt": 80}])
        proc = run("layout_check.py", "--root", self.tmp, "inspect",
                   "--docx", docx, "--pdf", pdf)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload["docx"]["images"]), 1)
        self.assertEqual(payload["docx"]["images"][0]["width_cm"], 8.5)
        self.assertEqual(payload["pdf"]["page_count"], 1)
        self.assertTrue(payload["match"]["ok"])

    def test_check_exit_code_reflects_the_verdict(self):
        png = make_png(self.p("cli2.png"), 1200, 800)
        docx = make_docx(self.p("cli2.docx"), png, 8.5,
                         caption="图 1  测试（N=1）")
        pdf = make_pdf(self.p("cli2.pdf"), [{"png": png, "width_cm": 8.5,
                                             "x_pt": 60, "y_pt": 80,
                                             "texts": [("l", 8.0, 8, 30)]}])
        bad = run("layout_check.py", "--root", self.tmp, "check",
                  "--docx", docx, "--pdf", pdf,
                  "--figure", f"{png}=f1",
                  "--figure-caption", "f1=图 1  测试（N=1）")
        self.assertEqual(bad.returncode, 2, bad.stdout + bad.stderr)
        self.assertFalse(json.loads(bad.stdout)["ok"])

        hires = make_png(self.p("cli3.png"), 6000, 4000)
        docx2 = make_docx(self.p("cli3.docx"), hires, 10.0,
                          caption="图 1  测试（N=1）")
        pdf2 = make_pdf(self.p("cli3.pdf"), [{"png": hires, "width_cm": 10.0,
                                              "x_pt": 60, "y_pt": 80,
                                              "texts": [("l", 8.0, 8, 30)]}])
        good = run("layout_check.py", "--root", self.tmp, "check",
                   "--docx", docx2, "--pdf", pdf2,
                   "--figure", f"{hires}=f1",
                   "--figure-caption", "f1=图 1  测试（N=1）", "--record")
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        payload = json.loads(good.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["record"]["status"], "passed")
        self.assertTrue(os.path.isfile(
            os.path.join(self.tmp, "output", "v2", "layout_check.jsonl")))

    def test_missing_pdf_is_an_error_not_a_pass(self):
        png = make_png(self.p("nopdf.png"), 1200, 800)
        docx = make_docx(self.p("nopdf.docx"), png, 2.5, caption="图 1  甲")
        proc = run("layout_check.py", "check", "--docx", docx,
                   "--pdf", self.p("absent.pdf"), "--figure", f"{png}=f1",
                   "--figure-caption", "f1=图 1  甲")
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("pdf_file", [c["check"] for c in payload["checks"]])
        # a missing PDF must not be mislabelled as a bitmap figure
        self.assertNotIn("no_text_layer", proc.stdout)
