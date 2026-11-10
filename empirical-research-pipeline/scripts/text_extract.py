# -*- coding: utf-8 -*-
"""Universal text extraction and inspection for research materials.

Supports PDF, DOCX, ODT, PPTX, XLSX/XLSM, HTML, plain text, and structured
data files. Images and audio/video are inventoried but require OCR or
transcription before text analysis. No domain assumptions are made here.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import zipfile
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path

# Stamped into the run output so an artefact names the code that made it.
SCRIPT_VERSION = "2.0.0"

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

# A line that is nothing but "3/26" (page stamp) carries no analyzable content.
PAGE_NO_RE = re.compile(r"^\s*\d+\s*[/／]\s*\d+\s*$")
MAX_TEXT_BYTES = 50 * 1024 * 1024
FALLBACK_ENCODING = "latin-1(fallback)"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def effective_chars(text: str) -> int:
    """Visible characters after dropping page-number-only lines and whitespace.

    `chars` stays the raw string length for backwards compatibility; this is
    the number to compare against `--min-chars` and to report as "字数".
    """
    if not text:
        return 0
    lines = [line for line in text.splitlines() if not PAGE_NO_RE.match(line)]
    return len(re.sub(r"\s", "", "\n".join(lines)))


def _rec(pages=None, chars=None, images=None) -> dict:
    """Build a uniform inspect_file() record so every caller sees every key."""
    return {"pages": pages, "chars": chars, "chars_effective": None,
            "images": images, "encrypted": 0, "encoding": "",
            "error": "", "error_kind": ""}


def _exc_kind(exc: BaseException) -> str:
    return "permission" if isinstance(exc, PermissionError) else "broken"


def is_ole_container(path: str) -> bool:
    """True for CFB/OLE files: password-protected Office is not a zip archive."""
    try:
        with open(win_path(path), "rb") as fh:
            return fh.read(8) == OLE_MAGIC
    except OSError:
        return False


def _read_bytes(path: str) -> bytes:
    """Read a file once, always closing the handle."""
    with open(win_path(path), "rb") as fh:
        return fh.read()


def win_path(path: str) -> str:
    path = os.path.abspath(path)
    if os.name == "nt" and len(path) > 240 and not path.startswith("\\\\?\\"):
        if path.startswith("\\\\"):
            # UNC shares need \\?\UNC\server\share, not \\?\\\server\share.
            return "\\\\?\\UNC\\" + path.lstrip("\\")
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


def decode_bytes_ex(raw: bytes) -> tuple[str, str]:
    """Decode bytes and report the encoding that was actually used.

    latin-1 accepts *any* byte sequence, so a fallback here is not proof that
    the file is text. It is labelled ``latin-1(fallback)`` and callers surface
    a mojibake warning instead of pretending the decode succeeded.
    """
    for enc in ("utf-8-sig", "gb18030", "big5", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            return text, FALLBACK_ENCODING if enc == "latin-1" else enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(replace)"


def decode_bytes(raw: bytes) -> str:
    return decode_bytes_ex(raw)[0]


def looks_binary(raw: bytes, sample_size: int = 8192) -> bool:
    """True when a sample looks like binary data (NUL bytes plus control chars).

    Only consulted after a latin-1 fallback, so UTF-16 text with many NUL
    bytes (which decodes cleanly through the utf-16 codec) never reaches here.
    """
    sample = raw[:sample_size]
    if not sample:
        return False
    ctrl = sum(1 for b in sample if b < 9 or 13 < b < 32)
    return sample.count(0) > 0 and ctrl / len(sample) > 0.05


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


def _pdf_pages_text(doc) -> tuple[list[str], int]:
    """Extract text page by page, tolerating single damaged pages.

    `sort=True` restores reading order for multi-column layouts; a broken page
    becomes an empty string instead of failing the whole document.
    """
    texts: list[str] = []
    bad = 0
    for page in doc:
        try:
            texts.append(page.get_text("text", sort=True))
        except Exception:
            bad += 1
            texts.append("")
    return texts, bad


def _inspect_pdf(path: str) -> dict:
    rec = _rec()
    if fitz is None:
        rec["error"] = "PyMuPDF not installed; pip install pymupdf"
        rec["error_kind"] = "missing_dep"
        return rec
    try:
        doc = fitz.open(win_path(path))
    except Exception as exc:
        rec["error"] = f"open:{type(exc).__name__}:{exc}"[:300]
        rec["error_kind"] = _exc_kind(exc)
        return rec
    try:
        rec["pages"] = doc.page_count
        meta = doc.metadata or {}
        rec["encrypted"] = int(
            bool(doc.is_encrypted)
            or bool(doc.needs_pass)
            or bool(meta.get("encryption"))
        )
        if doc.needs_pass:
            rec["error_kind"] = "encrypted"
            return rec
        texts, bad = _pdf_pages_text(doc)
        rec["chars"] = sum(len(t) for t in texts)
        rec["chars_effective"] = sum(effective_chars(t) for t in texts)
        images = 0
        for page in doc:
            try:
                images += len(page.get_images(full=True))
            except Exception:
                pass
        rec["images"] = images
        if bad:
            # Salvage readable pages: only a document with zero readable pages
            # counts as corrupt, otherwise the text is kept and the partial
            # failure is reported alongside it.
            rec["error"] = f"read:{bad}/{doc.page_count} pages unreadable"[:300]
            if bad >= doc.page_count:
                rec["error_kind"] = "broken"
    except Exception as exc:
        rec["error"] = f"read:{type(exc).__name__}:{exc}"[:300]
        rec["error_kind"] = _exc_kind(exc)
    finally:
        doc.close()
    return rec


def _inspect_text(path: str) -> dict:
    rec = _rec(pages=1, images=0)
    try:
        size = os.path.getsize(win_path(path))
        if size > MAX_TEXT_BYTES:
            rec["error"] = "file too large for full-text audit (>50MB)"
            rec["error_kind"] = "too_large"
            return rec
        raw = _read_bytes(path)
    except Exception as exc:
        rec["error"] = f"open:{type(exc).__name__}:{exc}"[:300]
        rec["error_kind"] = _exc_kind(exc)
        return rec
    ext = ext_of(path)
    if ext == "rtf":
        text = _decode_rtf(raw)
        rec["encoding"] = "rtf"
    else:
        text, encoding = decode_bytes_ex(raw)
        rec["encoding"] = encoding
        if encoding == FALLBACK_ENCODING:
            if looks_binary(raw):
                rec["error"] = "binary content in a text-extension file"
                rec["error_kind"] = "binary"
                return rec
            rec["error"] = "decoded as latin-1; mojibake likely"
            rec["error_kind"] = "mojibake"
    rec["chars"] = len(text)
    rec["chars_effective"] = effective_chars(text)
    return rec


def _inspect_html(path: str) -> dict:
    rec = _rec(pages=1, images=0)
    try:
        raw = _read_bytes(path)
        text, encoding = decode_bytes_ex(raw)
        rec["encoding"] = encoding
        parser = _HTMLText()
        parser.feed(text)
        joined = "".join(parser.parts)
        rec["chars"] = len(re.sub(r"\s+", " ", joined).strip())
        rec["chars_effective"] = effective_chars(joined)
        rec["images"] = parser.images
    except Exception as exc:
        rec["error"] = f"read:{type(exc).__name__}:{exc}"[:300]
        rec["error_kind"] = _exc_kind(exc)
    return rec


def _inspect_docx(path: str, ext: str) -> dict:
    rec = _rec()
    if is_ole_container(path):
        rec["encrypted"] = 1
        rec["error"] = "OLE/CFB container: possibly password-protected Office file"
        rec["error_kind"] = "encrypted_office"
        return rec
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
        rec["chars_effective"] = effective_chars(text)
        rec["images"] = images
    except Exception as exc:
        rec["error"] = f"read:{type(exc).__name__}:{exc}"[:300]
        rec["error_kind"] = _exc_kind(exc)
    return rec


def _inspect_xlsx_zip(path: str) -> dict:
    """Raw-XML fallback; also catches formula-only workbooks without cached values."""
    rec = _rec()
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
        rec["chars_effective"] = effective_chars(text)
        rec["images"] = sum(1 for n in names if n.startswith("xl/media/"))
    return rec


def _inspect_xlsx(path: str) -> dict:
    rec = _rec()
    if is_ole_container(path):
        rec["encrypted"] = 1
        rec["error"] = "OLE/CFB container: possibly password-protected Office file"
        rec["error_kind"] = "encrypted_office"
        return rec
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
            rec["chars_effective"] = chars
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
    rec["error_kind"] = "broken" if primary_error else ""
    return rec


def inspect_file(path: str) -> dict:
    """Return pages/chars/chars_effective/images/encrypted/encoding/error for one file."""
    ext = ext_of(path)
    kind = kind_of(path)
    if kind == "image":
        rec = _rec(pages=1, chars=0, images=1)
        rec["chars_effective"] = 0
        return rec
    if kind == "media":
        rec = _rec(pages=None, chars=0, images=0)
        rec["chars_effective"] = 0
        rec["error"] = "audio/video requires transcription or frame extraction first"
        rec["error_kind"] = "unsupported"
        return rec
    if kind == "archive":
        rec = _rec()
        rec["error"] = "archive: extract first, then audit the extracted files"
        rec["error_kind"] = "unsupported"
        return rec
    if kind == "legacy_office":
        rec = _rec()
        rec["error"] = "legacy Office format: convert .doc/.xls/.ppt to docx/xlsx/pptx first"
        rec["error_kind"] = "unsupported"
        return rec
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
    rec = _rec()
    rec["error"] = f"unsupported extension: .{ext or '(none)'}"
    rec["error_kind"] = "unsupported"
    return rec


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
            texts, bad = _pdf_pages_text(doc)
            text = "\n".join(texts)
            # EXT-03: keep whatever pages could be read; only a fully
            # unreadable document is an extraction failure.
            if bad and bad >= doc.page_count and not text.strip():
                raise ValueError(
                    f"corrupt PDF: all {doc.page_count} pages unreadable; "
                    "repair the PDF first")
            return text
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
        # _HTMLText already yields visible text; strip_markup would eat "<...>".
        parser = _HTMLText()
        parser.feed(decode_bytes(_read_bytes(path)))
        return "".join(parser.parts)
    if ext == "rtf":
        return _decode_rtf(_read_bytes(path))
    if kind == "text":
        return decode_bytes(_read_bytes(path))
    if kind == "spreadsheet":
        raise ValueError("tabular spreadsheet: use auto_stats / CSV pipeline, not document coding")
    if kind == "image":
        raise ValueError("image_only: run OCR first and audit the extracted text")
    if kind == "media":
        raise ValueError("audio/video: transcribe first and audit the transcript")
    if kind == "archive":
        raise ValueError("archive: extract first")
    raise ValueError(f"unsupported extension: .{ext or '(none)'}")


def _record(path: str, root: str) -> dict:
    """inspect_file() as a flat CSV row with a rel_path."""
    rec = inspect_file(path)
    ext = ext_of(path)
    return {
        "rel_path": os.path.relpath(path, root).replace(os.sep, "/") if root else path,
        "ext": ext,
        "kind": kind_of(path),
        "pages": rec.get("pages"),
        "chars": rec.get("chars"),
        "chars_effective": rec.get("chars_effective"),
        "images": rec.get("images"),
        "encrypted": rec.get("encrypted"),
        "encoding": rec.get("encoding") or "",
        "error": rec.get("error") or "",
        "error_kind": rec.get("error_kind") or "",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Extract/inspect text from research materials (offline, no OCR).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 ok, 2 parameter error / no input.",
    )
    print(f"text_extract.py {SCRIPT_VERSION}", file=sys.stderr)
    ap.add_argument("--root", help="directory to scan recursively")
    ap.add_argument("--file", action="append", default=[], help="one file (repeatable)")
    ap.add_argument("--out", help="output .csv or .jsonl path (default: stdout)")
    ap.add_argument("--ext", action="append", default=[], help="only these extensions")
    ap.add_argument("--max-files", type=int, default=0, help="stop after N files (0 = all)")
    ap.add_argument("--min-chars", type=int, default=0,
                    help="drop rows whose chars_effective is below N (0 = keep all)")
    ap.add_argument("--text", action="store_true", help="include the extracted text column")
    args = ap.parse_args(argv)

    if not args.root and not args.file:
        print("error: give --root or at least one --file", file=sys.stderr)
        return 2
    root = os.path.abspath(args.root) if args.root else os.getcwd()
    if args.root and not os.path.isdir(root):
        print(f"error: --root is not a directory: {args.root}", file=sys.stderr)
        return 2
    only = {e.lower().lstrip(".") for e in args.ext}

    files: list[str] = []
    if args.root:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for name in sorted(filenames):
                files.append(os.path.join(dirpath, name))
    for path in args.file:
        if not os.path.isfile(path):
            print(f"error: --file not found: {path}", file=sys.stderr)
            return 2
        files.append(os.path.abspath(path))

    # --root and --file may point at the same document; inspect it once.
    deduped: list[str] = []
    seen_paths: set[str] = set()
    for path in files:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen_paths:
            continue
        seen_paths.add(key)
        deduped.append(path)
    files = deduped

    rows: list[dict] = []
    for path in files:
        ext = ext_of(path)
        if only and ext not in only:
            continue
        if args.max_files and len(rows) >= args.max_files:
            break
        try:
            row = _record(path, root)
            if args.text:
                try:
                    row["text"] = extract_text(path)
                except (ValueError, OSError) as exc:
                    row["text"] = ""
                    row["error"] = row["error"] or str(exc)[:300]
            rows.append(row)
        except Exception as exc:  # one bad file must not kill the whole run
            rows.append({"rel_path": os.path.relpath(path, root).replace(os.sep, "/"),
                         "ext": ext, "kind": kind_of(path), "pages": None,
                         "chars": None, "chars_effective": None, "images": None,
                         "encrypted": None, "encoding": "", "error_kind": "broken",
                         "error": f"{type(exc).__name__}:{exc}"[:300]})

    kept = [r for r in rows if (r.get("chars_effective") or 0) >= args.min_chars]
    fields = ["rel_path", "ext", "kind", "pages", "chars", "chars_effective",
              "images", "encrypted", "encoding", "error", "error_kind"]
    if args.text:
        fields.append("text")
    if args.out:
        out = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        if out.lower().endswith(".jsonl"):
            with open(out, "w", encoding="utf-8", newline="\n") as fh:
                for row in kept:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        else:
            with open(out, "w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(kept)
        print(f"wrote {len(kept)} rows to {out}")
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)

    if not kept:
        print("error: no rows extracted (check --ext / --min-chars / inputs)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
