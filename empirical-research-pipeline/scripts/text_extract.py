# -*- coding: utf-8 -*-
"""Universal text extraction and inspection for research materials.

Supports PDF, DOCX, ODT, PPTX, XLSX/XLSM, HTML, plain text, and structured
data files. Images and audio/video are inventoried but require OCR or
transcription before text analysis. No domain assumptions are made here.
"""
from __future__ import annotations

import html
import os
import re
import zipfile
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

TEXT_EXTS = {
    "txt", "text", "md", "markdown", "rst", "tex", "log",
    "csv", "tsv", "json", "jsonl", "ndjson", "xml", "yaml", "yml", "rtf",
}
PDF_EXTS = {"pdf"}
DOCX_EXTS = {"docx", "docm"}
ODT_EXTS = {"odt"}
PPTX_EXTS = {"pptx", "pptm"}
XLSX_EXTS = {"xlsx", "xlsm"}
HTML_EXTS = {"html", "htm", "xhtml"}
IMAGE_EXTS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp", "gif", "heic"}
MEDIA_EXTS = {"mp3", "wav", "m4a", "aac", "flac", "ogg", "mp4", "mov", "avi", "mkv", "webm"}
ARCHIVE_EXTS = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz"}
LEGACY_OFFICE_EXTS = {"doc", "xls", "ppt"}
STRUCTURED_EXTS = {"csv", "tsv", "json", "jsonl", "ndjson", "xlsx", "xlsm"}

SUPPORTED_EXTS = (
    TEXT_EXTS | PDF_EXTS | DOCX_EXTS | ODT_EXTS | PPTX_EXTS
    | XLSX_EXTS | HTML_EXTS | IMAGE_EXTS | MEDIA_EXTS | ARCHIVE_EXTS
    | LEGACY_OFFICE_EXTS
)
TEXTUAL_EXTS = TEXT_EXTS | PDF_EXTS | DOCX_EXTS | ODT_EXTS | PPTX_EXTS | XLSX_EXTS | HTML_EXTS


def win_path(path: str) -> str:
    path = os.path.abspath(path)
    if os.name == "nt" and len(path) > 240 and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + path
    return path


def ext_of(path: str) -> str:
    return Path(path).suffix.lower().lstrip(".")


def kind_of(path: str) -> str:
    ext = ext_of(path)
    if ext in PDF_EXTS:
        return "pdf"
    if ext in DOCX_EXTS:
        return "docx"
    if ext in ODT_EXTS:
        return "odt"
    if ext in PPTX_EXTS:
        return "pptx"
    if ext in XLSX_EXTS:
        return "spreadsheet"
    if ext in HTML_EXTS:
        return "html"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in MEDIA_EXTS:
        return "media"
    if ext in ARCHIVE_EXTS:
        return "archive"
    if ext in LEGACY_OFFICE_EXTS:
        return "legacy_office"
    if ext in TEXT_EXTS:
        return "text"
    return "unknown"


def decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gb18030", "big5", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def strip_markup(value: str) -> str:
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n\s*\n+", "\n", value)
    return value.strip()


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.images = 0
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        elif tag == "img":
            self.images += 1
        elif tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        elif tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


RTF_IGNORE_GROUPS = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "header",
    "footer", "footnote", "annotation", "field", "fldinst", "listtable",
    "listoverridetable", "rsidtbl", "generator", "xmlnstbl", "themedata",
    "colorschememapping", "datastore", "latentstyles", "mmathPr",
}
RTF_CODEPAGES = {936: "gbk", 950: "big5", 65001: "utf-8", 1252: "cp1252", 1251: "cp1251"}


def _rtf_decode_bytes(buf: bytes, codepage: str) -> str:
    for enc in (codepage, "gb18030", "cp1252"):
        try:
            return buf.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return buf.decode("utf-8", errors="replace")


