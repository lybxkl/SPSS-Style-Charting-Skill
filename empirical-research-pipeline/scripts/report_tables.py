#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Produce the full set of data reports for a dataset, traceably.

One command emits the standard report pack: per-variable report,
descriptive statistics, frequency tables, cross-tabulations, missing-value
report and patterns, duplicate report, a readable master report, and
report_index.json - the provenance anchor that binds every report file to
the exact dataset bytes (and, when given, to the cleaning log that produced
them) through sha256.

This script reports; it never judges. Role labels come from the caller
(--id / --outcome are declarations, not guesses); "numeric/categorical/text"
are mechanical facts about parse rates and cardinality against
--max-cardinality, shown per variable so the reader sees the basis. Values
are read as exact strings (keep_default_na=False): the only missing value
is the empty cell, plus whatever the cleaning step already recorded.

Skewness/kurtosis are the SPSS-style adjusted sample statistics (G1 and
G2, matching pandas .skew()/.kurt()); they are left blank when n is too
small for the adjustment (skew n>=3, kurtosis n>=4). Percentages use all
rows as the denominator. A literal cell equal to "(缺失)" is
indistinguishable from a missing marker in frequency_tables.csv.

Usage:
    python scripts/report_tables.py --dataset output/dataset/analysis.csv \\
        --out output/reports --id respondent_id --outcome satisfaction \\
        --crosstab "gender,age_group" \\
        --cleaning-log output/cleaning/cleaning_log.jsonl \\
        --missing-reasons output/coding/missing_by_source.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from analysis_utils import (read_csv_auto, validate_csv_header,
                            validate_csv_shape)

SCRIPT_VERSION = "1.0.0"

MISSING_LABEL = "(缺失)"
NO_MISSING_LABEL = "(无缺失)"
PATTERN_CAP = 50           # missing-pattern rows kept in the report


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def num(value) -> str:
    """Format a number for CSV output: 6 significant digits, blank for None."""
    if value is None:
        return ""
    return format(float(value), ".6g")


def write_csv(path: str, header: list[str], rows: list[list]) -> int:
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return len(rows)


