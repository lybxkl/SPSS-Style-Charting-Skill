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
    cross-reference fields ([@tab:2] / [@fig:1] in any text become Word REF
    fields bound to the caption bookmarks), a bibliography block with hanging
    indents, and a TOC field;
  * ``<out>_numbers.csv`` — every N the document actually printed, so the
    manuscript, the tables and the figures share one source for that number;
  * ``figure_map.json`` — what ``export_pdf_hires.py`` needs to replace Word's
    downsampled bitmaps with the original 600 dpi files.

Nothing here decides content. If a number is missing, the build fails: a caption
that silently says "N=" with nothing after it is worse than a build that stops.
The reference engine typesets entries; it does not format citations (the entry
text and its order are the researcher's), and the TOC is a field Word fills on
update — the cached note says so instead of shipping a blank page.

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

SCRIPT_VERSION = "1.1.0"

try:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
except ImportError as exc:  # pragma: no cover - depends on the host
    print(f"ERROR: python-docx is required: {exc}", file=sys.stderr)
    raise SystemExit(2)

PLACEHOLDER = re.compile(r"\{([\w.\-]+)\}")
# Cross-reference markers in any rendered text: [@tab:2] / [@fig:1] become a
# Word REF field pointing at the caption bookmark, so the prose shows the
# number Word itself keeps current. The marker form is deliberately distinct
# from {key} number placeholders: [@tab:2] never pulls a value from numbers.csv.
XREF = re.compile(r"\[@(tab|fig):(\d+)\]")
# Near-miss shapes of the marker (wrong case, stray space): a typo'd marker
# must fail the build, never ship as literal bracket text. Matches exactly the
# marker family — [@anything] or [ @anything] — so it also catches the legal
# form, which is then filtered by the XREF check.
XREF_NEAR_MISS = re.compile(r"\[\s*@([^\]]*)\]")
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


def _bookmark(paragraph, name: str, bid: int) -> None:
    """Wrap the whole paragraph text range in a named bookmark.

    REF fields resolve to the text inside the bookmark range, so the bookmark
    covers exactly the runs already present in ``paragraph``. The start
    element goes AFTER ``w:pPr``: CT_P requires pPr to be the first child,
    and while Word tolerates it up front and re-normalises on save, other
    consumers (strict validators) do not have to.
    """
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bid))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bid))
    p = paragraph._p
    ppr = p.find(qn("w:pPr"))
    if ppr is not None:
        ppr.addnext(start)
    else:
        p.insert(0, start)
    p.append(end)


def _add_ref_field(paragraph, bookmark: str, cached: str, size_pt: float,
                   bold: bool, cjk: str, latin: str) -> None:
    """A REF field that hyperlinks to ``bookmark`` and shows ``cached`` until
    Word updates fields.

    begin / instr / separate / cached-text run / end: the cached text is a real
    run, so tools that read the document text (verify_numbers.py) see 「表 2」
    even before the first F9.
    """
    run = paragraph.add_run()
    _set_fonts(run, cjk, latin)
    run.font.size = Pt(size_pt)
    run.bold = bold
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" REF {bookmark} \\h "
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(sep)
    text_run = paragraph.add_run(cached)
    _set_fonts(text_run, cjk, latin)
    text_run.font.size = Pt(size_pt)
    text_run.bold = bold
    tail = paragraph.add_run()
    _set_fonts(tail, cjk, latin)
    tail.font.size = Pt(size_pt)
    tail.bold = bold
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    tail._r.append(end)


def _add_toc_field(paragraph, levels: str, note: str, cjk: str, latin: str) -> None:
    """A TOC field in a fldSimple wrapper with a readable cached note.

    Word (and LibreOffice) only fill a TOC on field update; the cached note
    tells the reader what to press instead of showing an empty page.
    """
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), f' TOC \\o "{levels}" \\h \\z \\u ')
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    rfonts = OxmlElement("w:rFonts")
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)
    rfonts.set(qn("w:cs"), latin)
    rfonts.set(qn("w:eastAsia"), cjk)
    rpr.append(rfonts)
    run.append(rpr)
    text = OxmlElement("w:t")
    text.set(qn("xml:space"), "preserve")
    text.text = note
    run.append(text)
    fld.append(run)
    paragraph._p.append(fld)


