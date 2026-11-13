# -*- coding: utf-8 -*-
"""Shared helpers for the skill's test suite (stdlib unittest only).

Design rules:
- No network, no external services, no dependence on the user's real corpus.
- Every test builds its own temporary workspace under tempfile.mkdtemp().
- CLI scripts are exercised through subprocess so the tests also cover argparse,
  exit codes and file layout, not just the importable functions.
"""
from __future__ import annotations

import csv
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # repository root
SKILL = os.path.join(ROOT, "empirical-research-pipeline")
SCRIPTS = os.path.join(SKILL, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

PYTHON = sys.executable

# Every script under test prints non-ASCII (ΔE, ΔL*, Chinese messages).  A
# Chinese Windows console defaults to cp936, so the same assertion would pass or
# fail depending on which module was imported first; pin the child encoding here
# so one module runs the same way as the whole suite.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def run(script: str, *args, cwd: str | None = None, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run one skill script as a subprocess and return the completed process."""
    cmd = [PYTHON, os.path.join(SCRIPTS, script), *[str(a) for a in args]]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def write_csv(path: str, header: list[str], rows: list[list | dict]) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for row in rows:
            if isinstance(row, dict):
                writer.writerow([row.get(col, "") for col in header])
            else:
                writer.writerow(row)
    return path


def read_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def make_png(path: str, width: int = 600, height: int = 400) -> str:
    """Write a plain PNG of the requested pixel size (Pillow)."""
    from PIL import Image
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    Image.new("RGB", (width, height), (235, 238, 242)).save(path, dpi=(600, 600))
    return path


def make_figure_pdf(path: str, png: str, width_cm: float = 15.0) -> str:
    """Embed one image into a single-page PDF at a fixed physical width.

    The effective resolution of the embedded image is therefore
    pixel_width / (width_cm / 2.54) dpi, which is what qa_outputs must measure.
    """
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)      # A4 in points
    w = width_cm / 2.54 * 72
    h = w * 0.66
    rect = fitz.Rect(50, 80, 50 + w, 80 + h)
    page.insert_image(rect, filename=png)
    doc.save(path)
    doc.close()
    return path


def make_text_pdf(path: str, text: str = "hello") -> str:
    """Write a text PDF that also survives CJK extraction.

    Base-14 fonts (Helvetica) have no CJK glyphs: PyMuPDF writes them as
    U+FFFD-ish blanks, so a Chinese fixture would silently extract as "·····".
    PyMuPDF ships built-in CJK fonts ("china-s" = Simplified Chinese), which do
    not require a font file on disk.
    """
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    page.insert_text((72, 72), text, fontname="china-s" if cjk else "helv",
                     fontsize=12)
    doc.save(path)
    doc.close()
    return path


def make_docx(path: str, paragraphs: list[str], image: str | None = None,
              width_cm: float = 15.0) -> str:
    from docx import Document
    from docx.shared import Cm
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    if image:
        doc.add_picture(image, width=Cm(width_cm))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    doc.save(path)
    return path


class TempCase(unittest.TestCase):
    """unittest.TestCase with a throw-away workspace."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="skill-test-")
        self.tmp = self._tmp

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def p(self, *parts: str) -> str:
        return os.path.join(self.tmp, *parts)
