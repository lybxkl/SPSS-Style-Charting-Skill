#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate SPSS GET DATA syntax from a CSV header and a small sample.

Why: hand-writing variable widths is a common source of truncated Chinese
strings and wrong numeric formats. This script infers a safe width from the
actual data, sanitizes variable names (spaces, punctuation, reserved words,
duplicates, over-long names), writes a runnable .sps file, and adds 0/1 RECODE
blocks for yes/no text columns so Logistic can use numeric outcomes directly.

Usage:
    python csv_to_spss_syntax.py --csv data/analysis.csv \\
        --out-sps syntax/import.sps --sav-out data/analysis.sav
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys


NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
INVALID_NAME_RE = re.compile(r"[^0-9A-Za-z_\u4e00-\u9fff@#$]")
RESERVED = {"ALL", "AND", "BY", "EQ", "GE", "GT", "LE", "LT", "NE",
            "NOT", "OR", "TO", "WITH", "THRU"}
BINARY_TEXT = {
    "是": 1, "否": 0, "有": 1, "无": 0, "发生": 1, "未发生": 0,
    "支持": 1, "不支持": 0, "明确支持": 1, "未明确支持": 0,
    "阳性": 1, "阴性": 0, "yes": 1, "no": 0, "true": 1, "false": 0,
}


def truncate_bytes(value: str, limit: int) -> str:
    while len(value.encode("utf-8")) > limit and value:
        value = value[:-1]
    return value


def valid_existing_name(value: str) -> bool:
    value = (value or "").strip()
    return bool(re.fullmatch(r"[A-Za-z_\u4e00-\u9fff@#$][0-9A-Za-z_\u4e00-\u9fff@#$]{0,63}", value)
                and len(value.encode("utf-8")) <= 64
                and value.upper() not in RESERVED)


def sanitize_name(raw: str, index: int, used: set[str]) -> str:
    name = (raw or "").strip()
    name = INVALID_NAME_RE.sub("_", name)
    if not name:
        name = f"v{index + 1}"
    if not re.match(r"[A-Za-z_\u4e00-\u9fff@#$]", name):
        name = "v_" + name
    if name.upper() in RESERVED:
        name += "_"
    name = truncate_bytes(name, 64)
    base = name
    suffix = 1
    while name.upper() in used:
        suffix += 1
        tail = f"_{suffix}"
        name = truncate_bytes(base, 64 - len(tail)) + tail
    used.add(name.upper())
    return name


def quote_label(text: str) -> str:
    text = (text or "").replace("\r", " ").replace("\n", " ").strip()
    text = truncate_bytes(text, 255)
    return "'" + text.replace("'", "''") + "'"


