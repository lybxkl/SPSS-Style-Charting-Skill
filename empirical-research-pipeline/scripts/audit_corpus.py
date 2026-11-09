#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit a folder of research materials before coding or analysis.

Scans every file, classifies it (valid / metadata / hidden / unsupported /
quarantined / zero_byte / corrupt / encrypted / textless / image_only / media),
computes MD5, finds byte-identical duplicates, and writes a CSV, JSON summary,
duplicate list, and Markdown report. Unmatched files are reported, not silently
skipped, so total_files reconciles with Explorer/Finder.

Supported natively: PDF, DOCX, ODT, PPTX, XLSX/XLSM, HTML, plain text, CSV/TSV,
JSON/JSONL, XML, YAML, RTF, images (inventory only), audio/video (inventory
only). Legacy .doc/.xls/.ppt and archives are inventoried as unsupported with a
conversion hint. No legal-domain assumptions are made.

Usage:
    python audit_corpus.py --root "资料目录" --out-dir "output/audit"
    python audit_corpus.py --root "资料目录" --out-dir "output/audit" --fail-on-issues
    python audit_corpus.py --list-ext
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

from text_extract import (
    STRUCTURED_EXTS, SUPPORTED_EXTS,
    inspect_file, kind_of, win_path,
)

YEAR_RE = re.compile(r"(?:19|20)\d{2}")


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


def iter_files(root: str):
    """Yield every file, including hidden and quarantined ones."""
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            yield os.path.join(dirpath, name)


def keeper_score(rec: dict) -> tuple:
    """Higher is better for the copy we keep."""
    name = rec["name"]
    return (
        1 if rec["status"] == "valid" else 0,
        1 if year_hint(name) else 0,
        0 if re.search(r"副本|\(\d+\)|（\d+）|\.\.\.|下载|copy|duplicate", name, re.I) else 1,
        1 if rec["chars"] and rec["chars"] >= 500 else 0,
        -rec["relpath"].count(os.sep),
        -len(rec["relpath"]),
    )


