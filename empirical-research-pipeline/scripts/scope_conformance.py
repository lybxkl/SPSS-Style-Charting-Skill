#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic scope-conformance check for any analysis dataset.

A research scope declares, per categorical column, which values are in scope
(the inclusion allowlist).  This script compares the *actual* category
distribution of an analysis table against that declaration and flags every
named category that leaked in from outside the declared scope.  It is
domain-agnostic: the same check works for legal charges, civil causes, survey
strata, product lines, site ids -- any categorical field.  It never embeds a
discipline's vocabulary; the allowlist lives in the project's scope.json.

It also reports small-denominator cells (optional ``--cell-cols A,B``) so a
rate table / heat map built on tiny groups is surfaced instead of silently
showing unstable 0%/100% cells.

Scope file (JSON)::

    {
      "columns": {
        "<categorical_column>": {"include": ["value1", "value2"], "label": "..."}
      },
      "min_cell_n": 20
    }

Exit codes: 0 = conformant; 2 = a named out-of-scope category is present, a
declared column is missing from the data, or inputs are unreadable/empty.
Missing values are a warning (declare how to handle them), not an error.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from collections import Counter, defaultdict

NA_LABEL = "(NA)"


def read_rows(path: str) -> list[dict]:
    last = None
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with io.open(path, encoding=enc, newline="") as fh:
                return list(csv.DictReader(fh))
        except UnicodeDecodeError as exc:
            last = exc
    raise last  # type: ignore[misc]


def load_scope(path: str) -> dict:
    with io.open(path, encoding="utf-8-sig") as fh:
        spec = json.load(fh)
    cols = spec.get("columns")
    if not isinstance(cols, dict) or not cols:
        raise ValueError("scope.json must declare a non-empty 'columns' object")
    for col, rule in cols.items():
        if not isinstance(rule, dict) or not isinstance(rule.get("include"), list):
            raise ValueError(f"scope column {col!r} needs an 'include' list")
    return spec


def check(data: str, scope: str, cell_cols: list[str] | None,
          min_cell_n: int | None) -> dict:
    rows = read_rows(data)
    spec = load_scope(scope)
    if min_cell_n is None:
        min_cell_n = int(spec.get("min_cell_n", 0) or 0)
    result = {"data": data, "scope": scope, "rows": len(rows),
              "errors": [], "warnings": [], "columns": {}, "report": []}
    if not rows:
        result["errors"].append("analysis table has no data rows")
        return result
    header = set(rows[0].keys())
    for col, rule in spec["columns"].items():
        if col not in header:
            result["errors"].append(f"declared scope column {col!r} not in data; columns={sorted(header)[:12]}")
            continue
        include = {str(v).strip() for v in rule["include"]}
        counts = Counter((r.get(col) or "").strip() for r in rows)
        col_report = {"include": sorted(include), "categories": [],
                      "out_of_scope": [], "na": 0}
        for value, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            shown = value if value else NA_LABEL
            if not value:
                col_report["na"] += n
                in_scope = NA_LABEL in include
                severity = "ok" if in_scope else "warning"
                note = "missing value; declare how to handle it in scope"
                if not in_scope:
                    result["warnings"].append(f"{col}: {n} row(s) with missing {col}")
            elif value in include:
                in_scope, severity, note = True, "ok", ""
            else:
                in_scope, severity, note = False, "error", "named category outside declared scope"
                col_report["out_of_scope"].append({"value": value, "n": n})
                result["errors"].append(f"{col}: out-of-scope category {value!r} (n={n})")
            col_report["categories"].append({"value": shown, "n": n, "in_scope": in_scope})
            result["report"].append({"column": col, "value": shown, "n": n,
                                     "in_scope": in_scope, "severity": severity, "note": note})
        result["columns"][col] = col_report
    if cell_cols and min_cell_n > 0:
        missing = [c for c in cell_cols if c not in header]
        if missing:
            result["errors"].append(f"--cell-cols not in data: {missing}")
        else:
            cells = defaultdict(int)
            for r in rows:
                key = tuple((r.get(c) or "").strip() or NA_LABEL for c in cell_cols)
                cells[key] += 1
            small = [{"cell": dict(zip(cell_cols, k)), "n": n}
                     for k, n in sorted(cells.items(), key=lambda kv: kv[1]) if n < min_cell_n]
            result["small_cells"] = small
            result["min_cell_n"] = min_cell_n
            if small:
                result["warnings"].append(
                    f"{len(small)} cell(s) of {'×'.join(cell_cols)} below min_cell_n={min_cell_n}; "
                    f"rates on these cells are unstable (e.g. {small[0]})")
    result["error_count"] = len(result["errors"])
    result["warning_count"] = len(result["warnings"])
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--data", required=True, help="analysis CSV (one row per unit)")
    ap.add_argument("--scope", required=True, help="scope.json with per-column include allowlists")
    ap.add_argument("--out", default=None, help="write scope_conformance.csv here")
    ap.add_argument("--cell-cols", default=None,
                    help="comma-separated columns for a small-cell crosstab check, e.g. 'charge,year'")
    ap.add_argument("--min-cell-n", type=int, default=None,
                    help="override scope.json min_cell_n for the small-cell warning")
    ap.add_argument("--exit-zero", action="store_true", help="always exit 0 (do not use in CI)")
    args = ap.parse_args(argv)
    cell_cols = [c.strip() for c in args.cell_cols.split(",")] if args.cell_cols else None
    try:
        result = check(args.data, args.scope, cell_cols, args.min_cell_n)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.data)), "scope_conformance.csv")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with io.open(out, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["column", "value", "n", "in_scope", "severity", "note"])
        writer.writeheader()
        writer.writerows(result["report"])
    result["out"] = out
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["error_count"] and not args.exit_zero:
        print(f"SCOPE FAILED: {result['error_count']} error(s), {result['warning_count']} warning(s)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())