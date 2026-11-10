#!/usr/bin/env python3
"""Build a submission-shaped Word manuscript from a JSON spec.

Stage 6 of the pipeline used to be prose: the tables and figures were produced by
scripts, and then a human retyped them into Word. That retyping is where the
numbers drift, because nothing connects the caption in the document to the CSV it
came from.

This script closes that hop. It reads a spec that names CSVs and PNGs, and writes

  * ``manuscript.docx`` — three-line tables (top rule, header rule, bottom rule,
    no vertical lines), rows that cannot split across a page break, a header row
    that repeats, figures placed at a fixed width, captions that cannot be
    separated from what they caption, CJK + Latin fonts set per run, first-line
    indent in characters (not centimetres), and a page number in the footer;
  * ``<out>_numbers.csv`` — every N the document actually printed, so the
    manuscript, the tables and the figures share one source for that number;
  * ``figure_map.json`` — what ``export_pdf_hires.py`` needs to replace Word's
    downsampled bitmaps with the original 600 dpi files.

Nothing here decides content. If a number is missing, the build fails: a caption
that silently says "N=" with nothing after it is worse than a build that stops.

Usage:
  python scripts/assemble_manuscript.py --spec manuscript.json \\
      --out output/manuscript.docx
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

SCRIPT_VERSION = "1.0.0"

try:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt
except ImportError as exc:  # pragma: no cover - depends on the host
    print(f"ERROR: python-docx is required: {exc}", file=sys.stderr)
    raise SystemExit(2)

PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.\-]+)\}")
FIGURE_PX_MIN = 3543  # 15 cm at 600 dpi

ALIGNS = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}

DEFAULT_STYLE = {
    "body_cjk": "宋体",
    "body_latin": "Times New Roman",
    "heading_cjk": "黑体",
    "heading_latin": "Times New Roman",
    "body_size_pt": 12.0,
    "line_spacing": 1.5,
    "first_line_indent_chars": 2,
    "table_size_pt": 9.0,
    "caption_size_pt": 10.5,
    "note_size_pt": 9.0,
    "title_size_pt": 18.0,
    "heading_sizes_pt": [14.0, 12.0, 12.0],
    "figure_width_cm": 15.0,
}


class SpecError(ValueError):
    """The spec asks for something that cannot be built faithfully."""


# --------------------------------------------------------------------------- #
# OOXML helpers
# --------------------------------------------------------------------------- #
def _set_fonts(run, cjk: str, latin: str) -> None:
    """Set both the Latin and the East Asian font on one run.

    python-docx only writes w:rFonts/@w:ascii and @w:hAnsi, so Chinese text
    silently falls back to the theme font while Latin looks correct.
    """
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)
    rfonts.set(qn("w:cs"), latin)
    rfonts.set(qn("w:eastAsia"), cjk)


def _set_indent_chars(paragraph, chars: int, size_pt: float) -> None:
    """First-line indent in *characters*.

    ``w:firstLineChars`` is what Word's "首行缩进 2 字符" actually stores. Setting
    only ``first_line_indent = Cm(0.85)`` breaks as soon as the body size changes.
    """
    ppr = paragraph._p.get_or_add_pPr()
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        ppr.append(ind)
    ind.set(qn("w:firstLineChars"), str(int(chars * 100)))
    ind.set(qn("w:firstLine"), str(int(round(size_pt * chars * 20))))


def _no_split(row) -> None:
    """Forbid a table row from breaking across pages.

    python-docx has no API for this; w:cantSplit has to be appended by hand.
    """
    trpr = row._tr.get_or_add_trPr()
    if trpr.find(qn("w:cantSplit")) is None:
        trpr.append(OxmlElement("w:cantSplit"))


def _repeat_header(row) -> None:
    trpr = row._tr.get_or_add_trPr()
    if trpr.find(qn("w:tblHeader")) is None:
        trpr.append(OxmlElement("w:tblHeader"))


def _border(tag: str, size_eighth_pt: int) -> OxmlElement:
    el = OxmlElement(tag)
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(size_eighth_pt))
    el.set(qn("w:space"), "0")
    el.set(qn("w:color"), "000000")
    return el


def _three_line_borders(table) -> None:
    """Top rule 1.5 pt, bottom rule 1.5 pt, no vertical lines, no inner rules."""
    tblpr = table._tbl.tblPr
    old = tblpr.find(qn("w:tblBorders"))
    if old is not None:
        tblpr.remove(old)
    borders = OxmlElement("w:tblBorders")
    borders.append(_border("w:top", 12))
    borders.append(_border("w:bottom", 12))
    for name in ("w:left", "w:right", "w:insideH", "w:insideV"):
        el = OxmlElement(name)
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "auto")
        borders.append(el)
    tblpr.append(borders)


def _header_rule(row) -> None:
    """The rule under the header row is a cell border, not a table border."""
    for cell in row.cells:
        tcpr = cell._tc.get_or_add_tcPr()
        old = tcpr.find(qn("w:tcBorders"))
        if old is not None:
            tcpr.remove(old)
        b = OxmlElement("w:tcBorders")
        b.append(_border("w:bottom", 6))
        tcpr.append(b)


def _add_page_field(paragraph) -> None:
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)


# --------------------------------------------------------------------------- #
# spec plumbing
# --------------------------------------------------------------------------- #
def load_numbers(path: str | None) -> dict:
    """Read key/value pairs used by ``{placeholder}`` in captions and text."""
    numbers: dict = {}
    if not path:
        return numbers
    if not os.path.exists(path):
        raise SpecError(f"numbers file not found: {path}")
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "key" not in reader.fieldnames:
            raise SpecError("numbers CSV needs a 'key' column")
        for row in reader:
            key = (row.get("key") or "").strip()
            if not key:
                continue
            if key in numbers:
                raise SpecError(f"numbers CSV repeats key {key!r}")
            numbers[key] = (row.get("value") or "").strip()
    return numbers


def resolve_text(text: str, numbers: dict, where: str) -> str:
    """Replace ``{key}`` from the numbers table; unknown keys are fatal.

    Leaving ``{n_analysis}`` in a caption would ship a literal brace to the
    reader, so an unresolved placeholder stops the build.
    """

    def sub(match: "re.Match") -> str:
        key = match.group(1)
        if key not in numbers:
            raise SpecError(f"{where}: no value for {{{key}}}; add it to numbers.csv")
        return numbers[key]

    return PLACEHOLDER.sub(sub, text or "")


def read_table(spec: dict, base_dir: str) -> tuple[list, list, str]:
    path = spec.get("csv")
    if not path:
        raise SpecError("table block needs 'csv'")
    path = path if os.path.isabs(path) else os.path.join(base_dir, path)
    if not os.path.exists(path):
        raise SpecError(f"table CSV not found: {path}")
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SpecError(f"table CSV has no rows: {path}")
    header = list(rows[0].keys())
    columns = spec.get("columns")
    if columns:
        cols = []
        for col in columns:
            if isinstance(col, str):
                col = {"col": col}
            name = col.get("col")
            if name not in header:
                raise SpecError(
                    f"table column {name!r} not in {os.path.basename(path)}; "
                    f"available: {', '.join(header)}"
                )
            cols.append(col)
    else:
        cols = [{"col": name} for name in header]
    return rows, cols, path


def format_cell(value, col: dict) -> str:
    text = "" if value is None else str(value)
    fmt = col.get("fmt")
    if not fmt:
        return text
    if text == "":
        return ""
    try:
        number = float(text.replace(",", ""))
    except ValueError:
        return text
    try:
        return fmt.format(number)
    except (ValueError, IndexError) as exc:
        raise SpecError(f"bad fmt {fmt!r} for value {text!r}: {exc}")


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #
class Builder:
    def __init__(self, spec: dict, base_dir: str, numbers: dict, out_docx: str):
        self.spec = spec
        self.base_dir = base_dir
        self.numbers = numbers
        self.out_docx = out_docx
        self.style = dict(DEFAULT_STYLE)
        self.style.update(spec.get("style") or {})
        self.numbers_used: dict[str, str] = {}
        self.figure_map: list[dict] = []
        self.warnings: list[str] = []
        self.table_no = 0
        self.figure_no = 0
        self.doc = Document()
        self._page_setup()

    # -- document scaffolding ------------------------------------------------
    def _page_setup(self) -> None:
        page = self.spec.get("page") or {}
        width = float(page.get("width_cm", 21.0))
        height = float(page.get("height_cm", 29.7))
        margin = page.get("margin_cm") or {}
        top = float(margin.get("top", 2.54))
        bottom = float(margin.get("bottom", 2.54))
        left = float(margin.get("left", 3.17))
        right = float(margin.get("right", 3.17))
        for section in self.doc.sections:
            section.page_width = Cm(width)
            section.page_height = Cm(height)
            section.top_margin = Cm(top)
            section.bottom_margin = Cm(bottom)
            section.left_margin = Cm(left)
            section.right_margin = Cm(right)
            self.text_width_cm = width - left - right
            footer = section.footer.paragraphs[0]
            footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_page_field(footer)

    def _run(self, paragraph, text: str, size_pt: float, bold: bool = False,
             italic: bool = False, cjk: str | None = None, latin: str | None = None):
        run = paragraph.add_run(text)
        run.bold = bold
        run.italic = italic
        run.font.size = Pt(size_pt)
        _set_fonts(run, cjk or self.style["body_cjk"], latin or self.style["body_latin"])
        return run

    def _para(self, text: str, *, size_pt: float, align: str = "justify",
              indent_chars: int = 0, space_before: float = 0.0,
              space_after: float = 0.0, line_spacing: float | None = None,
              keep_with_next: bool = False, bold: bool = False,
              cjk: str | None = None, latin: str | None = None):
        paragraph = self.doc.add_paragraph()
        pf = paragraph.paragraph_format
        paragraph.alignment = ALIGNS.get(align, WD_ALIGN_PARAGRAPH.JUSTIFY)
        pf.space_before = Pt(space_before)
        pf.space_after = Pt(space_after)
        pf.line_spacing = self.style["line_spacing"] if line_spacing is None else line_spacing
        pf.keep_with_next = keep_with_next
        if indent_chars:
            _set_indent_chars(paragraph, indent_chars, size_pt)
        if text:
            self._run(paragraph, text, size_pt, bold=bold, cjk=cjk, latin=latin)
        return paragraph

    # -- block types ---------------------------------------------------------
    def add_title(self, block: dict) -> None:
        self._para(self._text(block, "text"), size_pt=self.style["title_size_pt"],
                   align="center", space_before=0, space_after=12,
                   line_spacing=1.2, bold=True, cjk=self.style["heading_cjk"],
                   latin=self.style["heading_latin"])

    def add_authors(self, block: dict) -> None:
        self._para(self._text(block, "text"), size_pt=self.style["body_size_pt"],
                   align="center", space_after=6, line_spacing=1.2)

    def add_heading(self, block: dict) -> None:
        level = int(block.get("level", 1))
        sizes = self.style["heading_sizes_pt"]
        size = float(block.get("size_pt") or sizes[min(level, len(sizes)) - 1])
        self._para(self._text(block, "text"), size_pt=size,
                   align=block.get("align", "left"), space_before=12, space_after=6,
                   line_spacing=1.2, keep_with_next=True, bold=True,
                   cjk=self.style["heading_cjk"], latin=self.style["heading_latin"])

    def add_para(self, block: dict) -> None:
        indent = block.get("indent_chars")
        if indent is None:
            indent = self.style["first_line_indent_chars"]
        self._para(self._text(block, "text"), size_pt=float(block.get("size_pt") or self.style["body_size_pt"]),
                   align=block.get("align", "justify"), indent_chars=int(indent),
                   space_after=block.get("space_after", 0), line_spacing=block.get("line_spacing"))

    def add_note(self, block: dict) -> None:
        self._para(self._text(block, "text"), size_pt=self.style["note_size_pt"],
                   align=block.get("align", "left"), space_after=6, line_spacing=1.15)

    def add_pagebreak(self, block: dict) -> None:
        paragraph = self.doc.add_paragraph()
        paragraph.add_run().add_break(WD_BREAK.PAGE)

    def add_table(self, block: dict) -> None:
        rows, cols, path = read_table(block, self.base_dir)
        self.table_no += 1
        number = int(block.get("number") or self.table_no)
        caption = self._text(block, "caption")
        n_value = self._n_value(block, f"表 {number}", f"table{number}_n")
        self._caption(
            f"表 {number}  {caption}" + (f"（N={n_value}）" if n_value else ""),
            keep_with_next=True,
        )

        table = self.doc.add_table(rows=1, cols=len(cols))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.autofit = False
        _three_line_borders(table)

        header = table.rows[0]
        _repeat_header(header)
        _no_split(header)
        for i, col in enumerate(cols):
            cell = header.cells[i]
            label = col.get("label") or col["col"]
            paragraph = cell.paragraphs[0]
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.line_spacing = 1.0
            self._run(paragraph, label, self.style["table_size_pt"], bold=True)
        _header_rule(header)

        for row in rows:
            cells = table.add_row()
            _no_split(cells)
            for i, col in enumerate(cols):
                align = col.get("align") or ("left" if i == 0 else "right")
                if i == 0:
                    align = col.get("align", "left")
                paragraph = cells.cells[i].paragraphs[0]
                paragraph.alignment = ALIGNS.get(align, WD_ALIGN_PARAGRAPH.LEFT)
                paragraph.paragraph_format.line_spacing = 1.0
                text = format_cell(row.get(col["col"]), col)
                self._run(paragraph, text, self.style["table_size_pt"])

        note = self._text(block, "note", required=False)
        if note:
            self._para(note, size_pt=self.style["note_size_pt"], align="left",
                       space_after=6, line_spacing=1.15)
        else:
            self._para("", size_pt=self.style["note_size_pt"], align="left",
                       space_after=6)
        if block.get("source"):
            self.warnings.append(f"表 {number} built from {os.path.relpath(path, self.base_dir)}")

    def add_figure(self, block: dict) -> None:
        path = block.get("png")
        if not path:
            raise SpecError("figure block needs 'png' (Word cannot embed PDF)")
        if str(path).lower().endswith(".pdf"):
            raise SpecError(
                f"figure {path} is a PDF; Word cannot embed it — use the matching PNG"
            )
        full = path if os.path.isabs(path) else os.path.join(self.base_dir, path)
        if not os.path.exists(full):
            raise SpecError(f"figure image not found: {full}")
        self.figure_no += 1
        number = int(block.get("number") or self.figure_no)
        width_cm = block.get("width_cm")
        text_width = getattr(self, "text_width_cm", 15.0)
        if width_cm is None:
            # A 15 cm figure does not fit a 21 cm page with 3.17 cm margins
            # (14.66 cm of text). Default to the column, not to 15 cm.
            width_cm = min(float(self.style["figure_width_cm"]), text_width)
        width_cm = float(width_cm)
        if width_cm > text_width + 0.01:
            raise SpecError(
                f"figure {os.path.basename(full)} is {width_cm} cm wide but the text "
                f"column is {text_width:.2f} cm; narrow the margins or set width_cm "
                f"<= {text_width:.2f}"
            )

        px_width = _png_width(full)
        if px_width is not None and px_width < FIGURE_PX_MIN:
            self.warnings.append(
                f"figure {os.path.basename(full)} is {px_width} px wide; at "
                f"{width_cm:.1f} cm that is {px_width / (width_cm / 2.54):.0f} dpi, "
                f"below the 600 dpi floor"
            )

        holder = self.doc.add_paragraph()
        holder.alignment = WD_ALIGN_PARAGRAPH.CENTER
        holder.paragraph_format.space_before = Pt(6)
        holder.paragraph_format.space_after = Pt(3)
        holder.paragraph_format.keep_with_next = True
        holder.add_run().add_picture(full, width=Cm(width_cm))

        caption = self._text(block, "caption")
        n_value = self._n_value(block, f"图 {number}", f"fig{number}_n")
        self._caption(
            f"图 {number}  {caption}" + (f"（N={n_value}）" if n_value else ""),
            keep_with_next=bool(self._text(block, "note", required=False)),
        )
        note = self._text(block, "note", required=False)
        if note:
            self._para(note, size_pt=self.style["note_size_pt"], align="left",
                       space_after=6, line_spacing=1.15)
        self.figure_map.append(
            {"tag": f"图{number}", "title": caption, "image": os.path.abspath(full)}
        )

    # -- helpers -------------------------------------------------------------
    def _caption(self, text: str, keep_with_next: bool):
        return self._para(text, size_pt=self.style["caption_size_pt"], align="center",
                          space_before=6, space_after=3, line_spacing=1.15,
                          keep_with_next=keep_with_next)

    def _text(self, block: dict, key: str, required: bool = True) -> str:
        raw = block.get(key)
        if raw is None or raw == "":
            if required:
                raise SpecError(f"{block.get('type')} block needs '{key}'")
            return ""
        return resolve_text(str(raw), self.numbers, f"{block.get('type')}:{key}")

    def _n_value(self, block: dict, where: str, key: str) -> str:
        n = block.get("n")
        if n is None or n == "":
            return ""
        text = resolve_text(str(n), self.numbers, f"{where}:n")
        self.numbers_used[key] = text
        return text

    def build(self) -> None:
        blocks = self.spec.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            raise SpecError("spec needs a non-empty 'blocks' list")
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                raise SpecError(f"block {index} is not an object")
            kind = block.get("type")
            handler = {
                "title": self.add_title,
                "authors": self.add_authors,
                "heading": self.add_heading,
                "para": self.add_para,
                "note": self.add_note,
                "table": self.add_table,
                "figure": self.add_figure,
                "pagebreak": self.add_pagebreak,
            }.get(kind)
            if handler is None:
                raise SpecError(f"block {index}: unknown type {kind!r}")
            handler(block)


def _png_width(path: str):
    """Pixel width of a PNG, or None when the file is not a readable PNG."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(33)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return int.from_bytes(head[16:20], "big")
    except OSError:
        return None