def write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def classify(path: str, ext: str, min_chars: int) -> tuple[str, dict]:
    kind = kind_of(path)
    if kind == "image":
        return "image_only", inspect_file(path)
    if kind == "media":
        return "media", inspect_file(path)
    parsed = inspect_file(path)
    if parsed.get("error"):
        low = parsed["error"].lower()
        if ("not installed" in low or "requires" in low or "convert " in low
                or "first" in low or "extract" in low):
            return "unsupported", parsed
        return "corrupt", parsed
    if parsed.get("encrypted"):
        return "encrypted", parsed
    if ext in STRUCTURED_EXTS or kind == "spreadsheet":
        return ("valid", parsed) if (parsed.get("chars") or 0) > 0 else ("textless", parsed)
    if parsed.get("chars") is not None and parsed["chars"] < min_chars:
        if kind == "pdf" and parsed.get("images"):
            return "image_only", parsed
        return "textless", parsed
    return "valid", parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit research materials before coding.")
    parser.add_argument("--root", default=None, help="materials root folder")
    parser.add_argument("--out-dir", default="output/audit", help="output folder")
    parser.add_argument("--ext", action="append", default=None,
                        help="extension(s) to parse; default: all supported types")
    parser.add_argument("--min-chars", type=int, default=100, help="textless threshold")
    parser.add_argument("--skip-dir", action="append", default=None,
                        help="folder name(s) to skip; default: _duplicates")
    parser.add_argument("--max-files", type=int, default=0, help="limit for a quick test")
    parser.add_argument("--no-hash", action="store_true", help="skip MD5 (disables duplicate detection)")
    parser.add_argument("--fail-on-issues", action="store_true",
                        help="exit 2 if zero-byte/corrupt/textless/image_only/duplicates are found")
    parser.add_argument("--list-ext", action="store_true", help="print supported extensions and exit")
    args = parser.parse_args()

    if args.list_ext:
        print(" ".join(sorted(SUPPORTED_EXTS)))
        return 0
    if not args.root:
        print("ERROR: --root is required (except with --list-ext)", file=sys.stderr)
        return 2

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"ERROR: root not found: {root}", file=sys.stderr)
        return 2
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    requested = {e.lower().lstrip(".") for e in args.ext} if args.ext else None
    if requested:
        unknown = requested - SUPPORTED_EXTS
        if unknown:
            print(f"ERROR: unsupported extension(s): {', '.join(sorted(unknown))}; "
                  f"run --list-ext for the supported list", file=sys.stderr)
            return 2
    exts = requested
    skip_dirs = {d.strip() for d in (args.skip_dir or ["_duplicates"]) if d.strip()}

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
            "kind": kind_of(path),
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
            if (exts is not None and ext not in exts) or rec["bytes"] == 0:
                rec["status"] = "metadata"
                rec["error"] = "AppleDouble/metadata file; not a document"
            else:
                status, parsed = classify(path, ext, args.min_chars)
                rec.update(parsed)
                if status == "valid":
                    rec["status"] = "valid"
                    rec["error"] = "readable file with ._ prefix; verify manually"
                else:
                    rec["status"] = "metadata"
                    rec["error"] = "AppleDouble/metadata file; not a document"
        elif hidden_path or name.startswith("."):
            rec["status"] = "hidden"
            rec["error"] = "hidden path; not counted as an analyzable file"
        elif exts is not None and ext not in exts:
            rec["status"] = "unsupported"
            rec["error"] = (f"extension '{ext or '(none)'}' not requested; "
                            f"use --ext to include it")
        elif ext not in SUPPORTED_EXTS:
            rec["status"] = "unsupported"
            rec["error"] = f"no parser for .{ext or '(none)'}; convert or extract first"
        elif rec["bytes"] == 0:
            rec["status"] = "zero_byte"
        else:
            status, parsed = classify(path, ext, args.min_chars)
            rec.update(parsed)
            rec["status"] = status
        if not args.no_hash and rec["status"] not in {"metadata", "hidden", "quarantined", "zero_byte"}:
            try:
                rec["md5"] = md5_file(path)
            except Exception as exc:
                rec["error"] = (rec["error"] + f";md5:{exc}")[:300]
        rows.append(rec)
        if total % 200 == 0:
            print(f"  scanned {total} ...", flush=True)

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

    fields = ["relpath", "top", "name", "ext", "kind", "bytes", "pages", "chars", "images",
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
    by_top = Counter(r["top"] for r in unique if r["top"])
    by_ext = Counter((r["ext"] or "(none)") for r in unique)
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
        "media_files": status_counts.get("media", 0),
        "image_only_files": status_counts.get("image_only", 0),
        "duplicate_by_top": dict(Counter(
            r["top"] for v in dup_groups.values() for r in v if r["dup_role"] == "duplicate"
        ).most_common()),
        "by_top": dict(by_top.most_common()),
        "by_ext": dict(by_ext.most_common()),
        "by_year": dict(sorted(years.items())),
    }
    with open(os.path.join(out_dir, "corpus_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    lines = [
        "# 资料审计报告", "",
        f"- 目录：`{root}`",
        f"- 生成时间：{summary['generated_at']}",
        f"- 扫描文件：{summary['total_files']}",
        f"- 有效资料：{summary['valid_files']}",
        f"- 唯一样本（有效且非副本）：{summary['unique_valid_files']}",
        f"- 唯一样本总页数/表数：{summary['unique_pages_total']:,}",
        f"- 唯一样本总字符数：{summary['unique_chars_total']:,}",
        f"- 有效资料总页数/表数（含重复副本）：{summary['pages_total']:,}",
        f"- 有效资料总字符数（含重复副本）：{summary['chars_total']:,}",
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
        note.append(f"unsupported {summary['unsupported_files']} 份（格式未解析或需先转换/解压）")
    if summary["quarantined_files"]:
        note.append(f"quarantined {summary['quarantined_files']} 份（位于 `_duplicates` 等跳过目录）")
    if summary["media_files"]:
        note.append(f"media {summary['media_files']} 份（音视频，需先转写）")
    if summary["image_only_files"]:
        note.append(f"image_only {summary['image_only_files']} 份（图片，需先 OCR）")
    if note:
        lines += ["", "未计入可分析文本：" + "；".join(note) + "。"]
    lines += ["", "## 按扩展名（仅唯一样本）", "", "| 扩展名 | 文件数 |", "|---|---:|"]
    for k, v in by_ext.most_common():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## 重复副本", "",
              f"- 重复组：{summary['duplicate_groups']}",
              f"- 涉及文件：{summary['duplicate_files']}",
              f"- 多余副本：{summary['redundant_files']}",
              "- MD5 只能识别字节级重复；内容相同但元数据/排版/导出设置不同（MD5 不同）仍需按标题或正文抽样人工复核。"]
    if summary["duplicate_by_top"]:
        lines += ["", "| 顶层目录 | 多余副本 |", "|---|---:|"]
        for k, v in summary["duplicate_by_top"].items():
            lines.append(f"| {k} | {v} |")
    lines += ["", "## 年份提示（按文件名，仅唯一样本）", "", "| 年份 | 文件数 |", "|---|---:|"]
    for k, v in sorted(years.items()):
        lines.append(f"| {k} | {v} |")
    lines += ["", "## 下一步", "",
              "1. 检查 `corpus_duplicates.csv`，确认保留/移除规则。",
              "2. 运行 `dedupe_corpus.py` 生成计划；确认后再 `--apply`。",
              "3. 图片先 OCR；音视频先转写；压缩包先解压；旧版 Office 先转换。",
              "4. 对 `unsupported`/`textless` 文件确认是否需要转换或排除。",
              "5. 把本报告的数字写入 `sample_flow.md`；表格数据另做字段质量检查。"]
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