def _decode_rtf(raw: bytes) -> str:
    """Decode RTF text, including Chinese escapes and ignorable destinations.

    A regex-only pass loses `\\'d6\\'d0`-style GBK bytes and leaves font/color
    tables in the text, so this walks groups and control words instead.
    """
    s = raw.decode("latin-1")
    m = re.search(r"\\ansicpg(\d+)", s)
    codepage = RTF_CODEPAGES.get(int(m.group(1)), "cp1252") if m else "cp1252"
    out: list[str] = []
    bytebuf = bytearray()
    skip_stack: list[bool] = []
    skip_depth = 0
    uc_skip = 1
    i, n = 0, len(s)

    def flush() -> None:
        nonlocal bytebuf
        if bytebuf:
            out.append(_rtf_decode_bytes(bytes(bytebuf), codepage))
            bytebuf = bytearray()

    while i < n:
        c = s[i]
        if c == "{":
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            ignore = skip_depth > 0
            if not ignore and s.startswith("\\*", j):
                ignore = True
            elif not ignore:
                dest = re.match(r"\\([a-zA-Z]+)", s[j:])
                if dest and dest.group(1).lower() in RTF_IGNORE_GROUPS:
                    ignore = True
            skip_stack.append(ignore)
            skip_depth += 1 if ignore else 0
            i += 1
        elif c == "}":
            if skip_stack:
                was_skip = skip_stack.pop()
                skip_depth -= 1 if was_skip else 0
            i += 1
        elif c == "\\":
            if i + 1 >= n:
                break
            nxt = s[i + 1]
            if nxt in "\\{}":
                if not skip_depth:
                    flush()
                    out.append(nxt)
                i += 2
            elif nxt == "'":
                hexv = s[i + 2:i + 4]
                if re.fullmatch(r"[0-9a-fA-F]{2}", hexv):
                    if not skip_depth:
                        bytebuf.append(int(hexv, 16))
                    i += 4
                else:
                    i += 2
            elif nxt == "~":
                if not skip_depth:
                    flush()
                    out.append("\u00a0")
                i += 2
            elif nxt in "-_":
                if not skip_depth and nxt == "_":
                    flush()
                    out.append("-")
                i += 2
            elif nxt.isalpha():
                j = i + 1
                while j < n and s[j].isalpha():
                    j += 1
                word = s[i + 1:j].lower()
                k = j
                sign = ""
                if k < n and s[k] == "-":
                    sign = "-"
                    k += 1
                start = k
                while k < n and s[k].isdigit():
                    k += 1
                number = sign + s[start:k]
                if k < n and s[k] == " ":
                    k += 1
                if not skip_depth:
                    if word == "uc":
                        uc_skip = int(number or "1")
                    elif word in {"par", "line", "sect", "page"}:
                        flush()
                        out.append("\n")
                    elif word == "tab":
                        flush()
                        out.append("\t")
                    elif word == "u":
                        flush()
                        try:
                            out.append(chr(int(number) % 65536))
                        except ValueError:
                            pass
                        # `\uN` may be followed by a fallback character.
                        fallback = 0
                        while fallback < uc_skip and k < n:
                            if s[k] == "\\" and k + 1 < n:
                                if s[k + 1] == "'" and re.fullmatch(
                                        r"[0-9a-fA-F]{2}", s[k + 2:k + 4] or ""):
                                    k += 4
                                else:
                                    k += 2
                            elif s[k] not in "{}":
                                k += 1
                            else:
                                break
                            fallback += 1
                    elif word in {"emdash", "endash", "bullet", "lquote", "rquote"}:
                        flush()
                        out.append({"emdash": "\u2014", "endash": "\u2013",
                                    "bullet": "\u2022", "lquote": "\u2018",
                                    "rquote": "\u2019"}[word])
                i = k
            else:
                i += 2
        elif c in "\r\n":
            i += 1
        else:
            if not skip_depth:
                if ord(c) > 127:
                    bytebuf.append(ord(c))
                else:
                    flush()
                    out.append(c)
            i += 1
    flush()
    text = "".join(out)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _xml_text(raw: bytes) -> str:
    value = raw.decode("utf-8", errors="ignore")
    value = re.sub(r"<(w:p|a:p|text:p|text:h|w:br)[^>]*>", "\n", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r"\n\s*\n+", "\n", value)
    return value.strip()


@contextmanager
def _open_zip(path: str):
    with open(win_path(path), "rb") as fh:
        with zipfile.ZipFile(fh) as zf:
            yield zf