def write_numbers(path: str, used: dict) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["key", "value", "source"])
        for key in sorted(used):
            writer.writerow([key, used[key], "assemble_manuscript.py"])


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a Word manuscript from a JSON spec (stage 6).")
    parser.add_argument("--spec", required=True, help="manuscript spec JSON")
    parser.add_argument("--out", required=True, help="output .docx")
    parser.add_argument("--numbers", default=None,
                        help="CSV with key,value used by {placeholders}")
    parser.add_argument("--figure-map", default=None,
                        help="where to write figure_map.json (default next to --out)")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate the spec and print the plan, write nothing")
    parser.add_argument("--version", action="version", version=SCRIPT_VERSION)
    args = parser.parse_args(argv)

    try:
        with open(args.spec, encoding="utf-8-sig") as fh:
            spec = json.load(fh)
    except FileNotFoundError:
        print(f"ERROR: spec not found: {args.spec}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"ERROR: spec is not valid JSON: {exc}", file=sys.stderr)
        return 2

    base_dir = os.path.dirname(os.path.abspath(args.spec))
    try:
        numbers = load_numbers(args.numbers)
        builder = Builder(spec, base_dir, numbers, args.out)
        builder.build()
    except SpecError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    for warning in builder.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)

    if args.dry_run:
        print(f"dry run: {len(spec['blocks'])} blocks, "
              f"{builder.table_no} table(s), {builder.figure_no} figure(s)")
        return 0

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    builder.doc.save(args.out)

    numbers_path = os.path.splitext(args.out)[0] + "_numbers.csv"
    write_numbers(numbers_path, builder.numbers_used)
    map_path = args.figure_map or os.path.join(out_dir or ".", "figure_map.json")
    with open(map_path, "w", encoding="utf-8") as fh:
        json.dump(builder.figure_map, fh, ensure_ascii=False, indent=2)

    print(f"wrote {args.out}")
    print(f"tables: {builder.table_no}  figures: {builder.figure_no}")
    print(f"numbers: {numbers_path}")
    print(f"figure map: {map_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())