#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cohen's kappa between two independent codings of the same documents.

The coding protocol (references/02-coding-protocol.md) asks for double coding
or an independent re-read of 10-15% of the material before the codebook
freezes. This script turns that protocol into an artefact: it aligns two
coding results per document and per field, reports each variable's agreement
rate and Cohen's kappa, and lists every disagreement with the evidence lines
both coders recorded, so adjudication starts from the disagreements instead
of from the raw text.

Inputs are two CSVs with one row per document (the dataset.csv that
make_coding_sheet.py --extract writes is the intended shape, but any CSV with
a document key works). Optional --a-evidence/--b-evidence take the matching
evidence.jsonl files so disagreements carry both coders' source spans.

The script never decides who is right: disagreements are listed, not fixed.
Two codings that agree on nothing still exit 0; only structural problems
(missing files, no alignable key, duplicate keys) exit 2.

Usage:
    python compute_kappa.py --a output/coding/r1/dataset.csv \\
        --b output/coding/r2/dataset.csv \\
        [--a-evidence output/coding/r1/evidence.jsonl] \\
        [--b-evidence output/coding/r2/evidence.jsonl] \\
        --out output/kappa
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

KEY_COLUMNS = ("rel_path", "relpath", "file", "doc_id", "id", "name", "filename")
EXCLUDED_SUFFIXES = ("_src",)
EXCLUDED_COLUMNS = {"doc_type", "run_order"}
EMPTY_LABEL = "（未编码）"

SCRIPT_VERSION = "1.0.0"


def read_csv_rows(path: str, label: str) -> tuple[list[str], list[dict]]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields:
        raise ValueError(f"{label} is empty (no header row): {path}")
    return fields, rows


def pick_key(fields_a: list[str], fields_b: list[str]) -> str:
    for column in KEY_COLUMNS:
        if column in fields_a and column in fields_b:
            return column
    raise ValueError(
        "no alignable document key column; expected one of "
        f"{list(KEY_COLUMNS)} in both CSVs; A has {fields_a}, B has {fields_b}")


def _norm(value: str) -> str:
    text = (value or "").strip()
    return text if text else EMPTY_LABEL


def cohen_kappa(pairs: list[tuple[str, str]]) -> dict:
    """Agreement stats for paired codes. kappa is None when undefined."""
    n = len(pairs)
    if n == 0:
        return {"n_pairs": 0, "n_agree": 0, "n_disagree": 0,
                "agreement_rate": None, "cohen_kappa": None,
                "note": "no paired rows"}
    agree = sum(1 for a, b in pairs if a == b)
    rate = agree / n
    categories = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    row_marginal = {c: 0 for c in categories}
    col_marginal = {c: 0 for c in categories}
    for a, b in pairs:
        row_marginal[a] += 1
        col_marginal[b] += 1
    pe = sum((row_marginal[c] / n) * (col_marginal[c] / n) for c in categories)
    if pe >= 1.0:
        return {"n_pairs": n, "n_agree": agree, "n_disagree": n - agree,
                "agreement_rate": rate, "cohen_kappa": None,
                "note": "constant ratings on one side (kappa undefined); "
                        "report the agreement rate instead"}
    kappa = (rate - pe) / (1.0 - pe)
    note = ""
    if max(row_marginal.values()) == n or max(col_marginal.values()) == n:
        note = "one coder is constant"
    return {"n_pairs": n, "n_agree": agree, "n_disagree": n - agree,
            "agreement_rate": rate, "cohen_kappa": kappa, "note": note}


def load_evidence(path: str) -> dict[tuple[str, str], str]:
    """Map (doc key, field name) -> the coder's evidence line, if recorded."""
    out: dict[tuple[str, str], str] = {}
    if not path:
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            key = _norm(rec.get("rel_path") or rec.get("file") or rec.get("_row_id") or "")
            for evidence in rec.get("evidence") or []:
                name, _sep, _rest = str(evidence).partition("=")
                out.setdefault((key, name.strip()), str(evidence))
    return out


