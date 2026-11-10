#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract text and candidate evidence from research materials into a coding worksheet.

This script does NOT assign final codes. It produces one JSONL record per
document with the extracted text, basic metadata, and keyword-hit sentences so a
human or an LLM can code against the codebook with traceable evidence.

Profiles:
  generic (default) — any text-bearing material: PDF, DOCX, ODT, PPTX, HTML,
                      TXT/MD/RTF and similar. No legal fields are assumed.
  legal             — additionally extract court, docket number, province and
                      case-type candidates from Chinese judgment-style text.

Tabular files (CSV/TSV/JSON/XLSX) are skipped here; use auto_stats.py /
csv_to_spss_syntax.py for those. Images and audio/video must be OCR'd or
transcribed first.

Every exclusion is written to skipped_documents.csv with a machine-readable
reason, so the sample funnel can be rebuilt from the artefacts alone. A run
that extracts zero documents is an error (exit 2) unless --allow-empty is
passed.

Usage:
    python make_coding_sheet.py --root "资料目录" --out "output/coding" \\
        --keywords assets/coding-keywords.json
    python make_coding_sheet.py --root "裁判文书目录" --out "output/coding" --profile legal
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date

from text_extract import (
    STRUCTURED_EXTS, SUPPORTED_EXTS, extract_text, ext_of, kind_of,
)

# Docket number: (year) + optional court/region code + case type + number.
# Covers 刑初/刑终/刑再/刑更/刑他/刑申/民初/民终/民再/民特/民辖/行初/行终/知行/
# 执/执异/破申/诉前调, the optional 字第 form, and the 之一 suffix.
CASE_NO_RE = re.compile(
    r"[（(]\s*(?:19|20)\d{2}\s*[）)]\s*"
    r"[\u4e00-\u9fa5A-Za-z0-9*＊×\s]{0,30}?"
    r"(?:刑初|刑终|刑再|刑更|刑他|刑申|民初|民终|民再|民特|民辖终|民辖|民申"
    r"|行初|行终|知行|执异|执|破申|诉前调)"
    r"\s*(?:字第)?\s*\d+\s*号"
    r"(?:之[一二三四五六七八九十]+)?"
)
# A year must stand alone: 1990 inside an ID number or 2020 inside an amount
# must not be read as a year.
YEAR_RE = re.compile(r"(?<!\d)(19[4-9]\d|20\d{2})(?!\d)")
# Court names end in 人民法院. The leading junk ("不服", "该案经", ...) is
# stripped afterwards, so the pattern can start anywhere in a Chinese run.
COURT_RE = re.compile(r"([\u4e00-\u9fa5]{2,60}?人民法院)")
REDACT_RE = re.compile(r"[*＊×]{2,}")
PROVINCE_RE = re.compile(r"^([\u4e00-\u9fa5]{2,12}?(?:省|市|自治区|特别行政区))")
PROVINCE_SHORT = {
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
}
PROVINCE_FULL_TO_SHORT = {
    "北京市": "北京", "天津市": "天津", "上海市": "上海", "重庆市": "重庆",
    "内蒙古自治区": "内蒙古", "广西壮族自治区": "广西", "西藏自治区": "西藏",
    "宁夏回族自治区": "宁夏", "新疆维吾尔自治区": "新疆",
    "香港特别行政区": "香港", "澳门特别行政区": "澳门",
}
OWN_CASE_RE = re.compile(r"(?:本院|我院|本案)[^\n。]{0,40}?" + CASE_NO_RE.pattern)
# Sentences are split after Chinese and ASCII sentence punctuation, and also
# after the enumerating comma/dunhao so one clause cannot hide a negation.
SENT_SPLIT_RE = re.compile(r"(?<=[。；;！？!?、，,])|(?<=[.!?])\s+|\n+")
NEGATION_RE = re.compile(r"(?:不予|不得|禁止|驳回|尚未|未|无|不)")
EVIDENCE_MAX_CHARS = 200