def _set_hanging_indent(paragraph, chars: float, size_pt: float) -> None:
    """Hanging indent in *characters* (w:hangingChars), the same way Word's
    「悬挂缩进 2 字符」 stores it, so it survives body-size changes."""
    ppr = paragraph._p.get_or_add_pPr()
    ind = ppr.find(qn("w:ind"))
    if ind is None:
        ind = OxmlElement("w:ind")
        ppr.append(ind)
    ind.set(qn("w:hangingChars"), str(int(chars * 100)))
    ind.set(qn("w:hanging"), str(int(round(size_pt * chars * 20))))


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
    from verify_dataset import read_csv
    try:
        header, rows = read_csv(path)
        if not {"key", "value"} <= set(header):
            raise SpecError("numbers CSV needs key,value columns")
        for row in rows:
            key = (row.get("key") or "").strip()
            if not key:
                raise SpecError("numbers CSV has an empty key")
            if key in numbers:
                raise SpecError(f"numbers CSV repeats key {key!r}")
            numbers[key] = (row.get("value") or "").strip()
            if not numbers[key]:
                raise SpecError(f"numbers CSV has an empty value for {key!r}")
    except ValueError as exc:
        raise SpecError(str(exc)) from exc
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
        if numbers[key] is None or not str(numbers[key]).strip():
            raise SpecError(f"{where}: empty value for {{{key}}}")
        return str(numbers[key])

    return PLACEHOLDER.sub(sub, text or "")


def resolve_asset(path: str, root: str, spec_dir: str) -> str:
    """Relative spec paths are from the project root, not the spec file's folder.

    A spec saved under draft/ must still point at output/tables/... in the
    project. If that file is absent, the old location next to the spec is
    still accepted.
    """
    if os.path.isabs(path):
        return path
    at_root = os.path.normpath(os.path.join(root, path))
    if os.path.exists(at_root):
        return at_root
    at_spec = os.path.normpath(os.path.join(spec_dir, path))
    if os.path.exists(at_spec):
        return at_spec
    return at_root


