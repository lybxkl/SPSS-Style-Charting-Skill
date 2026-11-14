# -*- coding: utf-8 -*-
"""Recovery layer: source units, OCR/visual evidence, tables, ASR, audit views.

Covers A04 (partial scan range), A05 (rotation/bbox round trip), A06 (OCR is not
a fact; a re-read corrects and invalidates), A07 (cross-page tables), A08
(merged cells / stale formula cache / date epoch), A09 (ASR timings, gated on a
real provider), A10 (approximate reading kind), A43 (containers), A44 (audit view
identity), A46 (legal empty table), A58 (generated value kinds).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

from _helpers import PYTHON, SCRIPTS, TempCase, run, write_csv

import audit_view as AV
import contract_v2 as C
import ocr_provider as O
import source_units as SU
import table_recovery as TR


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def make_mixed_pdf(path: str) -> dict:
    """A text page, a pure scan page and a mixed page in one PDF."""
    import fitz
    from PIL import Image, ImageDraw

    doc = fitz.open()
    p1 = doc.new_page(width=400, height=300)
    p1.insert_text((40, 60), "Page one has a real text layer.", fontsize=12)

    img = Image.new("RGB", (800, 400), "white")
    d = ImageDraw.Draw(img)
    d.text((30, 40), "SCANNED TOTAL 1,284.50", fill="black")
    img_path = os.path.join(tempfile.mkdtemp(prefix="scan-fixture-"),
                            "scan.png")
    img.save(img_path)
    p2 = doc.new_page(width=400, height=300)
    p2.insert_image(fitz.Rect(0, 0, 400, 300), filename=img_path)

    p3 = doc.new_page(width=400, height=300)
    p3.insert_text((40, 80), "text plus a picture below", fontsize=11)
    p3.insert_image(fitz.Rect(40, 120, 360, 280), filename=img_path)

    doc.save(path)
    doc.close()
    return {"scan_image": img_path}


def make_rotated_pdf(path: str, text: str = "ROTATED LABEL 42") -> dict:
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((60, 80), text, fontname="helv", fontsize=22)
    truth = {}
    for w in page.get_text("words"):
        truth.setdefault("words", []).append([round(v, 2) for v in w[:4]])
    union = [min(w[0] for w in truth["words"]), min(w[1] for w in truth["words"]),
             max(w[2] for w in truth["words"]), max(w[3] for w in truth["words"])]
    page.set_rotation(90)
    doc.save(path)
    doc.close()
    return {"text": text, "union_bbox": union}


def make_table_pdf(path: str) -> dict:
    """Two-page table with a repeated multi-level header and a unit footnote."""
    import fitz
    doc = fitz.open()
    header = [["Group", "Share", "Mean"], ["", "n", "(%)"]]
    body1 = [["Control", "120", "48.2"], ["Treatment", "131", "52.7"]]
    body2 = [["Treatment B", "88", "61.4"]]

    def draw(page, rows, *, start_y=60):
        x0, cw, rh = 40, (130, 80, 80), 24
        y = start_y
        for row in rows:
            x = x0
            for c, val in enumerate(row):
                page.draw_rect(fitz.Rect(x, y, x + cw[c], y + rh),
                               color=(0, 0, 0), width=0.7)
                if val:
                    page.insert_text((x + 4, y + 16), val, fontname="helv",
                                     fontsize=9)
                x += cw[c]
            y += rh
        return y

    p1 = doc.new_page(width=400, height=400)
    p1.insert_text((40, 40), "Table 1. Allocation", fontsize=10)
    y = draw(p1, header + body1)
    p1.insert_text((40, y + 16), "Note: percentages use the wave-1 denominator.",
                   fontsize=7)
    p1.insert_text((40, y + 28), "单位：人", fontname="china-s", fontsize=8)
    p2 = doc.new_page(width=400, height=400)
    draw(p2, header + body2)
    doc.save(path)
    doc.close()
    return {"header_rows": 2, "body_rows": 3}


def make_docx_with_table(path: str) -> dict:
    from docx import Document
    doc = Document()
    doc.add_paragraph("Mixed header table")
    table = doc.add_table(rows=3, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1))
    table.cell(0, 0).text = "Merged header"
    table.cell(0, 2).text = "Value"
    table.cell(1, 0).text = "A"
    table.cell(1, 1).text = "1"
    table.cell(1, 2).text = "2"
    table.cell(2, 0).merge(table.cell(2, 1))
    table.cell(2, 0).text = "wide"
    table.cell(2, 2).text = "3"
    doc.save(path)
    # add a real embedded object member to the OOXML package
    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("word/embeddings/oleObject1.bin", b"\x00OLE payload")
    return {}


def make_workbook(path: str) -> dict:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Survey"
    ws["A1"] = "id"
    ws["B1"] = "amount"
    ws["A2"] = "007"                     # leading zero as text
    ws["B2"] = 10
    ws["A3"] = "008"
    ws["B3"] = 32
    ws["B4"] = "=SUM(B2:B3)"
    ws["A5"] = "merged"
    ws.merge_cells("A5:B5")
    ws["A6"] = "date"
    ws["B6"] = __import__("datetime").datetime(2024, 3, 5)
    wb.save(path)
    # inject a stale cached value for the formula cell, which a naive reader
    # would trust
    with zipfile.ZipFile(path) as zf:
        items = {n: zf.read(n) for n in zf.namelist()}
    sheet_name = "xl/worksheets/sheet1.xml"
    xml = items[sheet_name].decode("utf-8")
    import re
    xml2, n = re.subn(r'(<f>SUM\(B2:B3\)</f>)<v></v>', r"\1<v>999</v>", xml)
    if n == 0:
        xml2, n = re.subn(r'(<f>SUM\(B2:B3\)</f>)', r"\1<v>999</v>", xml)
    assert n == 1, "could not inject the stale cache"
    items[sheet_name] = xml2.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in items.items():
            zf.writestr(name, data)
    return {"sum": 42.0, "cached": 999.0}


def make_zip(path: str, inner: str) -> dict:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("interview_a.txt", "受访者 A，42 岁，2023-05-01。")
        zf.writestr("interview_b.txt", "受访者 B，37 岁，2023-05-02。")
        zf.writestr("notes/dup.txt", "受访者 A，42 岁，2023-05-01。")
    return {"members": 3}


def make_wav(path: str, sentence: str) -> bool:
    """Speak ``sentence`` with Windows SAPI TTS (local, no network)."""
    script = (
        "$ErrorActionPreference='Stop';"
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "try{$s.SelectVoice('Microsoft Zira Desktop')}catch{};"
        "$f=New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
        "16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        "[System.Speech.AudioFormat.AudioChannel]::Mono);"
        f"$s.SetOutputToWaveFile('{path}',$f);"
        f"$s.Speak('{sentence}');"
        "$s.Dispose()")
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, text=True, timeout=300)
    return proc.returncode == 0 and os.path.isfile(path)


def project(tmp):
    return C.Project(tmp)


# ---------------------------------------------------------------------------
# source units
# ---------------------------------------------------------------------------
class TestSourceUnits(TempCase):
    def setUp(self):
        super().setUp()
        self.proj = project(self.tmp)
        self.mat = self.p("materials")
        os.makedirs(self.mat)
        self.pdf = self.p("materials", "mixed.pdf")
        self.extra = make_mixed_pdf(self.pdf)
        with open(self.p("materials", "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("plain text material\n")
        self.docx = self.p("materials", "report.docx")
        make_docx_with_table(self.docx)
        self.xlsx = self.p("materials", "book.xlsx")
        self.wb = make_workbook(self.xlsx)
        write_csv(self.p("materials", "rows.csv"), ["id", "v"],
                  [["1", "a"], ["2", "b"]])
        self.zip_path = self.p("materials", "pack.zip")
        make_zip(self.zip_path, "")
        self.su = SU.SourceUnits(self.proj, root=self.mat, preview_dpi=150)
        self.summary = self.su.build(self.mat)

    def test_page_units_distinguish_text_scan_and_mixed(self):
        pages = {u["data"]["page"]: u for u in self.su.units("page")}
        self.assertEqual(len(pages), 3)
        kinds = [pages[p]["data"]["recovered_scope"]["page_kind"]
                 for p in sorted(pages)]
        self.assertEqual(kinds, ["text", "scan", "mixed"])
        self.assertTrue(pages[1]["data"]["recovered_scope"]["has_text_layer"])
        self.assertFalse(pages[2]["data"]["recovered_scope"]["has_text_layer"])
        # a scan page is never "fully recovered" just because the PDF opened
        self.assertEqual(pages[2]["status"], "partial")
        self.assertTrue(pages[2]["data"]["unrecovered"])
        self.assertTrue(pages[2]["data"]["preview"])

    def test_partial_reading_is_reported_as_partial_not_full(self):
        mixed = [u for u in self.su.units("page")
                 if u["data"]["recovered_scope"]["page_kind"] == "mixed"][0]
        self.assertEqual(mixed["status"], "partial")
        self.assertIn("OCR", " ".join(mixed["data"]["unrecovered"]))

    def test_containers_are_enumerated_and_members_are_not_observations(self):
        containers = self.proj.read("container")
        kinds = sorted(c["data"]["container_type"] for c in containers)
        self.assertIn("zip", kinds)
        self.assertIn("office_embedded", kinds)
        members = self.su.units("member")
        self.assertEqual(len(members), 3)
        self.assertEqual(self.summary["containers"], len(containers))
        # the duplicate member has the same representation as interview_a
        self.assertGreaterEqual(self.summary["duplicate_representation_units"], 1)
        self.assertLess(self.summary["observations"],
                        self.summary["logical_units"])
        self.assertEqual(self.summary["physical_files"], 6)

    def test_recovery_receipts_and_failure_classes(self):
        # a .doc cannot be read; it must show up as a real failure with a class
        with open(self.p("materials", "old.doc"), "wb") as fh:
            fh.write(b"\xd0\xcf\x11\xe0legacy")
        su = SU.SourceUnits(self.proj, root=self.mat)
        summary = su.build(self.mat)
        self.assertGreaterEqual(summary["failed_recoveries"], 1)
        self.assertIn("unsupported_format", summary["failure_classes"])

    def test_rebuild_is_idempotent(self):
        before = len(self.proj.read("source_unit"))
        self.su.build(self.mat)
        after = len(self.proj.read("source_unit"))
        self.assertEqual(before, after)

    def test_docx_tables_and_embedded_objects_exist_as_units(self):
        docx_tables = [u for u in self.su.units("table")
                       if u["data"]["source"] == "report.docx"]
        self.assertEqual(len(docx_tables), 1)
        objects = self.su.units("object")
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["data"]["container_path"],
                         "word/embeddings/oleObject1.bin")

    def test_cli_build_and_list(self):
        tmp2 = self.p("proj2")
        os.makedirs(tmp2)
        out = run("source_units.py", "--root", tmp2, "build", "--materials",
                  self.mat)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("logical_units", out.stdout)
        listed = run("source_units.py", "--root", tmp2, "list", "--type",
                     "page")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("mixed.pdf", listed.stdout)
        self.assertEqual(len(listed.stdout.strip().splitlines()), 3)


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
class TestOcr(TempCase):
    def setUp(self):
        super().setUp()
        self.proj = project(self.tmp)
        self.mat = self.p("materials")
        os.makedirs(self.mat)
        self.pdf = self.p("materials", "scan.pdf")
        self.extra = make_mixed_pdf(self.pdf)
        self.su = SU.SourceUnits(self.proj, root=self.mat, preview_dpi=216)
        self.su.build(self.mat)
        self.pages = {u["data"]["page"]: u for u in self.su.units("page")}

    def _provider_or_skip(self):
        try:
            return O.get_provider()
        except O.OcrUnavailable as exc:
            self.skipTest(f"no OCR provider installed: {exc}")

    def test_ocr_reads_known_text_and_never_marks_it_verified(self):
        prov = self._provider_or_skip()
        res = O.ocr_page(self.proj, self.su, self.pages[2], provider=prov,
                         dpi=216)
        self.assertEqual(res["status"], "partial")
        text = " ".join(r["text"] for r in res["regions"])
        self.assertIn("1,284.50", text)
        region = self.proj.latest("source_unit", res["regions"][0]["unit"])
        self.assertEqual(region["status"], "partial")
        self.assertIn("not a verified reading", " ".join(
            region["data"]["unrecovered"]))
        self.assertEqual(region["data"]["coord_unit"], "pt")

    def test_ocr_adjudication_corrects_and_invalidates(self):
        prov = self._provider_or_skip()
        res = O.ocr_page(self.proj, self.su, self.pages[2], provider=prov,
                         dpi=216)
        region = self.proj.latest("source_unit", res["regions"][0]["unit"])
        out = O.adjudicate(self.proj, self.su, region, "SCANNED TOTAL 1,284.50",
                           reviewer="agent:reread", note="re-read page 2 image")
        self.assertEqual(out["old"], region["data"]["recovered_scope"]["transcript"])
        fresh = self.proj.latest("source_unit", region["id"])
        self.assertEqual(fresh["status"], "recovered")
        self.assertEqual(fresh["data"]["engine"]["name"], "human-reread")
        self.assertEqual(fresh["data"]["recovered_scope"]["ocr_transcript"],
                         out["old"])
        events = self.proj.read("review_event")
        self.assertEqual(events[-1]["data"]["method"], "source_reread")
        self.assertEqual(events[-1]["data"]["independence"],
                         "independent_of_ocr")
        check = O.visual_evidence_check(fresh,
                                        str(self.proj.root /
                                            fresh["data"]["preview"]))
        self.assertEqual(check["semantic_verification"],
                         "not_possible_by_machine")

    def test_absent_provider_is_a_real_engine_missing_receipt(self):
        class Missing(O.OcrProvider):
            name = "missing"
            version = "0"

            def available(self):
                return False

            def reason(self):
                return "engine not installed in this test"

            def recognize(self, image_path, *, lang=None):
                raise O.OcrUnavailable(self.reason())

        res = O.ocr_page(self.proj, self.su, self.pages[2],
                         provider=Missing())
        self.assertEqual(res["status"], "failed")
        receipt = self.proj.latest("recovery_receipt", res["receipt"])
        self.assertEqual(receipt["data"]["failure_class"], "engine_missing")
        self.assertEqual(self.proj.latest("source_unit",
                                          self.pages[2]["id"])["status"],
                         "partial")

    def test_rotated_page_bbox_maps_back_to_the_text_layer(self):
        prov = self._provider_or_skip()
        import fitz
        rot_pdf = self.p("materials", "rotated.pdf")
        truth = make_rotated_pdf(rot_pdf)
        su = SU.SourceUnits(self.proj, root=self.mat, preview_dpi=216)
        sha = C.file_sha256(rot_pdf)
        units, _ = su._pdf(__import__("pathlib").Path(rot_pdf), "rotated.pdf", sha)
        page_unit = units[0]
        res = O.ocr_page(self.proj, su, page_unit, provider=prov, dpi=216)
        self.assertTrue(res["regions"], "OCR produced no region")
        best = max(res["regions"],
                   key=lambda r: O.iou(r["bbox_page"], truth["union_bbox"]))
        score = O.iou(best["bbox_page"], truth["union_bbox"])
        self.assertGreater(score, 0.55,
                           f"bbox {best['bbox_page']} vs truth "
                           f"{truth['union_bbox']} IoU={score:.2f}")
        # out-of-page coordinates must be refused by the inverse mapping
        with self.assertRaises(ValueError):
            su.map_to_page(page_unit, [-5, 0, 10, 10], scale=3.0,
                           page_size=(400, 300))

    def test_crop_roundtrip_is_locatable(self):
        prov = self._provider_or_skip()
        res = O.ocr_page(self.proj, self.su, self.pages[2], provider=prov,
                         dpi=216)
        region = self.proj.latest("source_unit", res["regions"][0]["unit"])
        box = region["data"]["locator"]["bbox_px"]
        crop = self.su.crop_page(self.pages[2], box, scale=216 / 72)
        self.assertTrue(os.path.isfile(self.proj.root / crop["crop"]))
        self.assertAlmostEqual(crop["page_bbox"][0], region["data"]["bbox"][0],
                               delta=1.0)
        self.assertAlmostEqual(crop["page_bbox"][1], region["data"]["bbox"][1],
                               delta=1.0)


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------
class TestTables(TempCase):
    def test_cross_page_table_keeps_observations_and_drops_repeated_header(self):
        proj = project(self.tmp)
        pdf = self.p("table.pdf")
        truth = make_table_pdf(pdf)
        res = TR.recover_source(proj, pdf)
        structures = res["structures"]
        self.assertEqual(len(structures), 2)
        first, second = structures
        self.assertEqual(len(first["header_rows"]), 2)
        self.assertEqual(first["n_rows"], 4)      # 2 header + 2 body
        self.assertTrue(second["repeated_header"])
        self.assertEqual(second["continuation_of"], first["table_id"])
        self.assertEqual(len(second["body"]), 1)
        group = first["group"]
        self.assertEqual(group["observations"],
                         len(first["body"]) + len(second["body"]))
        self.assertEqual(group["observations"], truth["body_rows"])
        self.assertEqual(first["units"], "人")
        self.assertTrue(any("denominator" in f for f in first["footnotes"]))

    def test_cell_grid_matches_rows_and_columns(self):
        proj = project(self.tmp)
        pdf = self.p("table.pdf")
        make_table_pdf(pdf)
        res = TR.recover_source(proj, pdf)
        table = res["structures"][0]
        self.assertEqual(len(table["cells"]), table["n_rows"] * table["n_cols"])
        coords = {(c["row"], c["col"]) for c in table["cells"]}
        self.assertEqual(len(coords), len(table["cells"]))

    def test_structure_verification_is_independent_and_detects_edits(self):
        proj = project(self.tmp)
        pdf = self.p("table.pdf")
        make_table_pdf(pdf)
        res = TR.recover_source(proj, pdf)
        ok = TR.verify_structure(proj, res["snapshot"])
        self.assertTrue(ok["ok"], ok)
        snap = json.load(open(proj.root / res["snapshot"], encoding="utf-8"))
        snap["structures"][0]["cells"][0]["value"] = "TAMPERED"
        json.dump(snap, open(proj.root / res["snapshot"], "w", encoding="utf-8"),
                  ensure_ascii=False)
        bad = TR.verify_structure(proj, res["snapshot"])
        self.assertFalse(bad["ok"])

    def test_docx_merged_cells_are_not_filled_with_copies(self):
        proj = project(self.tmp)
        docx = self.p("report.docx")
        make_docx_with_table(docx)
        res = TR.recover_source(proj, docx)
        table = res["structures"][0]
        merged = [c for c in table["cells"] if c["origin"] != "own"]
        self.assertTrue(merged)
        spanned = [c for c in merged if c["origin"] == "merged"]
        self.assertTrue(all(c["value"] == "" for c in spanned),
                        "a horizontally spanned cell must not duplicate the "
                        "header text into a data cell")

    def test_stale_formula_cache_is_detected_not_trusted(self):
        proj = project(self.tmp)
        xlsx = self.p("book.xlsx")
        truth = make_workbook(xlsx)
        res = TR.recover_source(proj, xlsx)
        sheet = res["sheets"]["Survey"]
        self.assertEqual(sheet["formulas"], 1)
        formula_cell = [c for c in sheet["cells"] if "formula" in c][0]
        self.assertEqual(formula_cell["cached_value"], "999")
        values = {c["cell"]: c["value"] for c in sheet["cells"]}
        check = TR.recompute_formula(formula_cell, values)
        self.assertEqual(check["status"], "mismatch")
        self.assertEqual(check["computed"], truth["sum"])
        self.assertEqual(check["cached"], "999")

    def test_xlsx_merged_and_leading_zero_and_epoch(self):
        proj = project(self.tmp)
        xlsx = self.p("book.xlsx")
        make_workbook(xlsx)
        res = TR.recover_source(proj, xlsx)
        sheet = res["sheets"]["Survey"]
        ids = {c["cell"]: c for c in sheet["cells"]}
        self.assertEqual(ids["A2"]["value"], "007")
        self.assertTrue(ids["A2"].get("leading_zero"))
        merged = [c for c in sheet["cells"] if c["origin"] == "merged"]
        self.assertTrue(merged)
        self.assertTrue(all(c["value"] == "" for c in merged))
        self.assertEqual(res["epoch"], "1899-12-30")
        self.assertEqual(ids["B6"]["iso"], "2024-03-05T00:00:00")


# ---------------------------------------------------------------------------
# audit views
# ---------------------------------------------------------------------------
class TestAuditView(TempCase):
    def test_jsonl_duplicate_keys_are_rejected(self):
        proj = project(self.tmp)
        path = self.p("materials", "dup.jsonl")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"a": 1, "a": 2}\n')
        built = AV.build_view(proj, path)
        res = AV.verify_view(proj, built["view"])
        self.assertFalse(res["ok"])
        dup = [c for c in res["checks"] if c["check"] == "duplicate_keys"][0]
        self.assertFalse(dup["ok"])
        self.assertTrue(any("a" in d for d in dup["duplicates"]))

    def test_json_number_text_is_preserved_through_the_view(self):
        proj = project(self.tmp)
        path = self.p("materials", "numbers.json")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"big": 123456789012345678901234567890, "small": 0.10}')
        built = AV.build_view(proj, path)
        res = AV.verify_view(proj, built["view"])
        self.assertTrue(res["ok"], res["checks"])
        rows = list(__import__("csv").DictReader(open(
            proj.root / built["view"], encoding="utf-8")))
        values = {r["path"]: r["value"] for r in rows}
        self.assertEqual(values["/big"], "123456789012345678901234567890")
        self.assertEqual(values["/small"], "0.10")

    def test_xlsx_view_is_checked_against_raw_xml(self):
        proj = project(self.tmp)
        xlsx = self.p("materials", "book.xlsx")
        os.makedirs(os.path.dirname(xlsx))
        make_workbook(xlsx)
        built = AV.build_view(proj, xlsx)
        res = AV.verify_view(proj, built["view"])
        self.assertTrue(res["ok"], [c for c in res["checks"] if not c["ok"]])
        # drop a cell from the view: the independent reader must notice
        view_path = proj.root / built["view"]
        lines = view_path.read_text(encoding="utf-8").splitlines()
        view_path.write_text("\n".join([ln for ln in lines if ",A2," not in ln])
                             + "\n", encoding="utf-8")
        bad = AV.verify_view(proj, built["view"], record=False)
        self.assertFalse(bad["ok"])

    def test_native_change_invalidates_the_view(self):
        proj = project(self.tmp)
        path = self.p("materials", "data.csv")
        os.makedirs(os.path.dirname(path))
        write_csv(path, ["a"], [["1"]])
        built = AV.build_view(proj, path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("2\n")
        res = AV.verify_view(proj, built["view"])
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "mismatch")
        self.assertIn("changed", res["checks"][0]["note"])

    def test_legal_empty_table_has_range_evidence_and_no_percentage(self):
        out = AV.empty_table_evidence(
            "events", window="2020-01-01..2020-12-31", denominator="all 412 cases",
            source_rel="materials/cases.csv", source_sha256="a" * 64,
            reread_by="agent:reread", reread_note="read all 412 rows",
            columns=["case_id", "event"])
        self.assertEqual(out["cell_coverage"], "not_applicable")
        self.assertNotIn("%", str(out["cell_coverage"]))
        with self.assertRaises(AV.AuditError):
            AV.empty_table_evidence("events", window="", denominator="",
                                    source_rel="", source_sha256="",
                                    reread_by="", reread_note="",
                                    columns=[])

    def test_generated_values_need_method_and_uncertainty(self):
        with self.assertRaises(AV.AuditError):
            AV.generated_value_record("estimated", "4.2", method="",
                                      uncertainty="")
        ok = AV.generated_value_record(
            "image_approx", "4.2", method="pixel calibration 0.1/px",
            uncertainty="+-0.3", sources=[{"path": "f.png"}])
        self.assertFalse(ok["observed_layer"])
        observed = AV.generated_value_record("observed", "4.2",
                                             method="", uncertainty="",
                                             sources=[{"path": "a.csv"}])
        self.assertTrue(observed["observed_layer"])


# ---------------------------------------------------------------------------
# ASR (real provider; skipped only when the environment lacks one)
# ---------------------------------------------------------------------------
def _asr_provider_or_none():
    import asr_provider as ASR
    model = ASR.find_model()
    if not model:
        return None
    # vosk's native loader cannot open model paths with non-ASCII characters,
    # so mirror the model to an ASCII temp path once per test session.
    if any(ord(ch) > 127 for ch in os.path.abspath(model)):
        target = os.path.join(tempfile.gettempdir(), "skill-vosk-model")
        if not os.path.isdir(target):
            shutil.copytree(model, target)
        model = target
    prov = ASR.VoskProvider(model)
    return prov if prov.available() else None


class TestAsr(TempCase):
    def setUp(self):
        super().setUp()
        prov = _asr_provider_or_none()
        if prov is None:
            self.skipTest("vosk model not available "
                          "(set VOSK_MODEL); recorded as unassessed, not passed")
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg missing")
        self.prov = prov
        self.proj = project(self.tmp)
        self.mat = self.p("materials")
        os.makedirs(self.mat)
        self.wav = self.p("materials", "talk.wav")
        self.sentence = "the total number of participants was two hundred and eleven"
        if not make_wav(self.wav, self.sentence):
            self.skipTest("SAPI TTS unavailable; cannot build the fixture")
        self.su = SU.SourceUnits(self.proj, root=self.mat)
        self.su.build(self.mat)
        self.media = [u for u in self.su.units("media")][0]

    def test_transcript_has_real_timings_and_is_partial(self):
        import asr_provider as ASR
        res = ASR.transcribe_media(self.proj, self.su, self.media,
                                   provider=self.prov)
        self.assertEqual(res["status"], "partial", res)
        self.assertTrue(res["segments"])
        seg = res["segments"][0]
        self.assertLess(seg["start"], seg["end"])
        self.assertIn("participants", seg["text"])
        unit = self.proj.latest("source_unit", seg["unit"])
        self.assertEqual(unit["status"], "partial")
        self.assertIsNone(unit["data"]["recovered_scope"]["speaker"])
        self.assertTrue(unit["data"]["recovered_scope"]["words"][0]["start"]
                        >= 0)

    def test_replay_cuts_the_recorded_interval(self):
        import asr_provider as ASR
        res = ASR.transcribe_media(self.proj, self.su, self.media,
                                   provider=self.prov)
        unit = self.proj.latest("source_unit", res["segments"][0]["unit"])
        clip = self.p("clip.wav")
        info = ASR.replay(self.proj, unit, clip)
        self.assertTrue(os.path.isfile(clip))
        self.assertAlmostEqual(info["duration"], info["requested_duration"],
                               delta=0.6)

    def test_relisten_can_mark_a_word_disputed(self):
        import asr_provider as ASR
        res = ASR.transcribe_media(self.proj, self.su, self.media,
                                   provider=self.prov)
        unit = self.proj.latest("source_unit", res["segments"][0]["unit"])
        out = ASR.adjudicate(self.proj, self.su, unit,
                             "the total number of participants was 211",
                             reviewer="agent:listen",
                             note="listened to 0.0-3.1s; speaker is the PI",
                             speaker="PI")
        fresh = self.proj.latest("source_unit", unit["id"])
        self.assertEqual(fresh["data"]["recovered_scope"]["speaker"], "PI")
        self.assertEqual(fresh["data"]["recovered_scope"]["asr_transcript"],
                         unit["data"]["recovered_scope"]["transcript"])
        self.assertEqual(out["revision"], 2)
