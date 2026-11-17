#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract text and candidate evidence from research materials into a coding worksheet.

This script does NOT assign final codes. It produces one JSONL record per
document with the extracted text, basic metadata, and keyword-hit sentences so a
human or an LLM can code against the codebook with traceable evidence. Every
text-bearing material is read the same generic way: PDF, DOCX, ODT, PPTX,
HTML, TXT/MD/RTF and similar. No genre gets special fields or special
segmentation; structured fields come from a project-authored --extract profile
only, never from this script.

Tabular files (CSV/TSV/JSON/XLSX) are skipped here; use auto_stats.py /
csv_to_spss_syntax.py for those. Images and audio/video must be OCR'd or
transcribed first.

Every exclusion is written to skipped_documents.csv with a machine-readable
reason, so the sample funnel can be rebuilt from the artefacts alone. A run
that extracts zero documents is an error (exit 2) unless --allow-empty is
passed.

Usage:
    python make_coding_sheet.py --root "资料目录" --out "output/coding" \\
        --keywords my-keywords.json --extract draft/fields.json
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
from check_decisions import (
    DecisionError, load_decisions, validate_decisions, write_issues,
)

# Stamped into run.json so an output directory names the code that built it.
SCRIPT_VERSION = "2.1.0"

# A year must stand alone: 1990 inside an ID number or 2020 inside an amount
# must not be read as a year.
YEAR_RE = re.compile(r"(?<!\d)(19[4-9]\d|20\d{2})(?!\d)")
# Sentences are split after Chinese and ASCII sentence punctuation, and also
# after the enumerating comma/dunhao so one clause cannot hide a negation.
SENT_SPLIT_RE = re.compile(r"(?<=[。；;！？!?、，,])|(?<=[.!?])\s+|\n+")
NEGATION_RE = re.compile(r"(?:不予|不得|禁止|驳回|尚未|未|无|不)")
EVIDENCE_MAX_CHARS = 200

# One implementation of the `name=snippet@start-end` line lives in extract_lib;
# importing it here keeps keyword evidence and field evidence byte-identical.
# The fallback only exists so a lone copy of this script still runs.
try:
    from extract_lib import evidence_line as _evidence_line
except Exception:                                     # pragma: no cover
    def _evidence_line(name, snippet, span):
        return f"{name}={snippet}@{int(span[0])}-{int(span[1])}"

# Key columns used to align audit/dedupe/keyword rows with extracted documents.
KEY_COLUMNS = ("rel_path", "relpath", "file", "path", "doc_id", "id")


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


def detect_categories(text: str, name: str, category_map: dict) -> list[str]:
    """Filename hits first, then full-text hits; both are only candidates."""
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

    hits = hits_in(name or "") or hits_in(text or "")
    seen, out = set(), []
    for canon in hits:
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def category_map_from(keywords: dict) -> dict:
    for key in ("category", "categories"):
        value = keywords.get(key)
        if isinstance(value, dict):
            return value
    return {}


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
                        "evidence": _evidence_line(category, snippet, (sent_start, sent_end)),
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


def read_valid_paths(audit: str | None,
                     dedupe_plan: str | None) -> tuple[set[str] | None, set[str], set[str]]:
    """Read the audit/dedupe filters.

    Returns ``(keep, removed, listed)`` where ``listed`` is every path the audit
    file mentions.  Without ``listed`` a wrong ``--root`` is indistinguishable
    from "the whole corpus failed the audit", and the funnel then reports the
    wrong reason for every single row.
    """
    keep: set[str] | None = None
    listed: set[str] = set()
    removed: set[str] = set()
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
            if rel:
                listed.add(rel)
            status = str(row.get(status_column) or "").strip().lower()
            duplicate = (row.get("dedupe_role") == "duplicate" if "dedupe_role" in fields
                         else row.get("dup_role") == "duplicate" or row.get("dup_role_content") == "duplicate")
            if duplicate and rel:
                removed.add(rel)
            if rel and status in {"valid", "1", "true", "yes", "y", "ok"}:
                keep.add(rel)
    if dedupe_plan:
        fields, rows = _read_csv_rows(dedupe_plan, "dedupe plan")
        if "action" not in fields:
            raise ValueError(f"dedupe plan missing an action column; have: {sorted(fields)}")
        if not (set(fields) & set(KEY_COLUMNS)):
            raise ValueError(
                "dedupe plan missing a path column; expected one of "
                f"{list(KEY_COLUMNS)}; have: {sorted(fields)}"
            )
        removed |= {
            _pick_key(row) for row in rows
            if str(row.get("action") or "").strip().lower() in {"move", "copy"}
            and _pick_key(row)
        }
    return keep, removed, listed