def infer(path: str, sample_rows: int = 500, encoding: str = "utf-8-sig",
          delimiter: str = ","):
    """Infer SPSS formats from the whole file, not just the first N rows.

    Reading a sample would let long values in later rows be silently truncated
    by an A format sized on the sample, or let a text value in row 900 turn a
    column declared F into missing data. Widths are byte lengths because SPSS
    string widths are bytes, not characters.
    """
    if encoding.lower() == "auto":
        last_error = None
        for candidate in ("utf-8-sig", "gb18030", "big5"):
            try:
                return infer(path, sample_rows, candidate, delimiter)
            except UnicodeDecodeError as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
    with open(path, encoding=encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("CSV is empty (no header row)")
        samples = [[] for _ in header]
        numeric = [True] * len(header)
        saw_numeric = [False] * len(header)
        max_bytes = [0] * len(header)
        max_decimals = [0] * len(header)
        max_digits = [0] * len(header)
        levels: list[list[str]] = [[] for _ in header]
        for row in reader:
            for j, value in enumerate(row[:len(header)]):
                if value == "":
                    continue
                if len(samples[j]) < sample_rows:
                    samples[j].append(value)
                max_bytes[j] = max(max_bytes[j], len(value.encode("utf-8")))
                if not NUM_RE.match(value):
                    numeric[j] = False
                    stripped = value.strip()
                    if stripped and stripped not in levels[j] and len(levels[j]) < 3:
                        levels[j].append(stripped)
                else:
                    saw_numeric[j] = True
                    decimals = len(value.split(".")[1]) if "." in value else 0
                    digits = len(re.sub(r"[^0-9]", "", value.split("e")[0].split("E")[0]))
                    max_decimals[j] = max(max_decimals[j], decimals)
                    max_digits[j] = max(max_digits[j], digits)

    used: set[str] = set()
    names: list[str | None] = [None] * len(header)
    # Preserve headers that are already valid SPSS names, so a valid `a_b`
    # is not renamed just because `a-b` appears earlier and sanitizes to `a_b`.
    for i, raw in enumerate(header):
        candidate = (raw or "").strip()
        if valid_existing_name(candidate) and candidate.upper() not in used:
            names[i] = candidate
            used.add(candidate.upper())
    for i, raw in enumerate(header):
        if names[i] is None:
            names[i] = sanitize_name(raw, i, used)

    specs = []
    labels = []
    recodes = []
    for i, (raw, name) in enumerate(zip(header, names)):
        values = samples[i]
        if values and numeric[i]:
            decimals = max_decimals[i]
            digits = max_digits[i]
            width = max(8, min(40, digits + (2 if decimals else 0) + 1))
            fmt = f"F{width}.{min(decimals, 4)}"
        else:
            width = max(20, max_bytes[i] + 20)
            fmt = f"A{min(width, 32767)}"
            mapping = {v: BINARY_TEXT[v.lower()] for v in levels[i]
                       if v.lower() in BINARY_TEXT}
            if (not saw_numeric[i] and len(levels[i]) == 2
                    and len(mapping) == 2 and set(mapping.values()) == {0, 1}):
                new_name = sanitize_name(name + "_num", len(names) + len(recodes), used)
                recodes.append({"name": name, "new": new_name, "map": mapping,
                                "label": raw.strip()})
        specs.append((name, fmt))
        labels.append((name, raw.strip()))
    return header, specs, labels, recodes, encoding


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SPSS import syntax from CSV.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out-sps", required=True)
    parser.add_argument("--sav-out", default=None, help="optional SAVE OUTFILE path")
    parser.add_argument("--encoding", default="auto",
                        help="SPSS encoding in GET DATA: auto (UTF8/GBK/BIG5) or a code page name")
    parser.add_argument("--csv-encoding", default="auto",
                        help="CSV encoding: auto (utf-8-sig/gb18030/big5) or a codec name")
    parser.add_argument("--delimiter", default=",")
    parser.add_argument("--sample-rows", type=int, default=500)
    parser.add_argument("--no-recode", action="store_true",
                        help="do not add 0/1 RECODE blocks for yes/no text columns")
    args = parser.parse_args()

    csv_path = os.path.abspath(args.csv)
    if not os.path.isfile(csv_path):
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        return 2
    delimiter = args.delimiter.replace("\\t", "\t")
    try:
        header, specs, labels, recodes, used_encoding = infer(
            csv_path, args.sample_rows, args.csv_encoding, delimiter)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not specs:
        print("ERROR: no variables found", file=sys.stderr)
        return 2
    spss_encoding = args.encoding
    if spss_encoding.lower() == "auto":
        spss_encoding = {"utf-8-sig": "UTF8", "gb18030": "GBK",
                         "big5": "BIG5"}.get(used_encoding, "UTF8")

    var_lines = "\n    ".join(f"{name} {fmt}" for name, fmt in specs)
    syntax = f"""GET DATA /TYPE=TXT
  /FILE='{csv_path.replace(chr(92), '/')}'
  /ENCODING='{spss_encoding}'
  /DELIMITERS="{delimiter}"
  /QUALIFIER='"'
  /ARRANGEMENT=DELIMITED
  /FIRSTCASE=2
  /VARIABLES=
    {var_lines}.
EXECUTE.
"""
    label_lines = [f"  {name} {quote_label(raw)}" for name, raw in labels if raw]
    if label_lines:
        syntax += "\nVARIABLE LABELS\n" + "\n".join(label_lines) + ".\nEXECUTE.\n"
    if recodes and not args.no_recode:
        blocks = []
        for r in recodes:
            pairs = " ".join(f"({quote_label(k)}={v})" for k, v in r["map"].items())
            blocks.append(f"RECODE {r['name']} {pairs} INTO {r['new']}.")
            blocks.append(f"VARIABLE LABELS {r['new']} {quote_label(r['label'] + '（0/1）')}.")
            values = " ".join(f"{v} {quote_label(k)}" for k, v in r["map"].items())
            blocks.append(f"VALUE LABELS {r['new']} {values}.")
        syntax += "\n* 将可识别的“是/否、有/无”文本列转成 0/1，供 Logistic 使用。\n" + \
                  "\n".join(blocks) + "\nEXECUTE.\n"
    if args.sav_out:
        sav = os.path.abspath(args.sav_out).replace("\\", "/")
        syntax += f"\nSAVE OUTFILE='{sav}'.\n"

    os.makedirs(os.path.dirname(os.path.abspath(args.out_sps)), exist_ok=True)
    with open(args.out_sps, "w", encoding="utf-8") as fh:
        fh.write(syntax)
    renamed = sum(1 for (name, _), raw in zip(specs, header) if name != raw.strip())
    print(f"wrote {args.out_sps} ({len(specs)} variables, {renamed} names sanitized)")
    for (name, fmt), raw in list(zip(specs, header))[:10]:
        note = f"  <- {raw.strip()}" if name != raw.strip() else ""
        print(f"  {name}: {fmt}{note}")
    if len(specs) > 10:
        print(f"  ... {len(specs) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