def parse_float(text):
    """Parse a cell as float, or None when it is not a finite number.

    Mirrors clean_data.parse_number: 'NaN'/'inf' spellings, digit
    separators like '1_000', and values that overflow to infinity are
    values, not numbers. Missing (None) cells return None as well;
    callers distinguish missing from non-numeric before calling.
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s or "_" in s:
        return None
    if s.lower() in ("nan", "inf", "-inf", "+inf", "infinity", "-infinity"):
        return None
    try:
        parsed = float(s)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def describe(values: list[float]) -> dict:
    """Descriptive statistics matching SPSS conventions.

    sd is the sample sd (ddof=1); skew/kurtosis are the adjusted sample
    statistics G1/G2 (pandas .skew()/.kurt()); quantiles use linear
    interpolation. Fields are None when n is too small.
    """
    series = pd.Series(values, dtype="float64")
    n = len(series)
    out: dict = {"n": n}
    out["mean"] = series.mean() if n else None
    out["sd"] = series.std(ddof=1) if n >= 2 else None
    out["se"] = (out["sd"] / (n ** 0.5)) if n >= 2 else None
    out["min"] = series.min() if n else None
    out["p25"] = series.quantile(0.25) if n else None
    out["median"] = series.median() if n else None
    out["p75"] = series.quantile(0.75) if n else None
    out["max"] = series.max() if n else None
    out["iqr"] = (out["p75"] - out["p25"]) if n else None
    out["skew"] = series.skew() if n >= 3 else None
    out["kurtosis"] = series.kurtosis() if n >= 4 else None
    return out


# ---------------------------------------------------------------------------
# column profiling
# ---------------------------------------------------------------------------

def profile_columns(columns: list[str], rows: list[dict], id_column: str,
                     outcome_columns: list[str],
                     max_cardinality: int) -> dict[str, dict]:
    """Mechanical facts per column: counts, parse rate, cardinality."""
    profiles: dict[str, dict] = {}
    for column in columns:
        present = [row[column] for row in rows if row.get(column) is not None]
        numeric_ok = [v for v in (parse_float(value) for value in present)
                      if v is not None]
        n_missing = len(rows) - len(present)
        n_non_numeric = len(present) - len(numeric_ok)
        n_unique = len(set(present))
        role = ("id" if column == id_column else
                "outcome" if column in outcome_columns else "variable")
        if not present:
            kind = "empty"
        elif n_non_numeric == 0:
            kind = "numeric"
        elif n_unique <= max_cardinality:
            kind = "categorical"
        else:
            kind = "text"
        top_value, top_n = None, 0
        if present:
            counts: dict[str, int] = {}
            for value in present:
                counts[value] = counts.get(value, 0) + 1
            top_value, top_n = sorted(counts.items(),
                                     key=lambda kv: (-kv[1], kv[0]))[0]
        profiles[column] = {
            "role": role, "kind": kind,
            "n": len(present), "n_missing": n_missing,
            "pct_missing": (n_missing / len(rows) * 100) if rows else 0.0,
            "n_unique": n_unique, "n_non_numeric": n_non_numeric,
            "numeric": numeric_ok, "top_value": top_value, "top_n": top_n,
        }
    return profiles


def value_counts(column: str, rows: list[dict],
                 include_missing: bool = False) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(column)
        if value is None:
            if include_missing:
                counts[MISSING_LABEL] = counts.get(MISSING_LABEL, 0) + 1
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# report builders (each returns (header, rows))
# ---------------------------------------------------------------------------

def build_variable_report(columns: list[str], profiles: dict[str, dict]
                          ) -> tuple[list[str], list[list]]:
    header = ["column", "role", "kind", "n", "n_missing", "pct_missing",
              "n_unique", "n_non_numeric", "mean", "sd", "min", "median",
              "max", "top_value", "top_value_n"]
    rows = []
    for column in columns:
        p = profiles[column]
        if p["kind"] == "numeric":
            stats = describe(p["numeric"])
            mean, sd = stats["mean"], stats["sd"]
            low, mid, high = stats["min"], stats["median"], stats["max"]
        else:
            mean = sd = low = mid = high = None
        rows.append([
            column, p["role"], p["kind"], p["n"], p["n_missing"],
            num(p["pct_missing"]), p["n_unique"], p["n_non_numeric"],
            num(mean), num(sd), num(low), num(mid), num(high),
            p["top_value"] or "", p["top_n"],
        ])
    return header, rows


def build_descriptive_stats(columns: list[str],
                            profiles: dict[str, dict]
                            ) -> tuple[list[str], list[list]]:
    header = ["variable", "n", "n_missing", "mean", "sd", "se", "min",
              "p25", "median", "p75", "max", "iqr", "skew", "kurtosis"]
    rows = []
    for column in columns:
        p = profiles[column]
        if p["kind"] != "numeric" or p["role"] == "id":
            continue
        stats = describe(p["numeric"])
        rows.append([column, stats["n"], p["n_missing"]] + [
            "" if stats[key] is None else num(stats[key])
            for key in ("mean", "sd", "se", "min", "p25", "median", "p75",
                        "max", "iqr", "skew", "kurtosis")])
    return header, rows


def build_frequency_tables(columns: list[str], rows: list[dict],
                           profiles: dict[str, dict], n_rows: int,
                           max_cardinality: int, skipped: list
                           ) -> tuple[list[str], list[list]]:
    """Value tables for low-cardinality columns only (the doc promise).

    A numeric column with more unique values than --max-cardinality is a
    continuous variable: listing it value-by-value would be a spreadsheet,
    not a report, so it is skipped visibly instead.
    """
    header = ["variable", "value", "n", "pct", "cumulative_pct"]
    out = []
    for column in columns:
        p = profiles[column]
        if p["role"] == "id":
            continue
        if p["kind"] == "empty":
            skipped.append({
                "item": f"frequency:{column}",
                "reason": f"{column} has no non-missing values; "
                          "nothing to tabulate"})
            continue
        if p["kind"] == "text" or p["n_unique"] > max_cardinality:
            # text columns are above the cap by construction; numeric
            # columns can be too - either way a value-by-value list would
            # be a spreadsheet, not a report
            skipped.append({
                "item": f"frequency:{column}",
                "reason": f"{column} has {p['n_unique']} unique values "
                          f"(> max-cardinality {max_cardinality}); "
                          "see variable_report instead of a value list"})
            continue
        counts = value_counts(column, rows, include_missing=True)
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        cumulative = 0
        for value, n in ordered:
            cumulative += n
            out.append([column, value, n, num(n / n_rows * 100),
                        num(cumulative / n_rows * 100)])
    return header, out


def build_crosstab(pairs: list[tuple[str, str]], rows: list[dict],
                   profiles: dict[str, dict], n_rows: int, skipped: list
                   ) -> tuple[list[str], list[list]]:
    header = ["var_a", "var_b", "value_a", "value_b", "n", "pct_within_a"]
    out = []
    for var_a, var_b in pairs:
        for var in (var_a, var_b):
            p = profiles.get(var, {})
            if p.get("role") == "id":
                skipped.append({"item": f"{var_a}×{var_b}",
                                "reason": f"{var} is the id column"})
                break
            if p.get("kind") != "categorical":
                skipped.append({
                    "item": f"{var_a}×{var_b}",
                    "reason": f"{var} is {p.get('kind')} "
                              f"({p.get('n_unique')} unique); a crosstab "
                              "needs two categorical columns "
                              "(see --max-cardinality)"})
                break
        else:
            counts: dict[tuple[str, str], int] = {}
            marginal_a: dict[str, int] = {}
            for row in rows:
                a, b = row.get(var_a), row.get(var_b)
                a_key = MISSING_LABEL if a is None else a
                b_key = MISSING_LABEL if b is None else b
                counts[(a_key, b_key)] = counts.get((a_key, b_key), 0) + 1
                marginal_a[a_key] = marginal_a.get(a_key, 0) + 1
            for (a_key, b_key), n in sorted(counts.items()):
                out.append([var_a, var_b, a_key, b_key, n,
                            num(n / marginal_a[a_key] * 100)])
            continue
    return header, out


def build_missing_report(columns: list[str], profiles: dict[str, dict],
                          rows: list[dict]
                          ) -> tuple[list[str], list[list]]:
    header = ["variable", "n_missing", "pct_missing", "n_non_numeric"]
    out = []
    for column in columns:
        p = profiles[column]
        out.append([column, p["n_missing"], num(p["pct_missing"]),
                    p["n_non_numeric"]])
    return header, out


def build_missing_patterns(columns: list[str], rows: list[dict],
                           id_column: str, n_rows: int
                           ) -> tuple[list[str], list[list]]:
    """Which variables are missing together, most frequent patterns first."""
    header = ["pattern", "n_rows", "pct"]
    pattern_cols = [col for col in columns if col != id_column]
    counts: dict[tuple, int] = {}
    for row in rows:
        key = tuple(sorted(col for col in pattern_cols
                          if row.get(col) is None))
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    out = []
    for key, n in ordered[:PATTERN_CAP]:
        label = NO_MISSING_LABEL if not key else ";".join(key)
        out.append([label, n, num(n / n_rows * 100)])
    if len(ordered) > PATTERN_CAP:
        out.append([f"(其余 {len(ordered) - PATTERN_CAP} 种模式)",
                    sum(n for _, n in ordered[PATTERN_CAP:]), ""])
    return header, out


def build_duplicate_report(rows: list[dict], columns: list[str],
                           id_column: str | None
                           ) -> tuple[list[str], list[list]]:
    header = ["duplicate_kind", "key", "n_rows", "n_extra"]
    out = []
    if id_column:
        counts = value_counts(id_column, rows)
        n_missing_id = sum(1 for row in rows if row.get(id_column) is None)
        for value, n in sorted(counts.items()):
            if n > 1:
                out.append(["id", value, n, n - 1])
        if n_missing_id:
            # rows without an id are not "duplicates", but a report that
            # counts duplicated ids must not hide them either
            out.append(["id_missing", MISSING_LABEL, n_missing_id, ""])
    full_key = lambda row: tuple(           # noqa: E731
        None if row.get(col) is None else row[col] for col in columns)
    groups: dict[tuple, int] = {}
    for row in rows:
        key = full_key(row)
        groups[key] = groups.get(key, 0) + 1
    dup_groups = {k: n for k, n in groups.items() if n > 1}
    if dup_groups:
        out.append(["full_row", "*",
                    sum(dup_groups.values()),
                    sum(n - 1 for n in dup_groups.values())])
    return header, out


# ---------------------------------------------------------------------------
# optional inputs
# ---------------------------------------------------------------------------

def read_cleaning_log(path: str) -> dict:
    """Parse cleaning_log.jsonl; returns what the master report shows."""
    records = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    header = next((r for r in records if r.get("record") == "header"), None)
    summary = next((r for r in records if r.get("record") == "summary"), None)
    failure = next((r for r in records if r.get("record") == "failure"), None)
    return {"header": header, "summary": summary, "failure": failure,
            "steps": [r for r in records if r.get("record") == "step"]}


def read_missing_reasons(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"field", "bucket", "n"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(
                f"missing-reasons file must have columns "
                f"{sorted(required)}; found {reader.fieldnames}")
        return [dict(row) for row in reader]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def merge_name_map(path: str, entries: list, wrapper: str) -> None:
    """Merge titled display-name entries into a map, keyed by normalized file path."""
    existing = []
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig") as fh:
                data = json.load(fh)
            existing = data if isinstance(data, list) else (data.get(wrapper) or [])
        except (OSError, ValueError) as exc:
            print(f"WARNING: {path} unreadable ({exc}); left untouched", file=sys.stderr)
            return

    def norm(p: str) -> str:
        return os.path.normpath(str(p)).replace("\\", "/")

    merged = {norm(it.get("file") or it.get("image") or ""): it
              for it in existing if isinstance(it, dict)}
    for it in entries:
        if it.get("file"):
            merged[norm(it["file"])] = it
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(list(merged.values()), fh, ensure_ascii=False, indent=2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit the full data report pack for one dataset, "
                    "with sha256 provenance for every report file.")
    parser.add_argument("--dataset", required=True,
                        help="dataset CSV (e.g. output/dataset/analysis.csv)")
    parser.add_argument("--out", default="output/reports",
                        help="output directory (default output/reports)")
    parser.add_argument("--id", help="identifier column (never used as a "
                        "variable in tables)")
    parser.add_argument("--outcome", action="append", default=[],
                        help="outcome column (repeatable)")
    parser.add_argument("--crosstab", action="append", default=[],
                        metavar="A,B",
                        help="categorical pair to cross-tabulate (repeatable)")
    parser.add_argument("--max-cardinality", type=int, default=50,
                        help="columns with more unique values than this "
                             "stay out of frequency tables and crosstabs "
                             "(non-numeric ones also become kind='text'; "
                             "numeric keeps its kind and is still fully "
                             "profiled; default 50)")
    parser.add_argument("--cleaning-log",
                        help="cleaning_log.jsonl from clean_data.py")
    parser.add_argument("--missing-reasons",
                        help="missing_by_source.csv from make_coding_sheet "
                             "--extract (per-field missing buckets)")
    args = parser.parse_args(argv)

    def error(message: str) -> int:
        print(f"ERROR: {message}", file=sys.stderr)
        return 2

    if not os.path.isfile(args.dataset):
        return error(f"dataset not found: {args.dataset}")
    # pandas absorbs rows with more fields than the header by promoting
    # the extra fields to an index column (and pads short rows) - silent
    # structural rewriting a report tool must refuse
    try:
        offenders = validate_csv_shape(args.dataset)
    except ValueError as exc:
        return error(str(exc))
    if offenders:
        shown = ", ".join(str(n) if n >= 0 else "…"
                          for n in offenders)
        return error(
            f"dataset has rows whose field count differs from the header "
            f"(first lines: {shown}); fix the file - the reader would "
            "silently absorb or pad those rows")
    try:
        problems = validate_csv_header(args.dataset)
    except ValueError as exc:
        return error(str(exc))
    if problems:
        return error("dataset header problems (pandas would silently "
                     f"rename these): {'; '.join(problems[:5])}")
    try:
        frame = read_csv_auto(args.dataset, dtype=str, keep_default_na=False)
    except Exception as exc:                              # noqa: BLE001
        return error(f"dataset not readable: {exc}")
    columns = [str(col) for col in frame.columns.tolist()]
    if not columns or frame.empty:
        return error("dataset has no columns or no rows")

    for name in ([args.id] if args.id else []) + list(args.outcome):
        if name not in columns:
            return error(f"--id/--outcome column {name!r} not in dataset; "
                         f"columns are {columns}")

    if args.max_cardinality < 1:
        return error("--max-cardinality must be at least 1")

    crosstab_pairs: list[tuple[str, str]] = []
    for spec in args.crosstab:
        parts = [part.strip() for part in spec.split(",")]
        if len(parts) != 2:
            return error(f"--crosstab must be 'A,B' (two columns), "
                         f"got {spec!r}")
        if parts[0] == parts[1]:
            return error(f"--crosstab needs two different columns, "
                         f"got {spec!r}")
        for part in parts:
            if part not in columns:
                return error(f"--crosstab column {part!r} not in dataset; "
                             f"columns are {columns}")
        crosstab_pairs.append((parts[0], parts[1]))

    cleaning = None
    if args.cleaning_log:
        if not os.path.isfile(args.cleaning_log):
            return error(f"cleaning log not found: {args.cleaning_log}")
        try:
            cleaning = read_cleaning_log(args.cleaning_log)
        except (OSError, json.JSONDecodeError) as exc:
            return error(f"cleaning log not readable: {exc}")

    missing_reasons = None
    if args.missing_reasons:
        if not os.path.isfile(args.missing_reasons):
            return error(f"missing-reasons file not found: "
                         f"{args.missing_reasons}")
        try:
            missing_reasons = read_missing_reasons(args.missing_reasons)
        except (OSError, ValueError) as exc:
            return error(str(exc))

    rows = [{col: (None if val == "" else val)
             for col, val in zip(columns, vals)}
            for vals in frame.values.tolist()]
    n_rows = len(rows)

    # staleness cross-check: an analysis table built before the last
    # cleaning run would anchor to a cleaning log that no longer describes
    # it. legitimate differences (unit restructuring, in_analysis filter)
    # exist, so this is a warning, not a refusal - but it must be visible.
    warnings: list[str] = []
    if cleaning:
        if cleaning.get("failure"):
            warnings.append(f"cleaning log ends in failure: "
                            f"{cleaning['failure'].get('error')}")
        summary = cleaning.get("summary")
        if summary:
            n_clean_final = summary.get("n_final")
            if isinstance(n_clean_final, int) and n_clean_final != n_rows:
                warnings.append(
                    f"cleaning log ended with {n_clean_final} rows; this "
                    f"dataset has {n_rows} rows - confirm the difference "
                    "comes from unit restructuring or the in_analysis "
                    "filter, else the analysis table predates the cleaning")

    if os.path.exists(args.out) and not os.path.isdir(args.out):
        return error(f"--out exists and is not a directory: {args.out}")
    try:
        os.makedirs(args.out, exist_ok=True)
    except OSError as exc:
        return error(f"cannot create output directory {args.out} ({exc})")
    profiles = profile_columns(columns, rows, args.id or "",
                               list(args.outcome), args.max_cardinality)
    skipped: list[dict] = []
    written: list[dict] = []

    def emit(filename: str, header: list[str], body: list[list]) -> None:
        path = os.path.join(args.out, filename)
        n = write_csv(path, header, body)
        written.append({"file": filename, "n_rows": n,
                        "sha256": sha256_file(path)})

    emit("variable_report.csv", *build_variable_report(columns, profiles))
    emit("descriptive_stats.csv",
         *build_descriptive_stats(columns, profiles))
    emit("frequency_tables.csv",
         *build_frequency_tables(columns, rows, profiles, n_rows,
                                 args.max_cardinality, skipped))
    emit("crosstabs.csv",
         *build_crosstab(crosstab_pairs, rows, profiles, n_rows, skipped))
    emit("missing_report.csv",
         *build_missing_report(columns, profiles, rows))
    emit("missing_patterns.csv",
         *build_missing_patterns(columns, rows, args.id or "", n_rows))
    emit("duplicate_report.csv",
         *build_duplicate_report(rows, columns, args.id))

    if missing_reasons is not None:
        path = os.path.join(args.out, "missing_reasons_by_field.csv")
        n = write_csv(path, ["field", "bucket", "n", "share_of_na"],
                      [[row.get("field", ""), row.get("bucket", ""),
                        row.get("n", ""), row.get("share_of_na", "")]
                       for row in missing_reasons])
        written.append({"file": "missing_reasons_by_field.csv", "n_rows": n,
                        "sha256": sha256_file(path)})

    # readable master report, then the index that anchors everything
    md_path = os.path.join(args.out, "data_report.md")
    write_master_report(md_path, args, columns, profiles, rows, n_rows,
                         cleaning, skipped, written, warnings)
    written.append({"file": "data_report.md", "n_rows": "",
                    "sha256": sha256_file(md_path)})

    index = {
        "tool": "report_tables.py",
        "version": SCRIPT_VERSION,
        "dataset": {"path": args.dataset,
                    "sha256": sha256_file(args.dataset),
                    "n_rows": n_rows, "n_columns": len(columns),
                    "columns": columns},
        "cleaning_log": ({"path": args.cleaning_log,
                          "sha256": sha256_file(args.cleaning_log)}
                         if args.cleaning_log else None),
        "missing_reasons": ({"path": args.missing_reasons,
                             "sha256": sha256_file(args.missing_reasons),
                             "n_rows": len(missing_reasons)}
                            if args.missing_reasons else None),
        "args": {"id": args.id, "outcome": args.outcome,
                 "crosstab": args.crosstab,
                 "max_cardinality": args.max_cardinality},
        "reports": written,
        "skipped": skipped,
        "warnings": warnings,
        "generated_at": now_iso(),
    }
    index_path = os.path.join(args.out, "report_index.json")
    with open(index_path, "w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    # 报表也是交付表：自动登记中文显示名，避免查看器回退英文文件名
    report_titles = {
        "variable_report.csv": "变量报告",
        "descriptive_stats.csv": "描述统计",
        "frequency_tables.csv": "频数表",
        "crosstabs.csv": "交叉表",
        "missing_report.csv": "缺失报告",
        "missing_patterns.csv": "缺失模式",
        "duplicate_report.csv": "重复报告",
        "missing_reasons_by_field.csv": "缺失原因（按字段）",
    }
    merge_name_map(os.path.join("output", "table_map.json"),
                   [{"tag": "报表", "title": report_titles[w["file"]],
                     "file": os.path.join(args.out, w["file"])}
                    for w in written if w["file"] in report_titles], "tables")
    merge_name_map(os.path.join("output", "doc_map.json"),
                   [{"tag": "", "title": "数据报告", "file": md_path}], "docs")

    print(f"reports: {len(written)} report files + report_index.json "
          f"-> {args.out}")
    print(f"dataset: {args.dataset} (sha256 "
          f"{index['dataset']['sha256'][:12]}…, {n_rows} rows)")
    if skipped:
        print(f"skipped: {len(skipped)} item(s); see report_index.json")
    print(f"index: {index_path}")
    return 0


def md_cell(text) -> str:
    """Make a value safe for a Markdown table cell."""
    if text is None:
        return ""
    return (str(text).replace("|", "\\|")
            .replace("\r\n", " ").replace("\n", " ").replace("\r", " "))


def write_master_report(path: str, args, columns: list[str],
                        profiles: dict[str, dict], rows: list[dict],
                        n_rows: int, cleaning, skipped: list,
                        written: list[dict], warnings: list) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# 数据报表\n\n")
        handle.write(f"- 数据集：{args.dataset}（{n_rows} 行 × "
                     f"{len(columns)} 列）\n")
        if cleaning and cleaning.get("header"):
            header = cleaning["header"]
            summary = cleaning.get("summary") or {}
            chain = (f"{summary.get('n_start', '?')} → "
                     f"{summary.get('n_final', '?')} 行")
            handle.write(f"- 清洗链：{chain}（{len(cleaning.get('steps', []))}"
                         f" 步；台账 {args.cleaning_log}）\n")
            if cleaning.get("failure"):
                handle.write(f"- ⚠ 清洗台账以失败中止："
                             f"{cleaning['failure'].get('error')}\n")
        elif cleaning:
            # a log exists but has no header: the run died while reading
            # the dataset; the warnings section carries the error
            handle.write("- 清洗链：台账存在但没有 header 记录（清洗在"
                         "读取数据集时失败）；见下方警告\n")
        else:
            handle.write("- 清洗链：（未提供 cleaning_log；本报表直接"
                         "针对所给数据集）\n")
        handle.write(f"- id 列：{args.id or '（未声明）'}；结果列："
                     f"{', '.join(args.outcome) or '（未声明）'}\n\n")

        handle.write("## 每变量摘要\n\n")
        handle.write("| 列 | 角色 | 类型 | n | 缺失% | 唯一值 | 众数 |\n")
        handle.write("|----|------|------|---|-------|--------|------|\n")
        for column in columns:
            p = profiles[column]
            handle.write(f"| {md_cell(column)} | {p['role']} "
                         f"| {p['kind']} "
                         f"| {p['n']} | {p['pct_missing']:.1f}% "
                         f"| {p['n_unique']} "
                         f"| {md_cell(p['top_value'])} ({p['top_n']}) |\n")

        worst = sorted(columns, key=lambda c: -profiles[c]["n_missing"])[:5]
        worst = [c for c in worst if profiles[c]["n_missing"]]
        if worst:
            handle.write("\n## 缺失最多的变量\n\n")
            for column in worst:
                p = profiles[column]
                handle.write(f"- {md_cell(column)}：{p['n_missing']} 缺失"
                             f"（{p['pct_missing']:.1f}%）\n")

        dupes = value_counts(args.id, rows) if args.id else {}
        n_id_dupes = sum(1 for n in dupes.values() if n > 1)
        if args.id:
            dup_line = f"- id 重复组：{n_id_dupes}\n"
        else:
            dup_line = "- id 重复组：（未声明 --id，不查）\n"
        handle.write("\n## 重复\n\n" + dup_line)

        if skipped:
            handle.write("\n## 未生成的表\n\n")
            for item in skipped:
                handle.write(f"- {item['item']}：{item['reason']}\n")

        if warnings:
            handle.write("\n## 警告\n\n")
            for warning in warnings:
                handle.write(f"- ⚠ {warning}\n")

        handle.write("\n## 报表清单与溯源\n\n")
        handle.write("| 文件 | 行数 |\n|------|------|\n")
        for item in written:
            handle.write(f"| {item['file']} | {item['n_rows']} |\n")
        handle.write(
            "\n每份报表的 sha256 记录在 report_index.json；报表数字的"
            "对象由 dataset 的 sha256（清洗时再上溯 cleaning_log.jsonl →"
            " 原始数据集 sha256）唯一锚定。复核时用哈希对照，不改数。\n")
        handle.write("\n口径说明：pct 分母为全部行数（一律 0–100）；"
                     "skew/kurtosis 为 SPSS 式调整统计量"
                     "（G1/G2，n 不足留空）；"
                     "频率表中的缺失记为「(缺失)」。\n")


if __name__ == "__main__":
    sys.exit(main())
