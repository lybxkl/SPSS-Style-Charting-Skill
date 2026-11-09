#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract full text and candidate evidence from PDFs into a coding worksheet.

This script does NOT assign final legal codes. It produces one JSONL record per
document with the text, metadata, and keyword-hit sentences so a human or an
LLM can code against the codebook with traceable evidence.

Usage:
    python make_coding_sheet.py --root "语料目录" --out "output/coding" \\
        --keywords assets/coding-keywords.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

CASE_NO_RE = re.compile(
    r"[（(]\s*(?:19|20)\d{2}\s*[）)]\s*[\u4e00-\u9fa5A-Za-z0-9*＊×\s]{0,30}?"
    r"(?:刑初|刑终|刑再|刑更|民初|民终|行初|行终)\s*\d+\s*号"
)
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
COURT_RE = re.compile(r"([\u4e00-\u9fa5]{2,40}?(?:人民法院|法院))")
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
SENT_SPLIT_RE = re.compile(r"[。；;]")


def win_path(path: str) -> str:
    path = os.path.abspath(path)
    if os.name == "nt" and len(path) > 240 and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + path
    return path


def extract_text(path: str) -> str:
    doc = fitz.open(win_path(path))
    try:
        return "\n".join(page.get_text("text") for page in doc)
    finally:
        doc.close()


def sentences(text: str) -> list[str]:
    out = []
    for part in SENT_SPLIT_RE.split(text):
        part = re.sub(r"\s+", " ", part).strip()
        if part:
            out.append(part)
    return out


def detect_doc_type(text: str, name: str = "") -> str:
    """Classify by title/filename first, then by dispositive language.

    Evidence lists routinely mention 《扣押决定书》 or 《行政处罚决定书》, so a
    title marker is only trusted in the first ~150 characters (or the filename).
    A judgment can quote "裁定如下" and a ruling can quote "判决如下", so the
    title still wins over dispositive language.
    """
    title = text[:150]
    for marker, doc_type in (
        ("调解协议", "mediation"),
        ("调解书", "mediation"),
        ("判决书", "judgment"),
        ("裁定书", "ruling"),
        ("决定书", "decision"),
    ):
        if marker in name or marker in title:
            return doc_type
    if "判决如下" in text:
        return "judgment"
    if "裁定如下" in text:
        return "ruling"
    if "调解" in name or "调解协议" in text:
        return "mediation"
    if "刑事" in name and ("一审" in name or "二审" in name or "判决" in name):
        return "judgment"
    return "other"


def find_case_no(text: str, name: str) -> str:
    """Prefer the docket in the filename, then the court's own docket."""
    m = CASE_NO_RE.search(name)
    if m:
        return m.group(0)
    m = OWN_CASE_RE.search(text[:1200])
    if m:
        found = CASE_NO_RE.search(m.group(0))
        if found:
            return found.group(0)
    m = CASE_NO_RE.search(text[:1200]) or CASE_NO_RE.search(text)
    return m.group(0) if m else ""


def normalize_province(value: str) -> str:
    value = (value or "").strip()
    if value in PROVINCE_SHORT:
        return value
    if value in PROVINCE_FULL_TO_SHORT:
        return PROVINCE_FULL_TO_SHORT[value]
    m = PROVINCE_RE.match(value)
    if not m:
        return ""
    return PROVINCE_FULL_TO_SHORT.get(m.group(1), m.group(1).rstrip("省市"))


def infer_province(parts: list[str], court: str, name: str) -> str:
    for part in parts[:-1]:
        if part == name:
            continue
        found = normalize_province(part)
        if found:
            return found
    return normalize_province(court) or normalize_province(name)


def detect_crimes(text: str, name: str, crime_map: dict) -> list[str]:
    """Filename hits win; text hits are only a fallback. Candidates, not codes."""
    def hits_in(source: str):
        found = []
        for canon, variants in (crime_map or {}).items():
            if not isinstance(variants, list):
                continue
            for variant in variants:
                pos = source.find(variant)
                if pos >= 0:
                    found.append((pos, canon))
                    break
        found.sort(key=lambda x: x[0])
        return [canon for _, canon in found]

    charge = re.search(r"案\s*由[：:]\s*([^\n]{0,200})", text[:2000])
    filename_hits = hits_in(name)
    if charge:
        hits = hits_in(charge.group(1))
    else:
        hits = filename_hits or hits_in(text)
    seen, out = set(), []
    for canon in hits:
        if canon not in seen:
            seen.add(canon)
            out.append(canon)
    return out


def find_signals(text: str, keywords: dict, limit_per_term: int = 3) -> dict:
    sents = sentences(text)
    signals = {}
    for category, terms in keywords.items():
        if category == "crime" or not isinstance(terms, list):
            continue
        hits = []
        for term in terms:
            found = 0
            for sent in sents:
                if term and term in sent:
                    hits.append({"term": term, "sentence": sent[:500]})
                    found += 1
                    if found >= limit_per_term:
                        break
        if hits:
            signals[category] = hits
    return signals