def comparable_fields(fields_a: list[str], fields_b: list[str], key: str) -> list[str]:
    shared = [f for f in fields_a if f in fields_b]
    out = []
    for field in shared:
        if field in KEY_COLUMNS or field in EXCLUDED_COLUMNS:
            continue
        if any(field.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
            continue
        out.append(field)
    return out


def one_sided_fields(fields: list[str], other: list[str]) -> list[str]:
    """Coded variables present in only one coder's CSV.

    Identifiers and provenance columns never count; the list is reported so
    a dropped variable is visible instead of silently skipped.
    """
    other_set = set(other)
    out = []
    for field in fields:
        if field in KEY_COLUMNS or field in EXCLUDED_COLUMNS:
            continue
        if any(field.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
            continue
        if field not in other_set:
            out.append(field)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Cohen's kappa between two independent codings")
    parser.add_argument("--a", required=True, help="coder A dataset CSV")
    parser.add_argument("--b", required=True, help="coder B dataset CSV")
    parser.add_argument("--a-evidence", default=None,
                        help="evidence.jsonl produced alongside A")
    parser.add_argument("--b-evidence", default=None,
                        help="evidence.jsonl produced alongside B")
    parser.add_argument("--out", default="output/kappa",
                        help="output directory (kappa_report.csv, "
                             "disagreements.csv, coding-sample.md)")
    args = parser.parse_args(argv)

    for label, path in (("A", args.a), ("B", args.b),
                        ("A evidence", args.a_evidence),
                        ("B evidence", args.b_evidence)):
        if path and not os.path.isfile(path):
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            return 2
    try:
        fields_a, rows_a = read_csv_rows(args.a, "A")
        fields_b, rows_b = read_csv_rows(args.b, "B")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        key = pick_key(fields_a, fields_b)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    map_a = {}
    for row in rows_a:
        value = _norm(row.get(key) or "")
        if value == EMPTY_LABEL:
            continue
        if value in map_a:
            print(f"ERROR: duplicate {key} in A: {value}", file=sys.stderr)
            return 2
        map_a[value] = row
    map_b = {}
    for row in rows_b:
        value = _norm(row.get(key) or "")
        if value == EMPTY_LABEL:
            continue
        if value in map_b:
            print(f"ERROR: duplicate {key} in B: {value}", file=sys.stderr)
            return 2
        map_b[value] = row

    shared_keys = [k for k in map_a if k in map_b]
    only_a = [k for k in map_a if k not in map_b]
    only_b = [k for k in map_b if k not in map_a]
    fields = comparable_fields(fields_a, fields_b, key)
    a_only_fields = one_sided_fields(fields_a, fields_b)
    b_only_fields = one_sided_fields(fields_b, fields_a)
    if not shared_keys:
        print(f"ERROR: no document appears in both CSVs "
              f"(key={key}; A-only={len(only_a)}, B-only={len(only_b)})",
              file=sys.stderr)
        return 2
    if not fields:
        print("ERROR: no comparable field columns shared by both CSVs",
              file=sys.stderr)
        return 2

    evidence_a = load_evidence(args.a_evidence or "")
    evidence_b = load_evidence(args.b_evidence or "")

    report_rows = []
    disagreement_rows = []
    for field in fields:
        pairs = []
        for doc in shared_keys:
            a = _norm(map_a[doc].get(field) or "")
            b = _norm(map_b[doc].get(field) or "")
            pairs.append((a, b))
            if a != b:
                disagreement_rows.append({
                    "doc": doc, "field": field,
                    "value_a": map_a[doc].get(field) or "",
                    "value_b": map_b[doc].get(field) or "",
                    "evidence_a": evidence_a.get((doc, field), ""),
                    "evidence_b": evidence_b.get((doc, field), ""),
                })
        stats = cohen_kappa(pairs)
        stats["variable"] = field
        report_rows.append(stats)

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    report_path = os.path.join(out_dir, "kappa_report.csv")
    with open(report_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "variable", "n_pairs", "n_agree", "n_disagree",
            "agreement_rate", "cohen_kappa", "note"])
        writer.writeheader()
        for row in report_rows:
            out = dict(row)
            out["agreement_rate"] = (
                "" if row["agreement_rate"] is None
                else f"{row['agreement_rate']:.4f}")
            out["cohen_kappa"] = (
                "" if row["cohen_kappa"] is None
                else f"{row['cohen_kappa']:.4f}")
            writer.writerow(out)

    disagreements_path = os.path.join(out_dir, "disagreements.csv")
    with open(disagreements_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "doc", "field", "value_a", "value_b", "evidence_a", "evidence_b"])
        writer.writeheader()
        writer.writerows(disagreement_rows)

    low_vars = [row["variable"] for row in report_rows
                if row["cohen_kappa"] is not None and row["cohen_kappa"] < 0.6]
    sample_path = os.path.join(out_dir, "coding-sample.md")
    with open(sample_path, "w", encoding="utf-8") as fh:
        fh.write("# 抽样复核（compute_kappa.py 生成）\n\n")
        fh.write(f"- 编码 A：{args.a}\n")
        fh.write(f"- 编码 B：{args.b}\n")
        fh.write(f"- 对齐键：{key}；两轮都有 {len(shared_keys)} 份"
                 f"（A 独有 {len(only_a)}，B 独有 {len(only_b)}）\n")
        fh.write(f"- 对齐变量：{len(fields)} 个；分歧 {len(disagreement_rows)} 条\n")
        if a_only_fields:
            fh.write(f"- 仅 A 编了、B 没编（未参与 κ）：{'、'.join(a_only_fields)}\n")
        if b_only_fields:
            fh.write(f"- 仅 B 编了、A 没编（未参与 κ）：{'、'.join(b_only_fields)}\n")
        fh.write("\n")
        fh.write("抽样复核：上述文档经两轮独立编码；每变量一致率与 Cohen's κ 见"
                 " kappa_report.csv，分歧逐条见 disagreements.csv（含双方证据行）。\n")
        if low_vars:
            fh.write("κ < 0.6、需回 codebook 修规则后重编的变量："
                     + "、".join(low_vars) + "。\n")
        else:
            fh.write("没有 κ < 0.6 的变量。\n")

    print(f"docs compared: {len(shared_keys)} (A-only {len(only_a)}, "
          f"B-only {len(only_b)})")
    print(f"variables: {len(fields)}; disagreements: {len(disagreement_rows)}")
    if a_only_fields:
        print("A-only variables (not compared): " + ", ".join(a_only_fields))
    if b_only_fields:
        print("B-only variables (not compared): " + ", ".join(b_only_fields))
    if low_vars:
        print("kappa < 0.6 (fix the codebook, then re-code): "
              + ", ".join(low_vars))
    print(f"kappa_report: {report_path}")
    print(f"disagreements: {disagreements_path}")
    print(f"coding-sample: {sample_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