# Words that may precede a court name in running text. Only stripped when the
# remainder still looks like a court name (see _court_ok), so 本溪市 is safe.
COURT_JUNK_PREFIXES = tuple(sorted((
    "不服", "该案经", "本案经", "本院", "该院", "原审", "一审", "二审", "再审",
    "认为", "判决", "裁定", "查明", "认定", "审理", "依照", "根据", "以及",
    "经", "由", "向", "在", "与", "和", "对", "据", "了", "的", "是", "称",
    "见", "及", "或", "其", "此", "我", "你", "他", "本",
), key=len, reverse=True))
BAD_COURT = {
    "原审法院", "一审法院", "二审法院", "再审法院", "本院", "该院",
    "法院", "人民法院", "上级法院", "下级法院",
}
KEY_COLUMNS = ("rel_path", "relpath", "file", "path", "doc_id", "id")
DEFAULT_KEYWORDS_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "assets", "coding-keywords.json"))


def _push_span(text: str, start: int, end: int, spans: list) -> None:
    if end <= start:
        return
    raw = text[start:end]
    lead = len(raw) - len(raw.lstrip())
    trail = len(raw) - len(raw.rstrip())
    first, last = start + lead, end - trail
    if last > first:
        spans.append((text[first:last], first, last))


def _sentence_spans(text: str) -> list[tuple[str, int, int]]:
    """Split text into (sentence, char_start, char_end) spans."""
    text = text or ""
    spans: list[tuple[str, int, int]] = []
    start = 0
    for match in SENT_SPLIT_RE.finditer(text):
        _push_span(text, start, match.start(), spans)
        start = match.end()
    _push_span(text, start, len(text), spans)
    return spans


def sentences(text: str, with_offsets: bool = False):
    """Return sentences; with_offsets=True returns (text, start, end) tuples.

    The legacy call ``sentences(text)`` still returns a list of strings.
    """
    spans = _sentence_spans(text)
    if with_offsets:
        return spans
    return [re.sub(r"\s+", " ", part).strip() for part, _s, _e in spans if part.strip()]


def detect_doc_type(text: str, name: str = "", with_source: bool = False):
    """Legal profile: classify by title/filename, then dispositive language.

    The dispositive check looks at the END of the document: a ruling quotes the
    original "判决如下" in its body, so only the closing language decides.
    """
    head = (text or "")[:150]
    tail = (text or "")[-1500:]

    def result(doc_type: str, source: str):
        return (doc_type, source) if with_source else doc_type

    for marker, doc_type in (
        ("调解协议", "mediation"),
        ("调解书", "mediation"),
        ("判决书", "judgment"),
        ("裁定书", "ruling"),
        ("决定书", "decision"),
    ):
        if marker in name:
            return result(doc_type, "filename")
        if marker in head:
            return result(doc_type, "title")
    if "裁定如下" in tail:
        return result("ruling", "body")
    if "判决如下" in tail:
        return result("judgment", "body")
    if "调解" in name or "调解协议" in text:
        return result("mediation", "body")
    if "刑事" in name and ("一审" in name or "二审" in name or "判决" in name):
        return result("judgment", "filename")
    return result("other", "fallback")


def find_case_no(text: str, name: str = "", with_source: bool = False):
    """Return the docket number (and its source when asked)."""
    def result(value: str, source: str):
        return (value, source) if with_source else value

    match = CASE_NO_RE.search(name or "")
    if match:
        return result(match.group(0).strip(), "filename")
    own = OWN_CASE_RE.search((text or "")[:1200])
    if own:
        found = CASE_NO_RE.search(own.group(0))
        if found:
            return result(found.group(0).strip(), "body")
    match = CASE_NO_RE.search((text or "")[:1200]) or CASE_NO_RE.search(text or "")
    if match:
        return result(match.group(0).strip(), "body")
    return result("", "")


def find_year(*sources: tuple[str, str]) -> tuple[int | None, str]:
    """Return (year, source label) for the first plausible year in 1949..now."""
    current = date.today().year
    for label, source in sources:
        if not source:
            continue
        for match in YEAR_RE.finditer(str(source)):
            year = int(match.group(1))
            if 1949 <= year <= current:
                return year, label
    return None, ""


def normalize_province(value: str) -> str:
    """Normalize a place name to a province short name, or "" when unsure.

    A city name such as 广州市 must NOT become 广州: only the province
    whitelist is accepted, so a city never masquerades as a province.
    """
    value = (value or "").strip()
    if value in PROVINCE_SHORT:
        return value
    if value in PROVINCE_FULL_TO_SHORT:
        return PROVINCE_FULL_TO_SHORT[value]
    match = PROVINCE_RE.match(value)
    if not match:
        return ""
    candidate = PROVINCE_FULL_TO_SHORT.get(match.group(1), match.group(1).rstrip("省市"))
    return candidate if candidate in PROVINCE_SHORT else ""