def read_table(spec: dict, base_dir: str, root: str | None = None) -> tuple[list, list, str]:
    path = spec.get("csv")
    if not path:
        raise SpecError("table block needs 'csv'")
    path = resolve_asset(path, root or base_dir, base_dir)
    if not os.path.exists(path):
        raise SpecError(f"table CSV not found: {path}")
    from verify_dataset import read_csv
    try:
        header, rows = read_csv(path)
    except ValueError as exc:
        raise SpecError(str(exc)) from exc
    if not rows:
        raise SpecError(f"table CSV has no rows: {path}")
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
        self.table_map: list[dict] = []
        self.warnings: list[str] = []
        self.table_no = 0
        self.figure_no = 0
        # Cross-reference plumbing: table/figure numbers are assigned in a
        # pre-scan (respecting explicit "number" fields and rejecting
        # duplicates), so prose that cites [@tab:2] BEFORE the table block can
        # still be checked and rendered as a REF field.
        self._tab_numbers, self._fig_numbers = self._assign_numbers()
        self._tab_idx = 0
        self._fig_idx = 0
        self._bookmark_ids = 0
        self._validate_xrefs()
        self.doc = Document()
        self._page_setup()

    # -- numbering pre-scan --------------------------------------------------
    def _assign_numbers(self) -> tuple[list[int], list[int]]:
        blocks = self.spec.get("blocks") or []
        tabs: list[int] = []
        figs: list[int] = []
        seen_t: set[int] = set()
        seen_f: set[int] = set()
        for block in blocks:
            if not isinstance(block, dict):
                continue  # build() reports non-object blocks with its own error
            if block.get("type") == "table":
                tabs_count = len(tabs) + 1
                number = int(block.get("number") or tabs_count)
                if number in seen_t:
                    raise SpecError(f"table number {number} is used twice; "
                                    f"explicit 'number' fields must stay unique")
                seen_t.add(number)
                tabs.append(number)
            elif block.get("type") == "figure":
                figs_count = len(figs) + 1
                number = int(block.get("number") or figs_count)
                if number in seen_f:
                    raise SpecError(f"figure number {number} is used twice; "
                                    f"explicit 'number' fields must stay unique")
                seen_f.add(number)
                figs.append(number)
        # explicit + auto numbering can interleave into non-monotonic order
        # (表5 then 表2); that is legal (verify_numbers checks reference
        # coverage, not order) but almost always a typo, so say it loudly
        for word, seq in (("表", tabs), ("图", figs)):
            if seq != sorted(seq):
                self.warnings.append(
                    f"{word}号按 blocks 顺序非单调：{('、'.join(f'{word}{n}' for n in seq))}"
                    f"——若非有意，请检查显式 number 字段")
        return tabs, figs

    def _validate_xrefs(self) -> None:
        """Every [@tab:N] / [@fig:N] in any rendered text must name a real
        table/figure number, and anything that merely LOOKS like a marker
        (wrong case, stray space) must fail too: a typo'd reference shipping
        literal bracket text is worse than a stopped build."""
        blocks = self.spec.get("blocks") or []
        for index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            for key in ("text", "caption", "note", "title"):
                raw = block.get(key)
                if not isinstance(raw, str):
                    continue
                where = f"block {index} ({key})"
                self._check_xref_text(raw, where)

    def _check_xref_text(self, text: str, where: str) -> None:
        for m in XREF.finditer(text):
            kind, number = m.group(1), int(m.group(2))
            known = self._tab_numbers if kind == "tab" else self._fig_numbers
            if number not in known:
                word = "表" if kind == "tab" else "图"
                raise SpecError(
                    f"{where}: {m.group(0)} cites {word}{number}, but the "
                    f"manuscript has no {word} numbered {number}"
                )
        for m in XREF_NEAR_MISS.finditer(text):
            token = m.group(0)
            if not XREF.fullmatch(token):
                raise SpecError(
                    f"{where}: {token!r} looks like a cross-reference marker but "
                    f"does not match [@tab:N] / [@fig:N] (lowercase, no spaces); "
                    f"fix the marker or remove the brackets"
                )

    # -- document scaffolding ------------------------------------------------
    def _page_setup(self) -> None:
        page = self.spec.get("page") or {}
        width = float(page.get("width_cm", 21.0))
        height = float(page.get("height_cm", 29.7))
        margin = page.get("margin_cm") or {}
        if not isinstance(margin, dict):
            # "margin_cm": 3.17 is a perfectly natural thing to write; failing
            # with "'float' object has no attribute 'get'" is not an answer.
            margin = {"top": margin, "bottom": margin, "left": margin,
                      "right": margin}
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

    def _add_text(self, paragraph, text: str, size_pt: float, bold: bool = False,
                  cjk: str | None = None, latin: str | None = None):
        """Add ``text`` (already {key}-resolved) as runs, turning every
        [@tab:N]/[@fig:N] marker into a REF field run group.

        The runtime guard re-checks every marker against the assigned numbers
        and rejects near-miss shapes: this is the path the references CSV
        takes, and its rows never see the spec-level pre-scan.
        """
        if not text:
            return
        cjk = cjk or self.style["body_cjk"]
        latin = latin or self.style["body_latin"]
        pos = 0
        for m in XREF.finditer(text):
            if m.start() > pos:
                self._run(paragraph, text[pos:m.start()], size_pt, bold=bold,
                          cjk=cjk, latin=latin)
            kind, number = m.group(1), int(m.group(2))
            known = self._tab_numbers if kind == "tab" else self._fig_numbers
            if number not in known:
                word = "表" if kind == "tab" else "图"
                raise SpecError(
                    f"{word}{number} is cited here but the manuscript has no "
                    f"{word} numbered {number}")
            word = "表" if kind == "tab" else "图"
            _add_ref_field(paragraph, f"_Ref{'Tab' if kind == 'tab' else 'Fig'}{number}",
                           f"{word}{number}", size_pt, bold, cjk, latin)
            pos = m.end()
        if pos < len(text):
            self._run(paragraph, text[pos:], size_pt, bold=bold, cjk=cjk, latin=latin)
        for m in XREF_NEAR_MISS.finditer(text):
            if not XREF.fullmatch(m.group(0)):
                raise SpecError(
                    f"{m.group(0)!r} looks like a cross-reference marker but "
                    f"does not match [@tab:N] / [@fig:N]")

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
            self._add_text(paragraph, text, size_pt, bold=bold, cjk=cjk, latin=latin)
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
        if not 1 <= level <= 9:
            raise SpecError("heading level must be between 1 and 9")
        sizes = self.style["heading_sizes_pt"]
        size = float(block.get("size_pt") or sizes[min(level, len(sizes)) - 1])
        paragraph = self._para(self._text(block, "text"), size_pt=size,
                   align=block.get("align", "left"), space_before=12, space_after=6,
                   line_spacing=1.2, keep_with_next=True, bold=True,
                   cjk=self.style["heading_cjk"], latin=self.style["heading_latin"])
        paragraph.style = f"Heading {level}"
        for run in paragraph.runs:
            run.font.color.rgb = RGBColor(0, 0, 0)

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
        rows, cols, path = read_table(block, self.base_dir, getattr(self, "root", None))
        if self._tab_idx >= len(self._tab_numbers):
            raise SpecError("table numbering desync: more table blocks than pre-scanned")
        number = self._tab_numbers[self._tab_idx]
        self._tab_idx += 1
        self.table_no += 1
        caption = self._text(block, "caption")
        self.table_map.append({"tag": f"表{number}", "title": caption, "file": path})
        n_value = self._n_value(block, f"表 {number}", f"table{number}_n")
        self._caption("tab", number,
                      "  " + caption + (f"（N={n_value}）" if n_value else ""),
                      keep_with_next=True)

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
        full = resolve_asset(path, getattr(self, "root", None) or self.base_dir, self.base_dir)
        if not os.path.exists(full):
            raise SpecError(f"figure image not found: {full}")
        if self._fig_idx >= len(self._fig_numbers):
            raise SpecError("figure numbering desync: more figure blocks than pre-scanned")
        number = self._fig_numbers[self._fig_idx]
        self._fig_idx += 1
        self.figure_no += 1
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
        if px_width is not None and px_width / (width_cm / 2.54) < 600 * .995:
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
        self._caption("fig", number,
                      "  " + caption + (f"（N={n_value}）" if n_value else ""),
                      keep_with_next=bool(self._text(block, "note", required=False)))
        note = self._text(block, "note", required=False)
        if note:
            self._para(note, size_pt=self.style["note_size_pt"], align="left",
                       space_after=6, line_spacing=1.15)
        self.figure_map.append(
            {"tag": f"图{number}", "title": caption, "image": os.path.abspath(full)}
        )

    # -- helpers -------------------------------------------------------------
    def _caption(self, kind: str, number: int, tail: str,
                 keep_with_next: bool):
        """A caption paragraph whose 「表 N」/「图 N」 prefix is bookmarked, so
        prose REF fields can cite the number Word keeps current."""
        word = "表" if kind == "tab" else "图"
        paragraph = self.doc.add_paragraph()
        pf = paragraph.paragraph_format
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf.space_before = Pt(6)
        pf.space_after = Pt(3)
        pf.line_spacing = 1.15
        pf.keep_with_next = keep_with_next
        size = self.style["caption_size_pt"]
        self._run(paragraph, f"{word} {number}", size)
        self._bookmark_ids += 1
        _bookmark(paragraph, f"_Ref{'Tab' if kind == 'tab' else 'Fig'}{number}",
                  self._bookmark_ids)
        self._add_text(paragraph, tail, size)
        return paragraph

    def add_references(self, block: dict) -> None:
        """A bibliography section from a CSV of already-formatted entries.

        The engine typesets (hanging indent, optional [n] numbering) but does
        not format citations: every entry's text is the researcher's own
        GB/T 7714 / APA / Vancouver string, and the order is the CSV's order.
        """
        title = block.get("title")
        if title:
            self.add_heading({"level": int(block.get("level", 1)),
                              "text": str(title)})
        rows, path = self._read_reference_rows(block)
        numbering = block.get("numbering", "bracket")
        if numbering not in ("bracket", "none"):
            raise SpecError("references numbering must be 'bracket' or 'none'")
        hanging = float(block.get("hanging_chars", 2))
        if not 0 <= hanging <= 10:
            raise SpecError("references hanging_chars must be within 0-10")
        size = float(block.get("size_pt") or self.style["note_size_pt"])
        for i, text in enumerate(rows, start=1):
            paragraph = self.doc.add_paragraph()
            pf = paragraph.paragraph_format
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            pf.space_after = Pt(3)
            pf.line_spacing = 1.2
            _set_hanging_indent(paragraph, hanging, size)
            prefix = f"[{i}] " if numbering == "bracket" else ""
            if prefix:
                self._run(paragraph, prefix, size)
            self._add_text(paragraph, text, size)
        if len(rows) > 1:
            seen = {}
            for i, text in enumerate(rows, start=1):
                if text in seen:
                    self.warnings.append(
                        f"references rows {seen[text]} and {i} are identical: "
                        f"{text[:60]}…")
                else:
                    seen[text] = i

    def _read_reference_rows(self, block: dict) -> tuple[list[str], str]:
        path = block.get("csv")
        if not path:
            raise SpecError("references block needs 'csv'")
        full = resolve_asset(path, getattr(self, "root", None) or self.base_dir,
                             self.base_dir)
        if not os.path.exists(full):
            raise SpecError(f"references CSV not found: {full}")
        from verify_dataset import read_csv
        try:
            header, rows = read_csv(full)
        except ValueError as exc:
            raise SpecError(str(exc)) from exc
        if "text" not in header:
            raise SpecError(
                f"references CSV needs a 'text' column; available: {', '.join(header)}")
        texts = []
        for i, row in enumerate(rows, start=2):
            text = (row.get("text") or "").strip()
            if not text:
                raise SpecError(f"references CSV row {i} has an empty text")
            where = f"references row {i}"
            texts.append(resolve_text(text, self.numbers, where))
        if not texts:
            raise SpecError(f"references CSV has no rows: {full}")
        return texts, full

    def add_toc(self, block: dict) -> None:
        """A Table of Contents field. Word fills it on field update; the
        cached note says so instead of shipping a blank page."""
        levels = str(block.get("levels", "1-3"))
        if not re.fullmatch(r"[1-9]-[1-9]", levels) or int(levels[0]) > int(levels[-1]):
            raise SpecError("toc levels must look like '1-3' with low <= high")
        paragraph = self.doc.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(6)
        paragraph.paragraph_format.space_after = Pt(3)
        _add_toc_field(
            paragraph, levels,
            f"（目录域：打开文档后按 Ctrl+A 全选、F9 更新；域参数 {levels} 级标题）",
            self.style["body_cjk"], self.style["body_latin"])
        self._para("注：本页为 Word 目录域，导出 PDF 前务必先更新域，否则目录为空。",
                   size_pt=self.style["note_size_pt"], align="left",
                   space_after=6, line_spacing=1.15)

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
                "references": self.add_references,
                "toc": self.add_toc,
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


