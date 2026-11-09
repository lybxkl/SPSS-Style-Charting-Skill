#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit a document corpus before coding.

Scans a folder, classifies every file (valid / metadata / hidden / unsupported /
quarantined / zero-byte / corrupt / encrypted / textless / image-only), computes
MD5, finds byte-identical duplicates, and writes a CSV, a JSON summary, a
duplicate list, and a Markdown report. Unmatched files are reported, not silently
skipped, so total_files reconciles with Explorer/Finder.

Usage:
    python audit_corpus.py --root "语料目录" --out-dir "output/audit"
    python audit_corpus.py --root "语料目录" --out-dir "output/audit" --fail-on-issues

Dependency: PyMuPDF (`pip install pymupdf`).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None


CASE_NO_RE = re.compile(
    r"[（(]\s*(?:19|20)\d{2}\s*[）)]\s*[\u4e00-\u9fa5A-Za-z0-9*＊×\s]{0,30}?"
    r"(?:刑初|刑终|刑再|刑更|民初|民终|行初|行终)\s*\d+\s*号"
)
YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def win_path(path: str) -> str:
    """Prefix long Windows paths so PyMuPDF can open them."""
    path = os.path.abspath(path)
    if os.name == "nt" and len(path) > 240 and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + path
    return path


def md5_file(path: str, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with open(win_path(path), "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def year_hint(name: str) -> str:
    m = YEAR_RE.search(name)
    return m.group(0) if m else ""


def has_case_no(name: str) -> bool:
    return bool(CASE_NO_RE.search(name))


def classify_pdf(path: str, min_chars: int) -> dict:
    rec = {
        "pages": None,
        "chars": None,
        "images": None,
        "encrypted": None,
        "error": "",
    }
    if fitz is None:
        rec["error"] = "PyMuPDF not installed"
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
            # A password-protected PDF cannot be read without credentials.
            return rec
        try:
            rec["chars"] = sum(len(page.get_text("text")) for page in doc)
            rec["images"] = sum(len(page.get_images(full=True)) for page in doc)
        except ValueError as exc:
            if "encrypt" in str(exc).lower():
                rec["encrypted"] = 1
            else:
                raise
    except Exception as exc:
        rec["error"] = f"read:{type(exc).__name__}:{exc}"[:300]
    finally:
        doc.close()
    return rec


def classify_text(path: str) -> dict:
    """Count characters in a plain-text document; used by --ext txt/md/csv."""
    rec = {"pages": 1, "chars": None, "images": 0, "encrypted": 0, "error": ""}
    try:
        raw = open(path, "rb").read()
    except Exception as exc:
        rec["error"] = f"open:{type(exc).__name__}:{exc}"[:300]
        return rec
    text = None
    for enc in ("utf-8-sig", "gb18030", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        rec["error"] = "decode: unable to decode text file"
        return rec
    rec["chars"] = len(text)
    return rec


def iter_files(root: str):
    """Yield every file, including hidden and quarantined ones.

    Silently skipping unmatched files makes the audit total impossible to
    reconcile with Explorer/Finder. The caller classifies them explicitly.
    """
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            yield os.path.join(dirpath, name)


def keeper_score(rec: dict) -> tuple:
    """Higher is better for the copy we keep."""
    name = rec["name"]
    return (
        1 if rec["status"] == "valid" else 0,
        1 if has_case_no(name) else 0,
        0 if re.search(r"副本|\(\d+\)|（\d+）|\.\.\.|下载", name) else 1,
        1 if rec["chars"] and rec["chars"] >= 500 else 0,
        -rec["relpath"].count(os.sep),
        -len(rec["relpath"]),
    )


def write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a PDF corpus before coding.")
    parser.add_argument("--root", required=True, help="corpus root folder")
    parser.add_argument("--out-dir", default="output/audit", help="output folder")
    parser.add_argument("--ext", action="append", default=None, help="extension(s), default: pdf")
    parser.add_argument("--min-chars", type=int, default=100, help="textless threshold")
    parser.add_argument("--skip-dir", action="append", default=None,
                        help="folder name(s) to skip; default: _duplicates")
    parser.add_argument("--max-files", type=int, default=0, help="limit for a quick test")
    parser.add_argument("--no-hash", action="store_true", help="skip MD5 (disables duplicate detection)")
    parser.add_argument("--fail-on-issues", action="store_true",
                        help="exit 2 if zero-byte/corrupt/textless/duplicates are found")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 2
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    exts = {e.lower().lstrip(".") for e in (args.ext or ["pdf"])}
    unsupported = exts - {"pdf", "txt", "md", "csv"}
    if unsupported:
        print(f"ERROR: unsupported extension(s): {', '.join(sorted(unsupported))}; "
              "supported: pdf, txt, md, csv", file=sys.stderr)
        return 2
    skip_dirs = {d.strip() for d in (args.skip_dir or ["_duplicates"]) if d.strip()}
    text_exts = exts & {"txt", "md", "csv"}

    rows: list[dict] = []
    total = 0
    for path in iter_files(root):
        total += 1
        if args.max_files and total > args.max_files:
            break
        rel = os.path.relpath(path, root)
        name = os.path.basename(path)
        parts = rel.split(os.sep)
        top = parts[0] if len(parts) > 1 else ""
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        dot_underscore = name.startswith("._")
        hidden_path = any(p.startswith(".") for p in parts[:-1])
        quarantined = any(p in skip_dirs for p in parts[:-1])
        rec = {
            "relpath": rel,
            "top": top,
            "name": name,
            "ext": ext,
            "bytes": os.path.getsize(path),
            "pages": None,
            "chars": None,
            "images": None,
            "encrypted": None,
            "status": "",
            "year_hint": year_hint(name),
            "md5": "",
            "dup_group": "",
            "dup_role": "",
            "error": "",
        }
        if quarantined:
            rec["status"] = "quarantined"
            rec["error"] = f"inside skipped folder: {skip_dirs}"
        elif name == ".DS_Store":
            rec["status"] = "metadata"
        elif dot_underscore:
            # macOS AppleDouble files usually share a .pdf name but are not
            # documents. Only a genuinely readable PDF survives this branch.
            if ext not in exts or rec["bytes"] == 0:
                rec["status"] = "metadata"
                rec["error"] = "AppleDouble/metadata file; not a document"
            else:
                parsed = (classify_text(path) if ext in text_exts
                          else classify_pdf(path, args.min_chars))
                rec.update(parsed)
                if (rec["error"] or rec["encrypted"]
                        or rec["chars"] is None or rec["chars"] < args.min_chars):
                    rec["status"] = "metadata"
                    rec["error"] = "AppleDouble/metadata file; not a document"
                else:
                    rec["status"] = "valid"
                    rec["error"] = "readable document with ._ prefix; verify manually"
        elif hidden_path or name.startswith("."):
            rec["status"] = "hidden"
            rec["error"] = "hidden path; not counted as a document"
        elif ext not in exts:
            rec["status"] = "unsupported"
            rec["error"] = (f"extension '{ext or '(none)'}' not requested; "
                            f"use --ext to include it")
        elif rec["bytes"] == 0:
            rec["status"] = "zero_byte"
        else:
            parsed = classify_text(path) if ext in text_exts else classify_pdf(path, args.min_chars)
            rec.update(parsed)
            if rec["error"]:
                rec["status"] = "corrupt"
            elif rec["encrypted"]:
                rec["status"] = "encrypted"
            elif rec["chars"] is not None and rec["chars"] < args.min_chars:
                rec["status"] = "image_only" if rec["images"] else "textless"
            else:
                rec["status"] = "valid"
        if not args.no_hash and rec["status"] in {
                "valid", "corrupt", "encrypted", "textless", "image_only"}:
            try:
                rec["md5"] = md5_file(path)
            except Exception as exc:
                rec["error"] = (rec["error"] + f";md5:{exc}")[:300]
        rows.append(rec)
        if total % 200 == 0:
            print(f"  scanned {total} ...", flush=True)

    # duplicate groups
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in rows:
        if rec["md5"]:
            groups[rec["md5"]].append(rec)
    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    for gi, (digest, items) in enumerate(sorted(dup_groups.items(), key=lambda kv: -len(kv[1])), 1):
        keeper = max(items, key=keeper_score)
        for rec in items:
            rec["dup_group"] = f"G{gi:04d}"
            rec["dup_role"] = "keeper" if rec is keeper else "duplicate"

    fields = ["relpath", "top", "name", "ext", "bytes", "pages", "chars", "images",
              "encrypted", "status", "year_hint", "md5", "dup_group", "dup_role", "error"]
    audit_csv = os.path.join(out_dir, "corpus_audit.csv")
    write_csv(audit_csv, rows, fields)

    dup_rows = []
    for rec in rows:
        if rec["dup_group"]:
            dup_rows.append({
                "group": rec["dup_group"], "md5": rec["md5"], "role": rec["dup_role"],
                "top": rec["top"], "file": rec["name"], "relpath": rec["relpath"],
                "bytes": rec["bytes"], "pages": rec["pages"], "chars": rec["chars"],
            })
    dup_csv = os.path.join(out_dir, "corpus_duplicates.csv")
    write_csv(dup_csv, dup_rows, ["group", "md5", "role", "top", "file", "relpath",
                                  "bytes", "pages", "chars"])

    status_counts = Counter(r["status"] for r in rows)
    valid = [r for r in rows if r["status"] == "valid"]
    unique = [r for r in valid if r["dup_role"] != "duplicate"]
    # Sample composition describes unique analyzable documents. Counting
    # duplicate copies here inflates by_year/by_top without adding information.
    by_top = Counter(r["top"] for r in unique if r["top"])
    years = Counter(r["year_hint"] or "unknown" for r in unique)
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": root,
        "total_files": len(rows),
        "status_counts": dict(status_counts.most_common()),
        "valid_files": len(valid),
        "unique_valid_files": len(unique),
        "pages_total": sum((r["pages"] or 0) for r in valid),
        "chars_total": sum((r["chars"] or 0) for r in valid),
        "unique_pages_total": sum((r["pages"] or 0) for r in unique),
        "unique_chars_total": sum((r["chars"] or 0) for r in unique),
        "duplicate_groups": len(dup_groups),
        "duplicate_files": sum(len(v) for v in dup_groups.values()),
        "redundant_files": sum(len(v) - 1 for v in dup_groups.values()),
        "quarantined_files": status_counts.get("quarantined", 0),
        "unsupported_files": status_counts.get("unsupported", 0),
        "hidden_files": status_counts.get("hidden", 0),
        "metadata_files": status_counts.get("metadata", 0),
        "duplicate_by_top": dict(Counter(
            r["top"] for v in dup_groups.values() for r in v if r["dup_role"] == "duplicate"
        ).most_common()),
        "by_top": dict(by_top.most_common()),
        "by_year": dict(sorted(years.items())),
    }
    with open(os.path.join(out_dir, "corpus_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    lines = [
        "# 语料审计报告", "",
        f"- 目录：`{root}`",
        f"- 生成时间：{summary['generated_at']}",
        f"- 扫描文件：{summary['total_files']}",
        f"- 有效文书：{summary['valid_files']}",
        f"- 唯一样本（有效且非副本）：{summary['unique_valid_files']}",
        f"- 唯一样本总页数：{summary['unique_pages_total']:,}",
        f"- 唯一样本总字符数：{summary['unique_chars_total']:,}",
        f"- 有效文书总页数（含重复副本）：{summary['pages_total']:,}",
        f"- 有效文书总字符数（含重复副本）：{summary['chars_total']:,}",
        "", "## 文件状态", "", "| 状态 | 数量 |", "|---|---:|",
    ]
    for k, v in status_counts.most_common():
        lines.append(f"| {k} | {v} |")
    note = []
    if summary["metadata_files"]:
        note.append(f"metadata {summary['metadata_files']} 份（`._*`/`.DS_Store`）")
    if summary["hidden_files"]:
        note.append(f"hidden {summary['hidden_files']} 份（隐藏文件/目录，未计入样本）")
    if summary["unsupported_files"]:
        note.append(f"unsupported {summary['unsupported_files']} 份（扩展名不在 --ext，未解析）")
    if summary["quarantined_files"]:
        note.append(f"quarantined {summary['quarantined_files']} 份（位于 `_duplicates` 等跳过目录）")
    if note:
        lines += ["", "未计入样本文书：" + "；".join(note) + "。"]
    lines += ["", "## 重复副本", "",
              f"- 重复组：{summary['duplicate_groups']}",
              f"- 涉及文件：{summary['duplicate_files']}",
              f"- 多余副本：{summary['redundant_files']}",
              "- MD5 只能识别字节级重复；正文相同但 PDF 元数据/排版不同（MD5 不同）仍需按案号、标题或正文抽样人工复核。"]
    if summary["duplicate_by_top"]:
        lines += ["", "| 顶层目录 | 多余副本 |", "|---|---:|"]
        for k, v in summary["duplicate_by_top"].items():
            lines.append(f"| {k} | {v} |")
    lines += ["", "## 年份分布（按文件名，仅唯一样本）", "", "| 年份 | 文件数 |", "|---|---:|"]
    for k, v in sorted(years.items()):
        lines.append(f"| {k} | {v} |")
    lines += ["", "## 下一步", "",
              "1. 检查 `corpus_duplicates.csv`，确认保留/移除规则。",
              "2. 运行 `dedupe_corpus.py` 生成计划；确认后再 `--apply`。",
              "3. 将状态为 `image_only` 的文书送 OCR 或排除。",
              "4. 对 `unsupported` 文件确认是否需要转换或改用 `--ext`。",
              "5. 把本报告的数字写入 `sample_flow.md`。"]
    with open(os.path.join(out_dir, "corpus_report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"\nscanned: {len(rows)}  valid: {len(valid)}")
    print("status:", dict(status_counts.most_common()))
    print(f"duplicates: {summary['duplicate_groups']} groups / "
          f"{summary['redundant_files']} redundant")
    print(f"output: {out_dir}")

    issues = (status_counts.get("zero_byte", 0) + status_counts.get("corrupt", 0)
              + status_counts.get("encrypted", 0) + status_counts.get("textless", 0)
              + status_counts.get("image_only", 0) + summary["redundant_files"])
    if args.fail_on_issues and issues:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