def _zip_text(path: str, members: list[str]) -> tuple[str, int, int]:
    text_parts: list[str] = []
    images = 0
    with _open_zip(path) as zf:
        names = zf.namelist()
        images = sum(1 for n in names if re.search(r"(^|/)(media|Pictures)/", n))
        for member in members:
            if member in names:
                text_parts.append(_xml_text(zf.read(member)))
    return "\n".join(p for p in text_parts if p), images, len(members)


def _inspect_pdf(path: str) -> dict:
    rec = {"pages": None, "chars": None, "images": None, "encrypted": 0, "error": ""}
    if fitz is None:
        rec["error"] = "PyMuPDF not installed; pip install pymupdf"
        return rec
    try:
        doc = fitz.open(win_path(path))
    except Exception as exc:
        rec["error"] = f"open:{type(exc).__name__}:{exc}"[:300]
        return rec
    try:
        rec["pages"] = doc.page_count
        rec["encrypted"] = int(bool(doc.is_encrypted) or bool(doc.needs_pass))
        if doc.needs_pass:
            return rec
        rec["chars"] = sum(len(page.get_text("text")) for page in doc)
        rec["images"] = sum(len(page.get_images(full=True)) for page in doc)
    except Exception as exc:
        rec["error"] = f"read:{type(exc).__name__}:{exc}"[:300]
    finally:
        doc.close()
    return rec


def _inspect_text(path: str) -> dict:
    rec = {"pages": 1, "chars": None, "images": 0, "encrypted": 0, "error": ""}
    try:
        raw = open(win_path(path), "rb").read()
    except Exception as exc:
        rec["error"] = f"open:{type(exc).__name__}:{exc}"[:300]
        return rec
    ext = ext_of(path)
    if ext == "rtf":
        text = _decode_rtf(raw)
    else:
        text = decode_bytes(raw)
    rec["chars"] = len(text)
    return rec


def _inspect_html(path: str) -> dict:
    rec = {"pages": 1, "chars": None, "images": 0, "encrypted": 0, "error": ""}
    try:
        parser = _HTMLText()
        parser.feed(decode_bytes(open(win_path(path), "rb").read()))
        text = "".join(parser.parts)
        rec["chars"] = len(re.sub(r"\s+", " ", text).strip())
        rec["images"] = parser.images
    except Exception as exc:
        rec["error"] = f"read:{type(exc).__name__}:{exc}"[:300]
    return rec