def merge_name_map(path: str, entries: list, wrapper: str) -> None:
    """Merge titled display-name entries into a map, keyed by normalized file path."""
    existing = []
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig") as fh:
                data = json.load(fh)
            existing = data if isinstance(data, list) else (data.get(wrapper) or [])
        except (OSError, ValueError) as exc:
            print(f"WARNING: {path} unreadable ({exc}); left untouched", file=sys.stderr)
            return

    def norm(p: str) -> str:
        return os.path.normpath(str(p)).replace("\\", "/")

    merged = {norm(it.get("file") or it.get("image") or ""): it
              for it in existing if isinstance(it, dict)}
    for it in entries:
        if it.get("file"):
            merged[norm(it["file"])] = it
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(list(merged.values()), fh, ensure_ascii=False, indent=2)


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a Word manuscript from a JSON spec (stage 6).")
    parser.add_argument("--spec", required=True, help="manuscript spec JSON")
    parser.add_argument("--root", default=".",
                        help="project root for relative csv/png paths (default: working directory)")
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

    spec_dir = os.path.dirname(os.path.abspath(args.spec))
    root = os.path.abspath(args.root)
    try:
        numbers_path = args.numbers
        if numbers_path and not os.path.isabs(numbers_path):
            numbers_path = resolve_asset(numbers_path, root, spec_dir)
        numbers = load_numbers(numbers_path)
        builder = Builder(spec, spec_dir, numbers, args.out)
        builder.root = root
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
    table_map_path = os.path.join(root, "output", "table_map.json")
    merge_name_map(table_map_path, builder.table_map, "tables")

    print(f"wrote {args.out}")
    print(f"tables: {builder.table_no}  figures: {builder.figure_no}")
    print(f"numbers: {numbers_path}")
    print(f"figure map: {map_path}")
    print(f"table map: {table_map_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
