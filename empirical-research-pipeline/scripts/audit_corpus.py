#!/usr/bin/env python3
"""Audit a corpus directory and record every file in a machine-readable table.

Usage:
    python audit_corpus.py --root <dir> [--out-dir output/audit] [--ext pdf]
        [--min-chars 100] [--skip-dir _duplicates] [--max-files 0]
        [--no-hash] [--content-dedupe] [--fail-on-issues] [--list-ext]

Outputs (all inside --out-dir):
    corpus_files.csv       one row per file, every column documented in
                           references/01-corpus-audit.md
    corpus_duplicates.csv  one row per byte-level duplicate copy
    corpus_summary.json    aggregates + sampling_frame (what exactly was scanned)
    corpus_report.md       human-readable report

Guarantees:
    * A per-file failure never aborts the scan: unreadable files are recorded
      with status="unreadable" and an error message.
    * `--fail-on-issues` returns 2 when any blocking issue remains, including
      unreadable files.
    * `--out-dir` inside `--root` is skipped so a second run cannot audit its
      own outputs.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime

from text_extract import (
    STRUCTURED_EXTS,
    SUPPORTED_EXTS,
    extract_text,
    inspect_file,
    kind_of,
    win_path,
)

HIDDEN_ATTR = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2)
# Written into every product: a report on a desk is worthless if nobody can tell
# which version of the script produced it.
SCRIPT_VERSION = "2.0.0"
YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
BRACKET_YEAR_RE = re.compile(r"[（(]((?:19|20)\d{2})[)）]")
COPY_MARKER_RE = re.compile(r"副本|复件|复印件|copy|_dup|dup\d|\(1\)|（1）", re.I)
KEEPER_REASONS = (
    "valid_status",
    "year_hint",
    "no_copy_marker",
    "shortest_path",
    "shortest_path",
    "text_completeness",
    "largest_bytes",
)
ERROR_KIND_STATUS = {
    "encrypted": "encrypted",
    "encrypted_office": "encrypted",
    "unsupported": "unsupported",
    "missing_dep": "unsupported",
    "too_large": "unsupported",
    "binary": "corrupt",
    "broken": "corrupt",
    "permission": "corrupt",
    "mojibake": "corrupt",
}

FIELDS = [
    "rel_path", "relpath", "top", "name", "ext", "kind", "bytes",
    "pages", "chars", "chars_effective", "images", "encrypted",
    "status", "year_hint", "md5", "dup_group", "dup_content_group",
    "dup_role", "dup_role_content", "dedupe_group", "dedupe_role", "error", "error_kind",
]
DUP_FIELDS = [
    "group", "md5", "role", "keeper_reason", "top", "file", "rel_path",
    "relpath", "bytes", "pages", "chars", "chars_effective",
]
# Files this script writes into --out-dir. When --out-dir is the scan root
# itself, these names are excluded so a second run cannot audit its own output.
OUTPUT_NAMES = frozenset({
    "corpus_files.csv",
    "corpus_audit.csv",
    "corpus_duplicates.csv",
    "corpus_summary.json",
    "corpus_report.md",
    "sample_flow.csv",
})


def md5_file(path: str, chunk: int = 1 << 20) -> str:
    digest = hashlib.md5()
    with open(win_path(path), "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def year_hint(name: str) -> str:
    """Best-effort publication year from a file name.

    Bracketed years win (``报告(2021).pdf``).  A bare year must be a standalone
    token: ``1920px.png`` is a width and ``file-2000-1.pdf`` a sequence number,
    so neither yields a year.
    """
    match = BRACKET_YEAR_RE.search(name)
    if match:
        return match.group(1)
    for match in YEAR_RE.finditer(name):
        tail = name[match.end():]
        if re.match(r"px\b", tail, re.I) or re.match(r"[-_]\d", tail):
            continue
        return match.group(1)
    return ""


def has_copy_marker(name: str) -> bool:
    return bool(COPY_MARKER_RE.search(name))


def hidden_attr(path: str) -> bool:
    """Windows hidden attribute (dot prefixes are handled separately)."""
    if os.name != "nt":
        return False
    try:
        attrs = os.stat(win_path(path)).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attrs & HIDDEN_ATTR)


def hidden_by_attr(path: str, root: str, cache: dict) -> bool:
    """True when the file or any ancestor directory carries the hidden attribute."""
    if os.name != "nt":
        return False
    base = os.path.abspath(root)
    current = os.path.abspath(path)
    while True:
        key = os.path.normcase(current)
        if key not in cache:
            cache[key] = hidden_attr(current)
        if cache[key]:
            return True
        if os.path.normcase(current) == os.path.normcase(base):
            return False
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def iter_files(root: str, walk_errors: list[str]):
    """Yield every file under root, collecting directory walk errors."""

    def onerror(exc):
        walk_errors.append(f"{getattr(exc, 'filename', root)}: {type(exc).__name__}: {exc}")

    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
        dirnames.sort()
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def keeper_score(rec: dict) -> tuple:
    """Ranking used to elect the keeper inside a duplicate group (lower wins).

    Order follows references/01-corpus-audit.md: still readable, year in the
    name, no copy marker, shorter/shallower path, more complete text, bytes.
    """
    return (
        0 if rec["status"] == "valid" else 1,
        -int(rec["year_hint"] or 0),
        1 if has_copy_marker(rec["name"]) else 0,
        rec["_depth"],
        len(rec["relpath"]),
        0 if (rec["chars_effective"] or 0) >= 500 else 1,
        -(rec["bytes"] or 0),
    )


def pick_keeper(items: list[dict]) -> tuple[dict, str]:
    """Return (keeper, reason). Ties keep the first file and are marked tie_first."""
    ranked = sorted(items, key=keeper_score)
    keeper = ranked[0]
    if len(ranked) == 1:
        return keeper, "only_copy"
    best, runner_up = keeper_score(keeper), keeper_score(ranked[1])
    if best == runner_up:
        return keeper, "tie_first"
    for index, label in enumerate(KEEPER_REASONS):
        if best[index] != runner_up[index]:
            return keeper, label
    return keeper, "tie_first"


def write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def classify(path: str, rec: dict, ext: str, min_chars: int) -> str:
    """Map one inspect_file() record to a status (see references/01-corpus-audit.md)."""
    kind = kind_of(path)
    if kind == "image":
        return "image_only"
    if kind == "media":
        return "media"
    error_kind = rec.get("error_kind") or ""
    if error_kind:
        return ERROR_KIND_STATUS.get(error_kind, "corrupt")
    error = (rec.get("error") or "").lower()
    # Partial reads ("read:2/9 pages unreadable") keep the salvaged text, so
    # they are judged by the character count like any other readable file.
    partial_read = error.startswith("read:") and "pages unreadable" in error
    if error and not partial_read:
        if any(word in error for word in ("archive", "legacy office", "audio/video", "unsupported")):
            return "unsupported"
        if "not installed" in error:
            return "unsupported"
        return "corrupt"
    chars = rec.get("chars_effective") or 0
    if rec.get("encrypted") and chars == 0:
        # Permission-encrypted PDFs that still yield readable text are not
        # discarded: only a genuinely unreadable document counts as encrypted.
        return "encrypted"
    if ext in STRUCTURED_EXTS:
        return "valid" if chars > 0 else "textless"
    if chars < min_chars:
        if ext == "pdf" and (rec.get("images") or 0):
            return "image_only"
        return "textless"
    return "valid"


def content_key(text: str) -> str:
    """Conservative text identity: preserve punctuation, decimals and case."""
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest() if normalized else ""


def mark_groups(rows: list[dict], key_field: str, group_field: str,
                role_field: str, reason_field: str | None = None) -> dict:
    """Assign group labels/roles for rows sharing a non-empty key."""
    buckets = defaultdict(list)
    for row in rows:
        if row.get(key_field):
            buckets[row[key_field]].append(row)
    groups = 0
    files = 0
    redundant = 0
    ties = 0
    for items in sorted(buckets.values(), key=lambda group: group[0]["relpath"]):
        if len(items) < 2:
            continue
        groups += 1
        files += len(items)
        redundant += len(items) - 1
        label = f"G{groups:04d}"
        keeper, reason = pick_keeper(items)
        if reason == "tie_first":
            ties += 1
        for item in items:
            item[group_field] = label
            item[role_field] = "keeper" if item is keeper else "duplicate"
            if reason_field:
                item[reason_field] = reason
    return {"groups": groups, "files": files, "redundant": redundant, "ties": ties}


def consolidate_duplicates(rows):
    """Union byte/content duplicate components and elect exactly one keeper."""
    parent = list(range(len(rows)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for column in ("dup_group", "dup_content_group"):
        first = {}
        for i, row in enumerate(rows):
            label = row.get(column)
            if label:
                if label in first:
                    parent[find(i)] = find(first[label])
                else:
                    first[label] = i
    groups = defaultdict(list)
    for i, row in enumerate(rows):
        row["dedupe_group"] = row["dedupe_role"] = ""
        groups[find(i)].append(row)
    seq = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        seq += 1
        keeper, _ = pick_keeper(group)
        for row in group:
            row["dedupe_group"] = f"D{seq:04d}"
            row["dedupe_role"] = "keeper" if row is keeper else "duplicate"


def fmt_int(value) -> str:
    return f"{value:,}" if isinstance(value, int) else str(value)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Audit a corpus: status, duplicates, sampling frame, report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit codes: 0 ok, 2 parameter error / blocking issues (--fail-on-issues).",
    )
    ap.add_argument("--root", help="corpus root to scan")
    ap.add_argument("--out-dir", default="output/audit", help="output directory")
    ap.add_argument("--ext", action="append", default=[], help="only these extensions")
    ap.add_argument("--min-chars", type=int, default=100,
                    help="minimum *effective* characters (page-number lines and "
                         "whitespace excluded) for a document to count as valid")
    ap.add_argument("--skip-dir", action="append", default=[], help="directory name to skip")
    ap.add_argument("--max-files", type=int, default=0, help="scan at most N files (0 = all)")
    ap.add_argument("--no-hash", action="store_true", help="skip MD5 hashing")
    ap.add_argument("--content-dedupe", action="store_true",
                    help="also group valid files by normalized text (sha1); slower")
    ap.add_argument("--fail-on-issues", action="store_true",
                    help="exit 2 when zero-byte/corrupt/encrypted/textless/image_only/"
                         "redundant/unreadable files remain")
    ap.add_argument("--list-ext", action="store_true", help="print supported extensions")
    args = ap.parse_args(argv)

    if args.list_ext:
        print("supported extensions: " + " ".join(sorted(SUPPORTED_EXTS)))
        return 0
    if not args.root:
        print("error: --root is required (or use --list-ext)", file=sys.stderr)
        return 2

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"error: --root is not a directory: {args.root}", file=sys.stderr)
        return 2
    out_dir = os.path.abspath(args.out_dir)

    requested = [e.lower().lstrip(".") for e in args.ext]
    unknown = sorted(set(requested) - SUPPORTED_EXTS)
    if unknown:
        print(f"error: unsupported --ext value(s): {', '.join(unknown)}", file=sys.stderr)
        print("hint: run with --list-ext to see the supported set", file=sys.stderr)
        return 2
    only_ext = set(requested)

    skip_dirs = [d for d in args.skip_dir if d] or ["_duplicates"]
    # AUD-11: an --out-dir inside --root would otherwise be re-scanned forever.
    out_inside = False
    out_same_root = False
    out_products_skipped = 0
    out_rel = ""
    out_note = ""
    try:
        common = os.path.commonpath([out_dir, root])
    except ValueError:
        common = ""
    if common and os.path.normcase(common) == os.path.normcase(root):
        same_dir = (os.path.normcase(os.path.realpath(out_dir))
                    == os.path.normcase(os.path.realpath(root)))
        if same_dir:
            out_same_root = True
            out_note = "out-dir 与 root 相同，已按产物文件名跳过自身产出"
        else:
            out_rel = os.path.relpath(out_dir, root).replace(os.sep, "/")
            out_inside = True
            out_note = f"输出目录 {out_rel} 位于扫描根内，已跳过"
    skip_fold = {os.path.normcase(d) for d in skip_dirs}

    os.makedirs(out_dir, exist_ok=True)
    walk_errors: list[str] = []
    hidden_cache: dict[str, bool] = {}
    rows: list[dict] = []
    unreadable = 0
    truncated = False
    seen = 0

    for path in iter_files(root, walk_errors):
        if args.max_files and len(rows) >= args.max_files:
            truncated = True
            break
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        if out_same_root and "/" not in rel and rel in OUTPUT_NAMES:
            out_products_skipped += 1
            continue  # known product of a previous run; never audit it
        if out_inside and (rel == out_rel or rel.startswith(out_rel + "/")):
            continue  # do not audit our own outputs
        seen += 1
        name = os.path.basename(path)
        parts = rel.split("/")
        top = parts[0] if len(parts) > 1 else "(root)"
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        quarantined = any(os.path.normcase(p) in skip_fold for p in parts[:-1])
        rec = {
            "rel_path": rel, "relpath": rel, "top": top, "name": name, "ext": ext,
            "kind": kind_of(path), "bytes": None, "pages": None, "chars": None,
            "chars_effective": None, "images": None, "encrypted": None,
            "status": "", "year_hint": year_hint(name), "md5": "",
            "dup_group": "", "dup_content_group": "", "dup_role": "",
            "dup_role_content": "", "error": "", "error_kind": "", "_depth": len(parts) - 1,
        }
        try:
            st = os.stat(win_path(path))
            rec["bytes"] = st.st_size
            hidden_path = (
                any(p.startswith(".") for p in parts[:-1])
                or name.startswith(".")
                or hidden_by_attr(path, root, hidden_cache)
            )
            in_filter = not only_ext or ext in only_ext

            if quarantined:
                status = "quarantined"
            elif name == ".DS_Store":
                status = "metadata"
            elif name.startswith("._"):
                status = "metadata"
                if in_filter and st.st_size > 0:
                    meta = inspect_file(path)
                    candidate = classify(path, meta, ext, args.min_chars)
                    rec.update({k: meta.get(k) for k in
                                ("pages", "chars", "chars_effective", "images", "encrypted")})
                    rec["error"] = meta.get("error") or ""
                    rec["error_kind"] = meta.get("error_kind") or ""
                    if candidate == "valid":
                        status = "valid"
                        rec["error"] = "readable file with ._ prefix; verify manually"
                        rec["error_kind"] = ""
            elif hidden_path:
                status = "hidden"
            elif not in_filter:
                status = "unsupported"
                rec["error"] = f"not in --ext selection: .{ext or '(none)'}"
                rec["error_kind"] = "unsupported"
            elif ext not in SUPPORTED_EXTS:
                status = "unsupported"
                rec["error"] = f"unsupported extension: .{ext or '(none)'}"
                rec["error_kind"] = "unsupported"
            elif st.st_size == 0:
                status = "zero_byte"
            else:
                meta = inspect_file(path)
                rec.update({k: meta.get(k) for k in
                            ("pages", "chars", "chars_effective", "images", "encrypted")})
                rec["error"] = meta.get("error") or ""
                rec["error_kind"] = meta.get("error_kind") or ""
                status = classify(path, rec, ext, args.min_chars)
            rec["status"] = status
        except Exception as exc:
            unreadable += 1
            rec["status"] = "unreadable"
            rec["error"] = f"{type(exc).__name__}:{exc}"[:300]
            rec["error_kind"] = "unreadable"
            rows.append(rec)
            continue

        if not args.no_hash and rec["status"] not in {"metadata", "hidden", "quarantined",
                                                       "zero_byte", "unreadable", "unsupported"}:
            try:
                rec["md5"] = md5_file(path)
            except OSError as exc:
                print(f"warning: cannot hash {rel}: {exc}", file=sys.stderr)
                rec["error"] = rec["error"] or f"md5 failed: {type(exc).__name__}"
        rows.append(rec)
        if len(rows) % 200 == 0:
            print(f"  ... scanned {len(rows)} files")

    # Byte-level duplicate groups (same MD5).
    byte_stats = {"groups": 0, "files": 0, "redundant": 0, "ties": 0}
    if not args.no_hash:
        byte_stats = mark_groups(rows, "md5", "dup_group", "dup_role", "keeper_reason")
    else:
        for row in rows:
            row["md5"] = ""
            row["dup_group"] = ""
            row["dup_role"] = ""

    # Content-level duplicate groups (same normalized text); opt-in because it
    # re-extracts every valid document.
    content_stats = {"groups": 0, "files": 0, "redundant": 0, "ties": 0}
    content_errors = 0
    if args.content_dedupe:
        for row in rows:
            if row["status"] != "valid":
                continue
            path = os.path.join(root, row["relpath"])
            try:
                row["_content"] = content_key(extract_text(path))
            except (ValueError, OSError, RuntimeError):
                row["_content"] = ""
                content_errors += 1
        content_stats = mark_groups(rows, "_content", "dup_content_group",
                                    "dup_role_content", "keeper_reason_content")
        for row in rows:
            row.pop("_content", None)

    consolidate_duplicates(rows)
    status_counts = Counter(row["status"] for row in rows)
    valid_rows = [row for row in rows if row["status"] == "valid"]
    keeper_rows = [row for row in valid_rows if row["dedupe_role"] != "duplicate"]

    def total(field: str, items: list[dict]) -> int:
        return sum(int(item.get(field) or 0) for item in items)

    pages_missing = sum(1 for row in keeper_rows if row.get("pages") is None)
    hashed = sum(1 for row in rows if row.get("md5"))
    hashable = sum(1 for row in rows if row["status"] in
                   {"valid", "corrupt", "encrypted", "textless", "image_only", "media"})
    dup_by_top = Counter(row["top"] for row in rows if row["dup_role"] == "duplicate")
    by_top = Counter(row["top"] for row in keeper_rows)
    by_ext = Counter(row["ext"] or "(none)" for row in keeper_rows)
    by_year = Counter(row["year_hint"] for row in keeper_rows if row["year_hint"])

    if out_same_root:
        out_note = (f"out-dir 与 root 相同，已按产物文件名跳过 "
                    f"{out_products_skipped} 个自身产出")

    # Corpus fingerprint: a later run over the "same" folder can be proven to be
    # the same corpus (or not) without keeping the files. Sorted, so a different
    # walk order does not fake a different corpus.
    fingerprint = hashlib.sha256()
    for row in sorted(rows, key=lambda r: r["rel_path"]):
        fingerprint.update(("%s\t%s\t%s\n" % (
            row["rel_path"], row.get("bytes") or 0, row.get("md5") or "")).encode("utf-8"))

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generator_version": SCRIPT_VERSION,
        "root": root,
        "corpus_fingerprint": {
            "files": len(rows),
            "bytes": sum(int(row.get("bytes") or 0) for row in rows),
            "sha256": fingerprint.hexdigest(),
            "covers": "sorted(rel_path, bytes, md5) — one line per file",
        },
        "sampling_frame": {
            "root": root,
            "ext": sorted(only_ext),
            "skip_dir": skip_dirs,
            "min_chars": args.min_chars,
            "content_dedupe": bool(args.content_dedupe),
            "generated_by": "audit_corpus.py",
        },
        "out_dir": out_dir,
        "out_dir_inside_root": out_inside,
        "out_dir_same_as_root": out_same_root,
        "out_products_skipped": out_products_skipped,
        "total_files": len(rows),
        "status_counts": dict(status_counts),
        "unreadable_files": unreadable,
        "walk_errors": walk_errors[:50],
        "walk_error_count": len(walk_errors),
        "max_files": args.max_files,
        "truncated": truncated,
        "hash_disabled": bool(args.no_hash),
        "md5_coverage": {"hashed": hashed, "hashable": hashable},
        "valid_files": len(valid_rows),
        "unique_valid_files": len(keeper_rows),
        "pages_total": total("pages", valid_rows),
        "chars_total": total("chars", valid_rows),
        "chars_effective_total": total("chars_effective", valid_rows),
        "unique_pages_total": total("pages", keeper_rows),
        "unique_chars_total": total("chars", keeper_rows),
        "unique_chars_effective_total": total("chars_effective", keeper_rows),
        "pages_missing": pages_missing,
        "duplicate_groups": byte_stats["groups"],
        "duplicate_files": byte_stats["files"],
        "redundant_files": byte_stats["redundant"],
        "keeper_ties": byte_stats["ties"],
        "content_duplicate_groups": content_stats["groups"],
        "content_duplicate_files": content_stats["files"],
        "content_redundant_files": content_stats["redundant"],
        "content_dedupe_errors": content_errors,
        "quarantined_files": status_counts.get("quarantined", 0),
        "unsupported_files": status_counts.get("unsupported", 0),
        "hidden_files": status_counts.get("hidden", 0),
        "metadata_files": status_counts.get("metadata", 0),
        "media_files": status_counts.get("media", 0),
        "image_only_files": status_counts.get("image_only", 0),
        "duplicate_by_top": dict(dup_by_top),
        "by_top": dict(by_top),
        "by_ext": dict(by_ext),
        "by_year": dict(by_year),
    }
    # The funnel is a machine-readable contract, not a paragraph in the report:
    # auto_stats --sample-flow and verify_numbers V-06 both read this very file,
    # and CONTRACTS promised it long before anything wrote it.  Running totals
    # only, so V-06's monotonicity check means what it says.
    flow_rows = [
        {"stage": "资料总数", "n": summary["total_files"],
         "note": "every file under the root after skip-dir/exclusion filters"},
        {"stage": "可读取", "n": summary["total_files"] - summary["unreadable_files"],
         "note": "files that could be opened (unreadable excluded)"},
        {"stage": "有效资料", "n": summary["valid_files"],
         "note": f"not metadata/zero-byte, passed the chars_effective gate"},
        {"stage": "唯一样本", "n": summary["unique_valid_files"],
         "note": "byte- and content-level duplicates removed (keeper per group)"},
    ]
    write_csv(os.path.join(out_dir, "sample_flow.csv"), flow_rows,
              ["stage", "n", "note"])

    summary_path = os.path.join(out_dir, "corpus_summary.json")
    with open(summary_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    write_csv(os.path.join(out_dir, "corpus_files.csv"), rows, FIELDS)
    # Backwards compatibility: this table used to be called corpus_audit.csv and
    # every document, the README quick start and `make_coding_sheet.py --audit`
    # still point at that name.  Write the same table twice rather than rename
    # silently under existing users.
    legacy_path = os.path.join(out_dir, "corpus_audit.csv")
    if os.path.abspath(legacy_path) != os.path.abspath(os.path.join(out_dir, "corpus_files.csv")):
        write_csv(legacy_path, rows, FIELDS)

    dup_rows = []
    for row in rows:
        if row["dup_role"] and row["dup_group"]:
            dup_rows.append({
                "group": row["dup_group"], "md5": row["md5"], "role": row["dup_role"],
                "keeper_reason": row.get("keeper_reason", ""), "top": row["top"],
                "file": row["name"], "rel_path": row["relpath"], "relpath": row["relpath"],
                "bytes": row["bytes"], "pages": row["pages"], "chars": row["chars"],
                "chars_effective": row["chars_effective"],
            })
    write_csv(os.path.join(out_dir, "corpus_duplicates.csv"), dup_rows, DUP_FIELDS)

    lines = [
        "# 资料审计报告",
        "",
        f"- 目录：{root}",
        f"- 生成时间：{summary['generated_at']}",
        f"- 扫描文件：{len(rows)}",
        f"- 有效资料：{summary['valid_files']}（唯一样本 {summary['unique_valid_files']}）",
        f"- 总页数：{fmt_int(summary['pages_total'])}"
        f"（缺少页数的文件 {pages_missing} 个）",
        f"- 总字符数：{fmt_int(summary['chars_total'])}"
        f"（有效字符 {fmt_int(summary['chars_effective_total'])}）",
        "",
        "## 抽样框",
        "",
        f"- 根目录：{root}",
        f"- 扩展名：{'全部受支持格式' if not only_ext else '仅 ' + ' / '.join(sorted(only_ext))}",
        f"- 跳过目录：{', '.join(skip_dirs)}",
        f"- 最小有效字符数：{args.min_chars}（页码行与空白不计）",
        f"- 内容级去重：{'开启' if args.content_dedupe else '关闭（--content-dedupe 可开启）'}",
        f"- 输出目录：{out_dir}",
        f"- 生成脚本：audit_corpus.py",
        "- 产出：`corpus_files.csv`（逐文件清单，规范名）；"
        "`corpus_audit.csv` 是它的旧名副本，仅为兼容既有命令而写出。",
    ]
    if out_note:
        lines.append(f"- 注意：{out_note}")
    if args.max_files:
        lines.append(f"- 截断：仅扫描前 {args.max_files} 个文件"
                     + ("（已达上限）" if truncated else "（未达上限）"))
    lines += [
        "",
        "## 文件状态",
        "",
        "| 状态 | 文件数 |",
        "| --- | ---: |",
    ]
    status_label = {
        "valid": "valid 可编码", "textless": "textless 无可提取文字",
        "image_only": "image_only 需 OCR", "encrypted": "encrypted 加密/需解密",
        "corrupt": "corrupt 损坏", "unsupported": "unsupported 不支持",
        "zero_byte": "zero_byte 0 字节", "quarantined": "quarantined 隔离目录",
        "hidden": "hidden 隐藏", "metadata": "metadata 系统/附属文件",
        "media": "media 音视频", "unreadable": "unreadable 读取失败",
    }
    for key, count in sorted(status_counts.items(), key=lambda pair: -pair[1]):
        lines.append(f"| {status_label.get(key, key)} | {count} |")
    lines.append("")
    if unreadable:
        lines.append(f"- 有 {unreadable} 个文件读取失败（status=unreadable），"
                     "错误原因见 corpus_files.csv 的 error 列；请先修复权限/路径后重跑。")
    if walk_errors:
        lines.append(f"- 有 {len(walk_errors)} 个目录无法遍历，其内容未纳入抽样框。")
    if summary["metadata_files"]:
        lines.append("- metadata：.DS_Store / ._ 附属文件等，不进入编码样本。")
    if summary["hidden_files"]:
        lines.append("- hidden：文件名/目录名以点开头，或带 Windows 隐藏属性。")
    if summary["unsupported_files"]:
        lines.append("- unsupported：当前流程不处理的格式或 --ext 未选中的文件。")
    if summary["quarantined_files"]:
        lines.append("- quarantined：位于 --skip-dir（默认 _duplicates）内的文件。")
    if summary["media_files"]:
        lines.append("- media：音频/视频，需先转写再编码。")
    if summary["image_only_files"]:
        lines.append("- image_only：无文字层，需先 OCR。")
    lines.append("")
    if args.no_hash:
        lines.append("- 重复组：未检测（--no-hash）")
        lines.append("- 说明：本次未计算 MD5，corpus_duplicates.csv 为空，"
                     "不能据此判断「无重复」。")
    else:
        lines.append(f"- 字节级重复组：{summary['duplicate_groups']}"
                     f"（涉及 {summary['duplicate_files']} 个文件，"
                     f"多余副本 {summary['redundant_files']} 个，"
                     f"平局 {summary['keeper_ties']} 组）")
        lines.append(f"- MD5 覆盖率：{hashed}/{hashable} 个可哈希文件")
        if args.content_dedupe:
            lines.append(f"- 内容级重复组：{summary['content_duplicate_groups']}"
                         f"（涉及 {summary['content_duplicate_files']} 个文件，"
                         f"多余副本 {summary['content_redundant_files']} 个）")
            lines.append("- 两组关系：字节级只看字节；内容级在 valid 文件上按正文归并，"
                         "可能把多个字节组合并成一个内容组，也可能发现字节级没有的重复。"
                         "两组口径不同，不能相减，应分别报告。")
            if summary["content_dedupe_errors"]:
                lines.append(f"- 内容级覆盖：{summary['content_dedupe_errors']} 个 valid "
                             "文件没有全文（表格/数据类），由字节级去重覆盖。")
        else:
            lines.append("- 内容级重复：未检测（--content-dedupe 未开启）")
    lines += [
        "",
        "## 重复副本",
        "",
        "| 重复组 | 涉及文件 | 多余副本 |",
        "| --- | ---: | ---: |",
    ]
    if args.no_hash:
        lines.append("| 字节级 | 未检测（--no-hash） | — |")
    else:
        lines.append(f"| 字节级 | {summary['duplicate_files']} | "
                     f"{summary['redundant_files']} |")
    if args.content_dedupe:
        lines.append(f"| 内容级 | {summary['content_duplicate_files']} | "
                     f"{summary['content_redundant_files']} |")
    else:
        lines.append("| 内容级 | 未检测（--content-dedupe） | — |")
    lines += [
        "",
        "- MD5 只认字节完全一致的副本；同一文档的转码版、另排版或另存版本需要"
        "内容级去重（--content-dedupe）才能发现。",
        "- 去重前用 dedupe_corpus.py 生成计划，确认 keeper 在盘后再 --apply。",
        "",
    ]
    if dup_by_top:
        lines += ["### 重复副本所在目录（top）", "", "| top | 多余副本 |", "| --- | ---: |"]
        for key, count in sorted(dup_by_top.items(), key=lambda pair: -pair[1]):
            lines.append(f"| {key} | {count} |")
        lines.append("")
    if by_top:
        lines += ["## 按目录（仅唯一样本）", "", "| top | 唯一样本 |", "| --- | ---: |"]
        for key, count in sorted(by_top.items(), key=lambda pair: -pair[1]):
            lines.append(f"| {key} | {count} |")
        lines.append("")
    if by_ext:
        lines += ["## 按扩展名（仅唯一样本）", "", "| 扩展名 | 唯一样本 |", "| --- | ---: |"]
        for key, count in sorted(by_ext.items(), key=lambda pair: -pair[1]):
            lines.append(f"| {key} | {count} |")
        lines.append("")
    if by_year:
        lines += ["## 年份提示（按文件名，仅唯一样本）", "", "| 年份 | 文件数 |", "| --- | ---: |"]
        for key, count in sorted(by_year.items()):
            lines.append(f"| {key} | {count} |")
        lines.append("")
    lines += [
        "## 下一步",
        "",
        "1. 打开 corpus_files.csv，先处理 status=corrupt / unreadable / zero_byte 的文件。",
        "2. 对 image_only 的 PDF 先 OCR；对 media 先转写。",
        "3. 用 dedupe_corpus.py 生成计划，核对 keeper 后再 --apply（保留 move_log.csv 以便回滚）。",
        "4. 按 codebook 抽取字段，并保留 provenance（<field>_src）。",
        "5. 报告里必须写明：删除了哪些重复文件、保留哪一份、原因是什么。",
        "",
    ]
    report = "\n".join(lines) + "\n"
    report_path = os.path.join(out_dir, "corpus_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report)

    print(f"scanned: {len(rows)} files, valid: {summary['valid_files']}, "
          f"unique: {summary['unique_valid_files']}")
    print("status: " + ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items())))
    print(f"unreadable: {unreadable}")
    if args.no_hash:
        print("duplicates: not checked (--no-hash)")
    else:
        print(f"duplicate groups: {summary['duplicate_groups']}, "
              f"redundant copies: {summary['redundant_files']}")
    if args.content_dedupe:
        print(f"content duplicate groups: {summary['content_duplicate_groups']}, "
              f"redundant copies: {summary['content_redundant_files']}")
    print(f"output: {out_dir}")

    if not rows:
        print("error: no files found under --root; check the path and --ext filters",
              file=sys.stderr)
        return 2

    issues = (status_counts.get("zero_byte", 0) + status_counts.get("corrupt", 0)
              + status_counts.get("encrypted", 0) + status_counts.get("textless", 0)
              + status_counts.get("image_only", 0) + summary["redundant_files"]
              + unreadable)
    if args.fail_on_issues and issues:
        print(f"fail-on-issues: {issues} blocking issue(s)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