def infer_province_with_source(parts: list[str], court: str, name: str) -> tuple[str, str]:
    for part in parts:
        if part == name:
            continue
        found = normalize_province(part)
        if found:
            return found, "path"
    found = normalize_province(court)
    if found:
        return found, "court"
    found = normalize_province(name)
    if found:
        return found, "filename"
    return "", ""


def infer_province(parts: list[str], court: str, name: str) -> str:
    return infer_province_with_source(parts, court, name)[0]


def _court_ok(value: str) -> bool:
    if not value or value in BAD_COURT:
        return False
    if value == "最高人民法院":
        return True
    match = re.search(r"(?:省|市|自治区|自治州|区|县)", value)
    if not match:
        return False
    head = value[:match.start()]
    return 2 <= len(head) <= 8


def _strip_court_junk(value: str) -> str:
    value = (value or "").strip()
    for _ in range(6):
        if _court_ok(value):
            return value
        for prefix in COURT_JUNK_PREFIXES:
            if value.startswith(prefix) and len(value) > len(prefix):
                candidate = value[len(prefix):]
                if _court_ok(candidate):
                    value = candidate
                    break
        else:
            return ""
    return value if _court_ok(value) else ""


def _extract_court(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    starts = sorted(
        (raw.find(name), name) for name in PROVINCE_SHORT if 0 <= raw.find(name) <= 20
    )
    for position, _name in starts:
        found = _strip_court_junk(raw[position:])
        if found:
            return found
    return _strip_court_junk(raw)


def find_court(name: str, text: str) -> tuple[str, str]:
    """Return (court, source). A redacted name yields "" with source=redacted."""
    sources = (("filename", name or ""), ("body", (text or "")[:5000]))
    redacted = bool(REDACT_RE.search(name or "")) or bool(REDACT_RE.search((text or "")[:5000]))
    for label, source in sources:
        if not source:
            continue
        masked = REDACT_RE.sub("\x00", source)
        for match in COURT_RE.finditer(masked):
            court = _extract_court(match.group(1))
            if court:
                return court, label
    if redacted:
        return "", "redacted"
    return "", ""


def detect_categories(text: str, name: str, category_map: dict) -> list[str]:
    """Filename hits win; 案由 hits are added, text hits are only a fallback."""
    def hits_in(source: str):
        found = []
        for canon, variants in (category_map or {}).items():
            if not isinstance(variants, list):
                continue
            for variant in variants:
                variant = str(variant)
                pos = source.find(variant)
                if pos >= 0:
                    found.append((pos, canon))
                    break
        found.sort(key=lambda x: x[0])
        return [canon for _, canon in found]

    charge = re.search(r"案\s*由[：:]\s*([^\n]{0,200})", (text or "")[:2000])
    hits = hits_in(name or "")
    if charge:
        hits = hits + hits_in(charge.group(1))
    elif not hits:
        hits = hits_in(text or "")
    seen, out = set(), []
    for canon in hits:
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def category_map_from(keywords: dict) -> dict:
    for key in ("category", "crime", "categories"):
        value = keywords.get(key)
        if isinstance(value, dict):
            return value
    return {}


def load_default_category_map() -> dict:
    """Load the bundled coding keywords (used when --keywords is not given)."""
    try:
        with open(DEFAULT_KEYWORDS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return category_map_from(data) if isinstance(data, dict) else {}


def _clip(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 1] + "…", True
    return text, False


def _is_negated(sentence: str, pos: int, term: str) -> bool:
    """Negation wins: a negated occurrence anywhere in the clause masks a hit."""
    if NEGATION_RE.search(term):
        return True
    if NEGATION_RE.search(sentence[max(0, pos - 10):pos]):
        return True
    for match in re.finditer(re.escape(term), sentence):
        if match.start() == pos:
            continue
        if NEGATION_RE.search(sentence[max(0, match.start() - 4):match.start()]):
            return True
    return False


def find_signals(
    text: str,
    keywords: dict,
    limit_per_term: int = 3,
    max_chars: int = EVIDENCE_MAX_CHARS,
    stats: dict | None = None,
) -> dict:
    """Return keyword hits with contract-grade evidence strings.

    Each hit carries the sentence (clipped to `max_chars`), the character span
    of the whole sentence in the source text, the span of the term, the
    paragraph number, and the negation polarity. `stats` is filled in place
    with included/skipped counters (the return value is unchanged).
    """
    spans = _sentence_spans(text or "")
    signals: dict = {}
    included = 0
    skipped = 0
    for category, terms in (keywords or {}).items():
        if str(category).startswith("_") or not isinstance(terms, list):
            continue
        hits = []
        for term in terms:
            term = str(term).strip()
            if not term:
                continue
            found = 0
            for sentence, sent_start, sent_end in spans:
                pos = sentence.find(term)
                while pos >= 0:
                    if found >= limit_per_term:
                        # Keep scanning so the skipped counter reflects every
                        # suppressed occurrence, not just the first overflow.
                        skipped += 1
                        pos = sentence.find(term, pos + len(term))
                        continue
                    abs_pos = sent_start + pos
                    snippet, truncated = _clip(sentence, max_chars)
                    negated = _is_negated(sentence, pos, term)
                    hits.append({
                        "term": term,
                        "sentence": snippet,
                        "start": sent_start,
                        "end": sent_end,
                        "term_start": abs_pos,
                        "term_end": abs_pos + len(term),
                        "para": (text or "").count("\n", 0, sent_start) + 1,
                        "negated": negated,
                        "polarity": "negative" if negated else "positive",
                        "truncated": truncated,
                        "evidence": f"{category}={snippet}@{sent_start}-{sent_end}",
                    })
                    included += 1
                    found += 1
                    pos = sentence.find(term, pos + len(term))
        if hits:
            signals[category] = hits
    if stats is not None:
        stats["included"] = included
        stats["skipped"] = skipped
    return signals


def _norm_rel(value: str) -> str:
    text = (value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _pick_key(row: dict) -> str:
    for column in KEY_COLUMNS:
        value = (row.get(column) or "").strip()
        if value:
            return _norm_rel(value)
    return ""


def _read_csv_rows(path: str, label: str) -> tuple[list[str], list[dict]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields:
        raise ValueError(f"{label} is empty (no header row)")
    return fields, rows


def read_valid_paths(audit: str | None, dedupe_plan: str | None) -> tuple[set[str] | None, set[str]]:
    """Read the audit/dedupe filters; the key column follows the contract order."""
    keep: set[str] | None = None
    if audit:
        fields, rows = _read_csv_rows(audit, "audit CSV")
        status_column = "status" if "status" in fields else ("valid" if "valid" in fields else "")
        if not status_column:
            raise ValueError(
                f"audit CSV missing a status column; have: {sorted(fields)}"
            )
        if not (set(fields) & set(KEY_COLUMNS)):
            raise ValueError(
                "audit CSV missing a path column; expected one of "
                f"{list(KEY_COLUMNS)}; have: {sorted(fields)}"
            )
        keep = set()
        for row in rows:
            rel = _pick_key(row)
            status = str(row.get(status_column) or "").strip().lower()
            if rel and status in {"valid", "1", "true", "yes", "y", "ok"}:
                keep.add(rel)
    removed: set[str] = set()
    if dedupe_plan:
        fields, rows = _read_csv_rows(dedupe_plan, "dedupe plan")
        if "action" not in fields:
            raise ValueError(f"dedupe plan missing an action column; have: {sorted(fields)}")
        if not (set(fields) & set(KEY_COLUMNS)):
            raise ValueError(
                "dedupe plan missing a path column; expected one of "
                f"{list(KEY_COLUMNS)}; have: {sorted(fields)}"
            )
        removed = {
            _pick_key(row) for row in rows
            if str(row.get("action") or "").strip().lower() in {"move", "copy"}
            and _pick_key(row)
        }
    return keep, removed


def first_title(text: str, name: str) -> str:
    """Pick a title line: a document-type line first, never the court header."""
    lines = []
    for line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) >= 2:
            lines.append(line)
        if len(lines) >= 12:
            break
    for line in lines:
        if re.search(r"(判决书|裁定书|调解书|决定书|调解协议)$", line):
            return line[:120]
    for line in lines:
        if re.search(r"(人民法院|人民检察院)$", line):
            continue
        return line[:120]
    return os.path.splitext(name)[0][:120]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a coding worksheet from research materials.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", default="output/coding")
    parser.add_argument("--keywords", default=None, help="JSON keyword dictionary")
    parser.add_argument("--audit", default=None,
                        help="corpus_files.csv from audit_corpus.py "
                             "(corpus_audit.csv is its legacy alias); rows with "
                             "status=valid are kept, the rest are reported as excluded")
    parser.add_argument("--dedupe-plan", default=None, help="dedupe_plan.csv (skip move/copy rows)")
    parser.add_argument("--profile", choices=["generic", "legal"], default="generic",
                        help="generic = any text material; legal = also extract court/docket fields")
    parser.add_argument("--doc-type", action="append", default=None,
                        choices=["judgment", "ruling", "mediation", "decision", "other", "all"],
                        help="legal profile only: keep only these document types "
                             "(repeatable; 'all' = no filter)")
    parser.add_argument("--ext", action="append", default=None,
                        help="extension(s) to extract; default: all document-like text types")
    parser.add_argument("--min-chars", type=int, default=100)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--max-text-chars", type=int, default=0,
                        help="truncate the stored body text to N characters (0 = full text)")
    parser.add_argument("--no-text", action="store_true",
                        help="do not store the document body in the JSONL output")
    parser.add_argument("--allow-empty", action="store_true",
                        help="exit 0 even when no document is extracted")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 2
    for label, path in (("audit", args.audit), ("dedupe-plan", args.dedupe_plan),
                        ("keywords", args.keywords)):
        if path and not os.path.isfile(path):
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            return 2
    requested = {e.lower().lstrip(".") for e in args.ext} if args.ext else None
    if requested:
        unknown = requested - SUPPORTED_EXTS
        if unknown:
            print(f"ERROR: unsupported extension(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
    exts = requested
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    keywords = {}
    if args.keywords:
        try:
            with open(args.keywords, encoding="utf-8") as fh:
                keywords = json.load(fh)
            if not isinstance(keywords, dict):
                raise ValueError("keywords must be a JSON object")
        except Exception as exc:
            print(f"ERROR: cannot read keywords: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 2
        keywords.pop("_note", None)
    cat_map = category_map_from(keywords)
    if args.profile == "legal" and not cat_map:
        cat_map = load_default_category_map()
        if cat_map:
            print(f"note: using default category keywords: {DEFAULT_KEYWORDS_PATH}",
                  file=sys.stderr)
    try:
        keep_paths, removed_paths = read_valid_paths(args.audit, args.dedupe_plan)
    except Exception as exc:
        print(f"ERROR: cannot read audit/dedupe input: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    jsonl_path = os.path.join(out_dir, "coding_sheet.jsonl")
    csv_path = os.path.join(out_dir, "coding_sheet.csv")
    skipped_path = os.path.join(out_dir, "skipped_documents.csv")
    flow_path = os.path.join(out_dir, "sample_flow.csv")
    rows: list[dict] = []
    skipped: list[dict] = []
    extracted = 0
    excluded = 0
    seen = 0
    run_order = 0
    signal_included = 0
    signal_skipped = 0
    stop = False

    def skip(rel: str, name: str, doc_type: str, chars: int, reason: str,
             detail: str = "", skip_stage: str = "", file_kind: str = "") -> None:
        skipped.append({
            "rel_path": rel, "relpath": rel, "file": name, "doc_type": doc_type,
            "chars": chars, "reason": reason, "detail": detail,
            "skip_stage": skip_stage, "file_kind": file_kind,
        })

    with open(jsonl_path, "w", encoding="utf-8") as out_jsonl:
        for dirpath, dirnames, filenames in os.walk(root):
            if stop:
                break
            dirnames[:] = sorted(
                d for d in dirnames if d != "_duplicates" and not d.startswith(".")
            )
            for name in sorted(filenames):
                if name.startswith("._") or name == ".DS_Store":
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                ext = ext_of(path)
                kind = kind_of(path)
                seen += 1
                if keep_paths is not None and _norm_rel(rel) not in keep_paths:
                    skip(rel, name, "", 0, "excluded by --audit (status is not valid)",
                         detail="audit status != valid", skip_stage="audit",
                         file_kind=kind)
                    excluded += 1
                    continue
                if _norm_rel(rel) in removed_paths:
                    skip(rel, name, "", 0, "excluded by --dedupe-plan (move/copy)",
                         detail="dedupe plan marks this file as a duplicate",
                         skip_stage="dedupe", file_kind=kind)
                    excluded += 1
                    continue
                if args.max_files and extracted >= args.max_files:
                    stop = True
                    break
                run_order += 1
                if exts is not None and ext not in exts:
                    skip(rel, name, "", 0, "extension not requested; use --ext to include it",
                         detail=f"ext={ext}", skip_stage="ext_filter", file_kind=kind)
                    continue
                if ext not in SUPPORTED_EXTS:
                    skip(rel, name, ext, 0, "unsupported extension; convert or extract first",
                         detail=f"ext={ext}", skip_stage="format")
                    continue
                try:
                    size = os.path.getsize(path)
                except OSError as exc:
                    skip(rel, name, ext, 0, "unreadable file", detail=str(exc),
                         skip_stage="read")
                    continue
                if size == 0:
                    skip(rel, name, "", 0, "zero-byte file", detail="size=0",
                         skip_stage="size")
                    continue
                if ext in STRUCTURED_EXTS or kind == "spreadsheet":
                    skip(rel, name, kind, 0,
                         "tabular/structured data; use auto_stats or CSV pipeline",
                         detail=f"kind={kind}", skip_stage="format", file_kind=kind)
                    continue
                if kind == "image":
                    skip(rel, name, kind, 0, "image_only; run OCR first",
                         detail="kind=image", skip_stage="format", file_kind=kind)
                    continue
                if kind == "media":
                    skip(rel, name, kind, 0, "audio/video; transcribe first",
                         detail="kind=media", skip_stage="format", file_kind=kind)
                    continue
                if kind in {"archive", "legacy_office", "unknown"}:
                    skip(rel, name, kind, 0, "unsupported format; convert or extract first",
                         detail=f"kind={kind}", skip_stage="format", file_kind=kind)
                    continue
                try:
                    text = extract_text(path)
                except Exception as exc:
                    print(f"WARN: cannot read {rel}: {exc}", file=sys.stderr)
                    skip(rel, name, "unreadable", 0, f"unreadable: {exc}",
                         detail=str(exc), skip_stage="read")
                    continue
                chars = len(text.strip())
                han = len(re.findall(r"[\u4e00-\u9fa5]", text))
                if chars < args.min_chars:
                    reason = f"below --min-chars ({chars} < {args.min_chars})"
                    detail = f"chars={chars}"
                    if kind == "pdf":
                        reason += "; scanned/image-only PDF? run OCR first"
                        detail += "; scanned/image-only PDF?"
                    skip(rel, name, kind, chars, reason, detail=detail,
                         skip_stage="min_chars", file_kind=kind)
                    continue

                if args.profile == "legal":
                    doc_type, doc_type_src = detect_doc_type(text, name, with_source=True)
                    wanted = {value for value in (args.doc_type or []) if value != "all"}
                    if wanted and doc_type not in wanted:
                        skip(rel, name, doc_type, chars,
                             f"document type '{doc_type}' not in --doc-type "
                             f"{sorted(wanted)}",
                             detail=f"doc_type={doc_type}", skip_stage="doc_type")
                        continue
                    parts = rel.split("/")[:-1]
                    court, court_src = find_court(name, text)
                    province, province_src = infer_province_with_source(parts, court, name)
                    case_no, case_no_src = find_case_no(text, name, with_source=True)
                    year, year_src = find_year(
                        ("case_no", case_no), ("filename", name), ("body", text[:800])
                    )
                else:
                    doc_type = kind or ext
                    doc_type_src = "extension"
                    court = court_src = province = province_src = ""
                    case_no = case_no_src = ""
                    year, year_src = find_year(("filename", name), ("body", text[:800]))

                stats: dict = {}
                signals = find_signals(text, keywords, stats=stats) if keywords else {}
                signal_included += int(stats.get("included", 0))
                signal_skipped += int(stats.get("skipped", 0))
                categories = detect_categories(text, name, cat_map) if cat_map else []
                title = first_title(text, name)
                stored_text = "" if args.no_text else text
                text_truncated = False
                if not args.no_text and args.max_text_chars and len(text) > args.max_text_chars:
                    stored_text = text[: args.max_text_chars]
                    text_truncated = True
                evidence = {
                    category: [hit["evidence"] for hit in hits]
                    for category, hits in signals.items()
                }
                rec = {
                    "profile": args.profile,
                    "file": name,
                    "relpath": rel,
                    "rel_path": rel,
                    "root": root,
                    "run_order": run_order,
                    "source_type": ext or kind,
                    "doc_type": doc_type,
                    "doc_type_src": doc_type_src,
                    "title": title,
                    "province": province,
                    "province_src": province_src,
                    "year": year,
                    "year_src": year_src,
                    "case_no": case_no,
                    "case_no_src": case_no_src,
                    "court": court,
                    "court_src": court_src,
                    "chars": chars,
                    "han_chars": han,
                    "category_candidates": categories,
                    "crime_candidates": categories if args.profile == "legal" else [],
                    "text": stored_text,
                    "text_truncated": text_truncated,
                    "signals": signals,
                    "codes": {},
                    "evidence": evidence,
                }
                out_jsonl.write(json.dumps(rec, ensure_ascii=False) + "\n")
                rows.append({
                    "file": name, "relpath": rel, "rel_path": rel,
                    "source_type": ext or kind,
                    "doc_type": doc_type, "title": title, "year": year,
                    "province": province, "case_no": case_no, "court": court,
                    "chars": chars, "han_chars": han,
                    "category_candidates": ",".join(categories),
                    "crime_candidates": ",".join(categories) if args.profile == "legal" else "",
                    "signal_categories": ",".join(sorted(signals.keys())),
                    "signal_hits": sum(len(v) for v in signals.values()),
                    "year_src": year_src, "doc_type_src": doc_type_src,
                    "case_no_src": case_no_src, "court_src": court_src,
                    "province_src": province_src,
                })
                extracted += 1
                if extracted % 200 == 0:
                    print(f"  extracted {extracted} ...", flush=True)

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        fields = ["file", "relpath", "source_type", "doc_type", "title", "year",
                  "province", "case_no", "court", "chars", "han_chars",
                  "category_candidates", "crime_candidates",
                  "signal_categories", "signal_hits", "rel_path",
                  "year_src", "doc_type_src", "case_no_src", "court_src",
                  "province_src"]
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    with open(skipped_path, "w", newline="", encoding="utf-8-sig") as fh:
        fields = ["rel_path", "relpath", "file", "doc_type", "chars",
                  "reason", "detail", "skip_stage", "file_kind"]
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(skipped)

    # Funnel: total -> usable -> passing filters -> coded (monotonic by design).
    effective = seen - excluded
    filtered = effective - (len(skipped) - excluded)
    flow_rows = [
        {"stage": "文件总数", "n": seen,
         "note": "files walked under --root (hidden/._ files excluded)"},
        {"stage": "有效文件", "n": effective,
         "note": "--audit status=valid and not excluded by --dedupe-plan"},
        {"stage": "通过筛选", "n": filtered,
         "note": "after extension/format/size/--min-chars/--doc-type filters"},
        {"stage": "编码完成", "n": len(rows),
         "note": "records written to coding_sheet.jsonl"},
    ]
    with open(flow_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=["stage", "n", "note"],
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flow_rows)

    print(f"extracted: {len(rows)} documents -> {jsonl_path}")
    print(f"skipped: {len(skipped)} documents -> {skipped_path}")
    print(f"excluded: {excluded} documents (subset of skipped; by --audit/--dedupe-plan)")
    print(f"signals: included {signal_included}, skipped {signal_skipped} (per-term limit)")
    print(f"summary: {csv_path}")
    print(f"sample_flow: {flow_path}")

    if not rows:
        if args.allow_empty:
            print("WARNING: extracted 0 documents (--allow-empty)", file=sys.stderr)
            return 0
        if keep_paths is not None and not keep_paths:
            print("ERROR: --audit lists no row with status=valid; every document is excluded",
                  file=sys.stderr)
        else:
            print("ERROR: extracted 0 documents; nothing to code "
                  "(pass --allow-empty to accept an empty worksheet)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