def read_valid_paths(audit: str | None, dedupe_plan: str | None) -> tuple[set[str] | None, set[str]]:
    keep = None
    if audit:
        with open(audit, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        keep = {r["relpath"] for r in rows if r.get("status") == "valid"}
    removed: set[str] = set()
    if dedupe_plan:
        with open(dedupe_plan, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        removed = {r["relpath"] for r in rows
                   if r.get("action") in {"move", "copy"} and r.get("relpath")}
    return keep, removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a coding worksheet from PDFs.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", default="output/coding")
    parser.add_argument("--keywords", default=None, help="JSON keyword dictionary")
    parser.add_argument("--audit", default=None, help="corpus_audit.csv (use valid rows)")
    parser.add_argument("--dedupe-plan", default=None, help="dedupe_plan.csv (skip moved rows)")
    parser.add_argument("--min-chars", type=int, default=100)
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--doc-type", choices=["judgment", "all"], default="judgment",
                        help="judgment = only 判决书/裁定书/调解书/决定书; all = keep every readable PDF")
    args = parser.parse_args()

    if fitz is None:
        print("ERROR: PyMuPDF not installed. Run: pip install pymupdf", file=sys.stderr)
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
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    keywords = {}
    if args.keywords:
        with open(args.keywords, encoding="utf-8") as fh:
            keywords = json.load(fh)
        keywords.pop("_note", None)
    keep_paths, removed_paths = read_valid_paths(args.audit, args.dedupe_plan)

    jsonl_path = os.path.join(out_dir, "coding_sheet.jsonl")
    csv_path = os.path.join(out_dir, "coding_sheet.csv")
    rows = []
    skipped = []
    total = 0
    stop = False
    with open(jsonl_path, "w", encoding="utf-8") as out_jsonl:
        for dirpath, dirnames, filenames in os.walk(root):
            if stop:
                break
            dirnames[:] = [d for d in dirnames if d != "_duplicates" and not d.startswith(".")]
            for name in filenames:
                if not name.lower().endswith(".pdf") or name.startswith("._"):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, root)
                if keep_paths is not None and rel not in keep_paths:
                    continue
                if rel in removed_paths:
                    continue
                if args.max_files and total >= args.max_files:
                    stop = True
                    break
                if os.path.getsize(path) == 0:
                    skipped.append({"relpath": rel, "file": name, "doc_type": "",
                                    "han_chars": 0, "reason": "zero-byte file"})
                    continue
                try:
                    text = extract_text(path)
                except Exception as exc:
                    print(f"WARN: cannot read {rel}: {exc}", file=sys.stderr)
                    skipped.append({"relpath": rel, "file": name, "doc_type": "unreadable",
                                    "han_chars": 0, "reason": f"unreadable: {exc}"})
                    continue
                han = len(re.findall(r"[\u4e00-\u9fa5]", text))
                if han < args.min_chars:
                    skipped.append({"relpath": rel, "file": name, "doc_type": "",
                                    "han_chars": han,
                                    "reason": f"below --min-chars ({han} < {args.min_chars})"})
                    continue
                doc_type = detect_doc_type(text, name)
                if args.doc_type == "judgment" and doc_type == "other":
                    skipped.append({"relpath": rel, "file": name, "doc_type": doc_type,
                                    "han_chars": han, "reason": "not a judgment/ruling/mediation/decision"})
                    continue
                parts = rel.split(os.sep)
                court_match = COURT_RE.search(name) or COURT_RE.search(text[:2000])
                court = court_match.group(1) if court_match else ""
                province = infer_province(parts, court, name)
                case_no = find_case_no(text, name)
                year_match = (YEAR_RE.search(case_no) or YEAR_RE.search(name)
                              or YEAR_RE.search(text[:500]))
                signals = find_signals(text, keywords) if keywords else {}
                crime_candidates = detect_crimes(text, name, keywords.get("crime", {})) if keywords else []
                rec = {
                    "file": name,
                    "relpath": rel,
                    "province": province,
                    "year": int(year_match.group(0)) if year_match else None,
                    "case_no": case_no,
                    "court": court,
                    "doc_type": doc_type,
                    "han_chars": han,
                    "crime_candidates": crime_candidates,
                    "text": text,
                    "signals": signals,
                    "codes": {},
                    "evidence": {},
                }
                out_jsonl.write(json.dumps(rec, ensure_ascii=False) + "\n")
                rows.append({
                    "file": name, "relpath": rel, "province": province,
                    "year": rec["year"], "case_no": case_no, "court": court,
                    "doc_type": doc_type, "han_chars": han,
                    "crime_candidates": ",".join(crime_candidates),
                    "signal_categories": ",".join(sorted(signals.keys())),
                    "signal_hits": sum(len(v) for v in signals.values()),
                })
                total += 1
                if total % 200 == 0:
                    print(f"  extracted {total} ...", flush=True)

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        fields = ["file", "relpath", "province", "year", "case_no", "court", "doc_type",
                  "han_chars", "crime_candidates", "signal_categories", "signal_hits"]
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    skipped_path = os.path.join(out_dir, "skipped_documents.csv")
    with open(skipped_path, "w", newline="", encoding="utf-8-sig") as fh:
        fields = ["relpath", "file", "doc_type", "han_chars", "reason"]
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(skipped)

    print(f"extracted: {len(rows)} documents -> {jsonl_path}")
    print(f"skipped: {len(skipped)} documents -> {skipped_path}")
    print(f"summary: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