def _inspect_docx(path: str, ext: str) -> dict:
    rec = {"pages": None, "chars": None, "images": None, "encrypted": 0, "error": ""}
    try:
        if ext in {"docx", "docm"}:
            text, images, _ = _zip_text(path, ["word/document.xml"])
        elif ext == "odt":
            text, images, _ = _zip_text(path, ["content.xml"])
        else:  # pptx
            with _open_zip(path) as zf:
                slides = sorted(
                    (n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                    key=lambda n: int(re.search(r"(\d+)", n).group(1)),
                )
            text, images, pages = _zip_text(path, slides)
            rec["pages"] = pages
        rec["chars"] = len(text)
        rec["images"] = images
    except Exception as exc:
        rec["error"] = f"read:{type(exc).__name__}:{exc}"[:300]
    return rec


def _inspect_xlsx_zip(path: str) -> dict:
    """Raw-XML fallback; also catches formula-only workbooks without cached values."""
    rec = {"pages": None, "chars": None, "images": None, "encrypted": 0, "error": ""}
    with _open_zip(path) as zf:
        names = zf.namelist()
        shared = ""
        if "xl/sharedStrings.xml" in names:
            shared = _xml_text(zf.read("xl/sharedStrings.xml"))
        sheets = sorted(
            (n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
            key=lambda n: int(re.search(r"(\d+)", n).group(1)),
        )
        text = shared
        for n in sheets:
            text += "\n" + _xml_text(zf.read(n))
        rec["pages"] = len(sheets)
        rec["chars"] = len(text)
        rec["images"] = sum(1 for n in names if n.startswith("xl/media/"))
    return rec


def _inspect_xlsx(path: str) -> dict:
    rec = {"pages": None, "chars": None, "images": None, "encrypted": 0, "error": ""}
    primary_error = ""
    try:
        import openpyxl  # optional, more reliable than raw XML when values are cached
        wb = openpyxl.load_workbook(win_path(path), read_only=True, data_only=True)
        try:
            pages = len(wb.worksheets)
            chars = 0
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    chars += sum(len(str(v)) for v in row if v is not None)
            rec["pages"] = pages
            rec["chars"] = chars
        finally:
            wb.close()
        with _open_zip(path) as zf:
            rec["images"] = sum(1 for n in zf.namelist() if n.startswith("xl/media/"))
        if chars > 0:
            return rec
    except ImportError:
        pass
    except Exception as exc:
        primary_error = f"read:{type(exc).__name__}:{exc}"[:300]
    # Formula-only sheets and openpyxl failures still need an auditable status.
    try:
        fallback = _inspect_xlsx_zip(path)
        if (fallback.get("chars") or 0) > 0 or not primary_error:
            return fallback
    except Exception as exc:
        if not primary_error:
            primary_error = f"read:{type(exc).__name__}:{exc}"[:300]
    rec["error"] = primary_error
    return rec


def inspect_file(path: str) -> dict:
    """Return pages/chars/images/encrypted/error for one file."""
    ext = ext_of(path)
    kind = kind_of(path)
    if kind == "image":
        return {"pages": 1, "chars": 0, "images": 1, "encrypted": 0, "error": ""}
    if kind == "media":
        return {"pages": None, "chars": 0, "images": 0, "encrypted": 0,
                "error": "audio/video requires transcription or frame extraction first"}
    if kind == "archive":
        return {"pages": None, "chars": None, "images": None, "encrypted": 0,
                "error": "archive: extract first, then audit the extracted files"}
    if kind == "legacy_office":
        return {"pages": None, "chars": None, "images": None, "encrypted": 0,
                "error": "legacy Office format: convert .doc/.xls/.ppt to docx/xlsx/pptx first"}
    if kind == "pdf":
        return _inspect_pdf(path)
    if kind in {"docx", "odt", "pptx"}:
        return _inspect_docx(path, ext)
    if kind == "spreadsheet":
        return _inspect_xlsx(path)
    if kind == "html":
        return _inspect_html(path)
    if kind == "text":
        return _inspect_text(path)
    return {"pages": None, "chars": None, "images": None, "encrypted": 0,
            "error": f"unsupported extension: .{ext or '(none)'}"}


def extract_text(path: str) -> str:
    """Extract plain text for coding. Raises ValueError for non-text materials."""
    kind = kind_of(path)
    ext = ext_of(path)
    if kind == "pdf":
        if fitz is None:
            raise ValueError("PyMuPDF not installed; pip install pymupdf")
        doc = fitz.open(win_path(path))
        try:
            if doc.needs_pass:
                raise ValueError("encrypted PDF: provide a decrypted copy")
            return "\n".join(page.get_text("text") for page in doc)
        finally:
            doc.close()
    if kind == "docx":
        text, _, _ = _zip_text(path, ["word/document.xml"])
        return text
    if kind == "odt":
        text, _, _ = _zip_text(path, ["content.xml"])
        return text
    if kind == "pptx":
        with _open_zip(path) as zf:
            slides = sorted(
                (n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                key=lambda n: int(re.search(r"(\d+)", n).group(1)),
            )
        text, _, _ = _zip_text(path, slides)
        return text
    if kind == "html":
        parser = _HTMLText()
        parser.feed(decode_bytes(open(win_path(path), "rb").read()))
        return strip_markup("".join(parser.parts))
    if ext == "rtf":
        return _decode_rtf(open(win_path(path), "rb").read())
    if kind == "text":
        return decode_bytes(open(win_path(path), "rb").read())
    if kind == "spreadsheet":
        raise ValueError("tabular spreadsheet: use auto_stats / CSV pipeline, not document coding")
    if kind == "image":
        raise ValueError("image_only: run OCR first and audit the extracted text")
    if kind == "media":
        raise ValueError("audio/video: transcribe first and audit the transcript")
    if kind == "archive":
        raise ValueError("archive: extract first")
    raise ValueError(f"unsupported extension: .{ext or '(none)'}")