def first_title(text: str, name: str) -> str:
    """First meaningful line of the document; no genre word list picks titles."""
    for line in (text or "").splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) >= 2:
            return line[:120]
    return os.path.splitext(name)[0][:120]


def _strip_extended_prefix(path: str) -> str:
    # os.path.realpath keeps a \\?\ prefix when the input has one, which makes
    # commonpath() see a different drive and skips the containment check.
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[len("\\\\?\\UNC\\"):]
    if path.startswith("\\\\?\\"):
        return path[len("\\\\?\\"):]
    return path


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
    parser.add_argument("--extract", default=None, metavar="PROFILE_JSON",
                        help="run a field-extraction profile and write dataset.csv, "
                             "evidence.jsonl and run.json (contract: references/09-field-extraction.md)")
    parser.add_argument("--require-review", action="store_true",
                        help="exit 2 while any extracted field is flagged for review "
                             "(write decisions.jsonl, then re-run with --decisions)")
    parser.add_argument("--decisions", default=None, metavar="DECISIONS_JSONL",
                        help="apply a validated decisions.jsonl to the dataset "
                             "(value / na per field, exclude per document)")
    parser.add_argument("--allow-unresolved", action="store_true",
                        help="let needs_human=true decisions through (draft runs only)")
    args = parser.parse_args()
    if args.require_review and not args.extract:
        print("ERROR: --require-review only applies with --extract", file=sys.stderr)
        return 2
    if args.decisions and not args.extract:
        print("ERROR: --decisions only applies with --extract", file=sys.stderr)
        return 2

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
    try:
        keep_paths, removed_paths, listed_paths = read_valid_paths(
            args.audit, args.dedupe_plan)
    except Exception as exc:
        print(f"ERROR: cannot read audit/dedupe input: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    extract_profile = None
    if args.extract:
        if not os.path.isfile(args.extract):
            print(f"ERROR: --extract profile not found: {args.extract}", file=sys.stderr)
            return 2
        shipped_profiles = _strip_extended_prefix(os.path.realpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "profiles")))
        target_profile = _strip_extended_prefix(
            os.path.realpath(os.path.abspath(args.extract)))
        try:
            inside_shipped = os.path.commonpath(
                [shipped_profiles, target_profile]) == shipped_profiles
        except ValueError:
            inside_shipped = False
        if inside_shipped:
            print("ERROR: --extract refuses profiles shipped with the skill: "
                  f"{args.extract}. Shipped profiles are field-shape examples, "
                  "not extraction rules for this corpus. Read your samples, "
                  "write the segmentation into draft/fields.json (copy a "
                  "shipped profile there first if the shapes help), and pass "
                  "that file instead. See SKILL.md section 2.2.",
                  file=sys.stderr)
            return 2
        try:
            from extract_lib import (ProfileError, apply_profile, evidence_line,
                                     load_profile, profile_sha256)
        except Exception as exc:                       # pragma: no cover
            print(f"ERROR: cannot import extract_lib: {exc}", file=sys.stderr)
            return 2
        try:
            extract_profile = load_profile(args.extract)
        except ProfileError as exc:
            print(f"ERROR: invalid profile: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"ERROR: cannot read profile: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 2
        profile_dir = os.path.dirname(os.path.abspath(args.extract))

    jsonl_path = os.path.join(out_dir, "coding_sheet.jsonl")
    csv_path = os.path.join(out_dir, "coding_sheet.csv")
    skipped_path = os.path.join(out_dir, "skipped_documents.csv")
    flow_path = os.path.join(out_dir, "sample_flow.csv")
    rows: list[dict] = []
    skipped: list[dict] = []
    ds_rows: list[dict] = []
    ds_evidence: list[dict] = []
    review_rows: list[dict] = []
    candidate_rows: list[dict] = []
    ds_field_names: list[str] = []
    ds_na_counts: dict = {}
    # Why a field is empty matters: "the document never mentions it", "it was
    # negated", "it was redacted" and "we found text but could not parse it"
    # are four different facts, and collapsing them is how a coding sheet
    # quietly turns into a claim that a thing did not happen.
    ds_na_by_source: dict = {}
    ds_hit_counts: dict = {}
    ds_errors = 0
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
                    if _norm_rel(rel) not in listed_paths:
                        # The audit file describes a different root: every single
                        # path would be "not in the audit", which looks exactly
                        # like "all files failed the audit".
                        skip(rel, name, "", 0,
                             "not listed in the --audit CSV (wrong --root, or the "
                             "audit was run on another directory)",
                             detail=f"rel_path={rel} absent from audit rows",
                             skip_stage="audit", file_kind=kind)
                    else:
                        skip(rel, name, "", 0,
                             "excluded by --audit (status is not valid)",
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
                # Normalise line endings once, before any offset is computed:
                # a CRLF file would otherwise shift every evidence span by the
                # number of preceding lines, and the offsets would not match
                # what a reviewer sees in an editor.
                text = text.replace("\r\n", "\n").replace("\r", "\n")
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

                # `doc_type` is a document kind, not a file format: writing
                # "pdf" here made every downstream group-by useless and was
                # indistinguishable from a real classification.
                doc_type = "document"
                doc_type_src = "default"
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
                    "file": name,
                    "relpath": rel,
                    "rel_path": rel,
                    "root": root,
                    "run_order": run_order,
                    "source_type": ext or kind,
                    "doc_type": doc_type,
                    "doc_type_src": doc_type_src,
                    "title": title,
                    "year": year,
                    "year_src": year_src,
                    "chars": chars,
                    "han_chars": han,
                    "category_candidates": categories,
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
                    "chars": chars, "han_chars": han,
                    "category_candidates": ",".join(categories),
                    "signal_categories": ",".join(sorted(signals.keys())),
                    "signal_hits": sum(len(v) for v in signals.values()),
                    "year_src": year_src, "doc_type_src": doc_type_src,
                })
                extracted += 1
                if extract_profile is not None:
                    row_id = f"{extracted:05d}"
                    try:
                        res = apply_profile(extract_profile, text,
                                            base_dir=profile_dir)
                    except Exception as exc:           # one bad document only
                        ds_errors += 1
                        print(f"ERROR: extract {rel}: {type(exc).__name__}: {exc}",
                              file=sys.stderr)
                        res = {"fields": {}, "evidence": []}
                    if not ds_field_names:
                        ds_field_names = [f["name"] for f in extract_profile["fields"]]
                    ds_row = {"rel_path": rel, "file": name, "doc_type": doc_type}
                    ev_fields = {}
                    doc_candidates = {"rel_path": rel, "fields": {}}
                    for fname in ds_field_names:
                        got = res["fields"].get(fname) or {}
                        value = got.get("value")
                        ds_row[fname] = "" if value is None else value
                        ds_row[f"{fname}_src"] = got.get("source", "none")
                        flags = list(got.get("flags") or [])
                        candidates = got.get("candidates") or []
                        ev_fields[fname] = {
                            "value": value, "raw": got.get("raw"),
                            "span": got.get("span"), "source": got.get("source"),
                            "na": got.get("na"), "negated": bool(got.get("negated")),
                            "fallback_used": got.get("fallback_used", 0),
                            "truncated": bool(got.get("truncated")),
                            "flags": flags,
                            "needs_review": bool(got.get("needs_review")),
                            "cross_line": bool(got.get("cross_line")),
                            "na_hit": bool(got.get("na_hit")),
                            "candidates": candidates,
                        }
                        doc_candidates["fields"][fname] = ev_fields[fname]
                        alternatives = []
                        for item in candidates:
                            item_value = item.get("value")
                            if item_value is None or str(item_value) == str(value):
                                continue
                            text_value = str(item_value)
                            if text_value not in alternatives:
                                alternatives.append(text_value)
                        review_rows.append({
                            "rel_path": rel, "field": fname,
                            "value": "" if value is None else value,
                            "raw": got.get("raw") or "",
                            "source": got.get("source") or "none",
                            "span": (f"{got['span'][0]}-{got['span'][1]}"
                                     if got.get("span") else ""),
                            "na_hit": bool(got.get("na_hit")),
                            "cross_line": bool(got.get("cross_line")),
                            "needs_review": bool(got.get("needs_review")),
                            "flags": "|".join(flags),
                            "alternatives": "|".join(alternatives[:6]),
                            "note": "|".join(sorted({str(c.get("note") or "")
                                                     for c in candidates
                                                     if c.get("note")})),
                        })
                        if value is None:
                            ds_na_counts[fname] = ds_na_counts.get(fname, 0) + 1
                            if got.get("negated"):
                                bucket = "negated"
                            elif str(got.get("source") or "none") == "none":
                                bucket = "not_found"
                            elif got.get("redacted"):
                                bucket = "redacted"
                            elif got.get("na"):
                                bucket = "na_phrase"
                            else:
                                bucket = "unparsed"
                            per_field = ds_na_by_source.setdefault(fname, {})
                            per_field[bucket] = per_field.get(bucket, 0) + 1
                        else:
                            ds_hit_counts[fname] = ds_hit_counts.get(fname, 0) + 1
                    ds_rows.append(ds_row)
                    candidate_rows.append(doc_candidates)
                    ds_evidence.append({"_row_id": row_id, "rel_path": rel,
                                        "fields": ev_fields,
                                        "evidence": res["evidence"]})
                if extracted % 200 == 0:
                    print(f"  extracted {extracted} ...", flush=True)

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        fields = ["file", "relpath", "source_type", "doc_type", "title", "year",
                  "chars", "han_chars", "category_candidates",
                  "signal_categories", "signal_hits", "rel_path",
                  "year_src", "doc_type_src"]
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
         "note": "after extension/format/size/--min-chars filters"},
        {"stage": "编码完成", "n": len(rows),
         "note": "records written to coding_sheet.jsonl"},
    ]
    if extract_profile is not None:
        flow_rows.append({
            "stage": "抽取字段完成", "n": len(ds_rows),
            "note": f"records written to dataset.csv (profile "
                    f"{extract_profile['profile']})"})
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

    review_index = {(row["rel_path"], row["field"]): row for row in review_rows}
    applied_decisions: list[dict] = []
    excluded_by_decision: list[str] = []
    if extract_profile is not None and args.decisions:
        try:
            decisions = load_decisions(args.decisions)
        except (OSError, DecisionError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        issues = validate_decisions(decisions, root=root, review=review_index,
                                    allow_unresolved=args.allow_unresolved)
        issue_path = os.path.join(out_dir, "decision_issues.csv")
        write_issues(issue_path, issues)
        errors = [issue for issue in issues if issue["severity"] == "error"]
        if errors:
            for issue in errors[:8]:
                print(f"ERROR [{issue['check']}] {issue['id'] or '-'}: "
                      f"{issue['detail']}", file=sys.stderr)
            print(f"ERROR: {len(errors)} decision issue(s); see {issue_path}",
                  file=sys.stderr)
            return 2
        by_target = {str(item.get("target") or ""): item for item in decisions
                     if item.get("stage") == "extract"}
        kept = []
        for row in ds_rows:
            rel = row.get("rel_path", "")
            doc_decision = by_target.get(rel)
            if doc_decision and doc_decision.get("decision") == "exclude":
                excluded_by_decision.append(rel)
                continue
            for fname in ds_field_names:
                decision = by_target.get(f"{rel}#{fname}")
                if not decision:
                    continue
                kind = decision.get("decision")
                if kind == "value":
                    row[fname] = decision.get("value")
                    row[f"{fname}_src"] = "decision"
                elif kind == "na":
                    row[fname] = ""
                    row[f"{fname}_src"] = "decision:na"
                else:
                    continue
                applied_decisions.append({
                    "id": decision.get("id"), "target": decision.get("target"),
                    "decision": kind, "value": decision.get("value"),
                })
                review_row = review_index.get((rel, fname))
                if review_row is not None:
                    review_row["needs_review"] = False
                    review_row["value"] = row[fname]
                    review_row["source"] = row[f"{fname}_src"]
                    review_row["span"] = ""
                    note = review_row.get("note") or ""
                    review_row["note"] = (
                        note + "|" if note else "") + f"decision:{decision.get('id')}"
                for record in ds_evidence:
                    if record.get("rel_path") != rel:
                        continue
                    field_record = (record.get("fields") or {}).get(fname)
                    if field_record is not None:
                        field_record["value"] = (row[fname]
                                                 if row[fname] != "" else None)
                        field_record["source"] = row[f"{fname}_src"]
                        field_record["decision"] = decision.get("id")
                        field_record["span"] = None
                        field_record["raw"] = (decision.get("quote")
                                               or decision.get("value"))
                    # The rejected reading is not evidence for the decision.
                    # Keeping both lines would let a reader cite the value the
                    # author explicitly overruled.
                    prefix = f"{fname}="
                    record["evidence"] = [
                        line for line in record.get("evidence", [])
                        if not line.startswith(prefix)]
                    record["evidence"].append(
                        f"{fname}=decision:{decision.get('id')}")
                    break
            kept.append(row)
        ds_rows = kept
        if excluded_by_decision:
            excluded_set = set(excluded_by_decision)
            # A document excluded by decision must disappear from every
            # artefact, not only from dataset.csv: a stale evidence row is
            # still citable and would contradict the sample.
            ds_evidence = [record for record in ds_evidence
                           if record.get("rel_path") not in excluded_set]
            review_rows = [row for row in review_rows
                           if row.get("rel_path") not in excluded_set]
            candidate_rows = [row for row in candidate_rows
                              if row.get("rel_path") not in excluded_set]

    final_hits = {name: sum(1 for row in ds_rows
                            if row.get(name) not in ("", None))
                  for name in ds_field_names}
    # Missingness describes the FINAL dataset, not rejected readings or excluded
    # documents. Recompute it after decisions have been applied.
    if extract_profile is not None:
        if args.decisions:
            flow_rows.extend([
                {"stage": "复审排除", "kind": "excluded", "n": len(excluded_by_decision),
                 "note": "excluded by validated document decisions"},
                {"stage": "最终字段数据集", "kind": "stage", "n": len(ds_rows),
                 "note": "final dataset.csv after validated decisions"},
            ])
            with open(flow_path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=["stage", "n", "note", "kind"])
                writer.writeheader()
                writer.writerows(flow_rows)
        ds_hit_counts = dict(final_hits)
        ds_na_counts = {n: len(ds_rows) - final_hits[n] for n in ds_field_names}
        ds_na_by_source = {n: {} for n in ds_field_names}
        for record in ds_evidence:
            for name, field in record.get("fields", {}).items():
                if name not in ds_na_by_source or field.get("value") not in (None, ""):
                    continue
                bucket = ("decision_na" if field.get("source") == "decision:na" else
                          "negated" if field.get("negated") else "redacted" if field.get("redacted") else
                          "not_found" if field.get("source") in (None, "none") else
                          "na_phrase" if field.get("na") else "unparsed")
                counts = ds_na_by_source[name]
                counts[bucket] = counts.get(bucket, 0) + 1

    if extract_profile is not None:
        ds_path = os.path.join(out_dir, "dataset.csv")
        ev_path = os.path.join(out_dir, "evidence.jsonl")
        run_path = os.path.join(out_dir, "run.json")
        cols = ["rel_path", "file", "doc_type"]
        for fname in ds_field_names:
            cols += [fname, f"{fname}_src"]
        with open(ds_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(ds_rows)
        with open(ev_path, "w", encoding="utf-8") as fh:
            for rec in ds_evidence:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        review_path = os.path.join(out_dir, "extraction_review.csv")
        with open(review_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["rel_path", "field", "value", "raw", "source",
                                "span", "na_hit", "cross_line", "needs_review",
                                "flags", "alternatives", "note"],
                extrasaction="ignore")
            writer.writeheader()
            writer.writerows(review_rows)
        candidates_path = os.path.join(out_dir, "extraction_candidates.jsonl")
        with open(candidates_path, "w", encoding="utf-8") as fh:
            for record in candidate_rows:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        pending = [row for row in review_rows if row.get("needs_review")]
        todo_path = os.path.join(out_dir, "decisions_todo.csv")
        with open(todo_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["target", "field", "current", "alternatives",
                                "flags"], extrasaction="ignore")
            writer.writeheader()
            for row in pending:
                writer.writerow({
                    "target": f"{row['rel_path']}#{row['field']}",
                    "field": row["field"],
                    "current": row.get("value", ""),
                    "alternatives": row.get("alternatives", ""),
                    "flags": row.get("flags", ""),
                })
        run = {
            "profile": extract_profile["profile"],
            "profile_path": os.path.abspath(args.extract),
            "profile_sha256": profile_sha256(args.extract),
            "documents": len(ds_rows),
            "errors": ds_errors,
            "fields": {name: {"hit": ds_hit_counts.get(name, 0),
                              "na": ds_na_counts.get(name, 0),
                              "type": next(f["type"] for f in extract_profile["fields"]
                                           if f["name"] == name)}
                       for name in ds_field_names},
            "generated_by": "make_coding_sheet.py --extract",
            "script_version": SCRIPT_VERSION,
            "final_hits": final_hits,
            "review": {
                "fields": len(review_rows),
                "needs_review": len(pending),
                "decisions_applied": len(applied_decisions),
                "documents_excluded_by_decision": len(excluded_by_decision),
            },
        }
        na_path = os.path.join(out_dir, "missing_by_source.csv")
        with open(na_path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["field", "bucket", "n", "share_of_na"])
            for fname in ds_field_names:
                per_field = ds_na_by_source.get(fname, {})
                total = sum(per_field.values())
                for bucket in ("not_found", "negated", "redacted", "na_phrase",
                               "unparsed", "decision_na"):
                    count = per_field.get(bucket, 0)
                    if not count:
                        continue
                    writer.writerow([fname, bucket, count,
                                     f"{count / total:.3f}" if total else ""])
        print(f"missing: {na_path}")
        print(f"review: {review_path} ({len(pending)} field(s) flagged)")
        print(f"candidates: {candidates_path}")
        print(f"decisions todo: {todo_path}")
        # run.json is shared by every producer that writes into this directory.
        # Overwriting it wholesale would drop the other script's version stamp,
        # so each producer stores itself under "producers" and the top level is
        # kept for compatibility with a single-producer directory.
        merged = {}
        if os.path.exists(run_path):
            try:
                with open(run_path, encoding="utf-8-sig") as fh:
                    merged = json.load(fh) or {}
            except (OSError, json.JSONDecodeError):
                merged = {}
        producers = dict(merged.get("producers") or {})
        producers["make_coding_sheet.py --extract"] = run
        merged.setdefault("schema", "run.json v2")
        merged["extract"] = run
        # Mirror the current extraction, so legacy readers do not see stale
        # documents/fields after a decisions-based re-run.
        for key, value in run.items():
            merged[key] = value
        # `review` describes this extraction run, not the first one that ever
        # wrote into the directory; a stale count here hides an unresolved
        # field after a re-run with --decisions.
        merged["review"] = run["review"]
        merged["producers"] = producers
        with open(run_path, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=1)
        print(f"dataset: {ds_path} ({len(ds_rows)} rows, {len(ds_field_names)} fields)")
        print(f"evidence: {ev_path} ({len(ds_evidence)} rows)")
        print(f"run: {run_path}")
        # An extractor that hits nothing must not look like success: pointing a
        # profile at the wrong corpus yields a full dataset of NAs and exit 0.
        if args.require_review and pending:
            print(f"ERROR: {len(pending)} extracted field(s) still need review; "
                  f"fill {todo_path} into decisions.jsonl, validate it with "
                  f"check_decisions.py, then re-run with --decisions",
                  file=sys.stderr)
            return 2
        if ds_errors:
            print(f"ERROR: {ds_errors} document(s) failed field extraction; see evidence/run.json and repair before final use", file=sys.stderr)
            return 2
        empty = [n for n in ds_field_names if not ds_hit_counts.get(n, 0)]
        explicit_all_na = bool(ds_evidence) and all(
            field.get("source") == "decision:na" or field.get("na") or field.get("negated") or field.get("redacted")
            for rec in ds_evidence for field in rec.get("fields", {}).values())
        if len(empty) == len(ds_field_names) and not explicit_all_na:
            print(f"ERROR: profile '{extract_profile['profile']}' matched 0 of "
                  f"{len(ds_field_names)} fields in {len(ds_rows)} document(s); the "
                  f"profile does not fit this corpus (check --extract, scope and "
                  f"section markers)", file=sys.stderr)
            return 2
        if empty:
            print(f"warning: {len(empty)}/{len(ds_field_names)} field(s) never hit: "
                  f"{', '.join(empty[:8])}"
                  + (" …" if len(empty) > 8 else ""), file=sys.stderr)

    if not rows and keep_paths is not None and listed_paths:
        # Nothing matched: is this a filter, or a wrong --root?  A mismatch is a
        # usage error, and saying so is the difference between a five-minute fix
        # and a fruitless hunt for a corrupt corpus.
        overlap = len({_norm_rel(r["rel_path"]) for r in skipped} & listed_paths)
        if overlap == 0:
            sample_audit = sorted(listed_paths)[0]
            print("ERROR: --audit lists a different directory than --root "
                  f"(no path overlap at all). audit example: {sample_audit!r}; "
                  "re-run audit_corpus.py on this --root or pass the matching "
                  "--root", file=sys.stderr)
            return 2
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
