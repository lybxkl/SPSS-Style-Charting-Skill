#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate SPSS GET DATA syntax from a CSV header and a full pass over the data.

Why: hand-writing variable widths is a common source of truncated Chinese
strings and wrong numeric formats. This script infers a safe width from the
actual data, sanitizes variable names (spaces, punctuation, reserved words,
duplicates, over-long names), writes a runnable .sps file, and adds 0/1 RECODE
blocks for yes/no text columns so Logistic can use numeric outcomes directly.

Contract points implemented here:
  * numeric columns stay numeric even when the file uses thousands separators
    ("1,234") or NA sentinels ("NA", "N/A", "null", "None", "-", "\u2014");
    a column only falls back to a string when a value really is not a number,
    and every such fallback is reported on stderr;
  * the .sps file is written with the same encoding that GET DATA declares
    (UTF8 for utf-8, GBK for gb18030/gbk, BIG5 for big5), never UTF-8 bytes
    with a GBK declaration;
  * numeric variables get MISSING VALUES (-99, -98, -97), or a non-conflicting
    sentinel triple when the data already uses those values;
  * every variable gets VARIABLE LEVEL (NOMINAL/ORDINAL/SCALE) and categorical
    variables get placeholder VALUE LABELS (replace them with the codebook);
  * the delimiter is sniffed from the header when --delimiter is omitted, and
    ragged rows are counted instead of silently dropping values.

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
from decimal import Decimal, InvalidOperation

# Stamped into the run output so an artefact names the code that made it.
SCRIPT_VERSION = "2.0.0"

NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
# S10: CJK ideographs cover the BMP blocks plus the Supplementary Ideographic
# Plane, so a name such as "\U00020BB7" is kept instead of flattened to "_".
CJK_RANGES = "\u3400-\u4dbf\u4e00-\u9fff" + "\U00020000-\U0002a6df"
INVALID_NAME_RE = re.compile(rf"[^0-9A-Za-z_{CJK_RANGES}@#$]")
NAME_START_RE = re.compile(rf"[A-Za-z_{CJK_RANGES}@#$]")
VALID_NAME_RE = re.compile(rf"[A-Za-z_{CJK_RANGES}@#$][0-9A-Za-z_{CJK_RANGES}@#$]{{0,63}}")
RESERVED = {"ALL", "AND", "BY", "EQ", "GE", "GT", "LE", "LT", "NE",
            "NOT", "OR", "TO", "WITH", "THRU"}
BINARY_TEXT = {
    "是": 1, "否": 0, "有": 1, "无": 0, "发生": 1, "未发生": 0,
    "已发生": 1, "支持": 1, "不支持": 0, "明确支持": 1, "未明确支持": 0,
    "阳性": 1, "阴性": 0, "同意": 1, "不同意": 0,
    "yes": 1, "no": 0, "true": 1, "false": 0, "y": 1, "n": 0,
}
# Tokens SPSS/pandas users write for "no value"; none of them may turn a
# numeric column into a string column.
NA_TOKENS = {"", "na", "n/a", "n.a.", "null", "none", "nan", "-", "\u2014", "\uff0d"}
MAX_LEVELS = 60          # distinct values tracked per column (enough for labels)
VALUE_LABEL_BYTES = 118  # SPSS caps value labels at 120 bytes
SPSS_ENCODINGS = {
    "utf-8": ("utf-8-sig", "UTF8"),
    "utf8": ("utf-8-sig", "UTF8"),
    "utf-8-sig": ("utf-8-sig", "UTF8"),
    "utf8-sig": ("utf-8-sig", "UTF8"),
    "gb18030": ("gb18030", "GBK"),
    "gbk": ("gbk", "GBK"),
    "gb2312": ("gbk", "GBK"),
    "big5": ("big5", "BIG5"),
    "big5hkscs": ("big5hkscs", "BIG5"),
}


def truncate_bytes(value: str, limit: int) -> str:
    while len(value.encode("utf-8")) > limit and value:
        value = value[:-1]
    return value


def valid_existing_name(value: str) -> bool:
    value = (value or "").strip()
    return bool(VALID_NAME_RE.fullmatch(value)
                and len(value.encode("utf-8")) <= 64
                and value.upper() not in RESERVED)


def sanitize_name(raw: str, index: int, used: set[str]) -> str:
    name = (raw or "").strip()
    name = INVALID_NAME_RE.sub("_", name)
    if not name:
        name = f"v{index + 1}"
    if not NAME_START_RE.match(name):
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


def quote_label(text: str, limit: int = 255) -> str:
    text = (text or "").replace("\r", " ").replace("\n", " ").strip()
    text = truncate_bytes(text, limit)
    return "'" + text.replace("'", "''") + "'"


def parse_number(value: str):
    """Classify one CSV cell: ("missing"|"num"|"text", normalized value).

    Thousands separators are stripped before the numeric check so "1,234"
    stays numeric; the NA tokens listed in the contract count as missing and
    therefore never demote the column to a string column.
    """
    text = (value or "").strip()
    if text.lower() in NA_TOKENS:
        return "missing", None
    candidate = text.replace(",", "").replace("\uff0c", "")
    if NUM_RE.match(candidate):
        return "num", candidate
    return "text", text


def number_shape(normalized: str):
    """Return (integer_digits, decimals) of a numeric literal.

    Uses Decimal so exponent notation is measured by its real magnitude
    (1e12 needs 13 integer digits, not the 1 digit of its mantissa).
    """
    try:
        dec = Decimal(normalized)
    except InvalidOperation:
        return 1, 0
    _sign, digits, exponent = dec.as_tuple()
    count = len(digits)
    if exponent >= 0:
        return count + exponent, 0
    decimals = -exponent
    return max(1, count - decimals), decimals


def han_score(text: str) -> float:
    """Share of CJK characters among non-space characters (encoding probe)."""
    if not text:
        return 0.0
    total = 0
    han = 0
    for char in text:
        if char.isspace():
            continue
        total += 1
        if "\u4e00" <= char <= "\u9fff" or "\u3400" <= char <= "\u4dbf":
            han += 1
    return (han / total) if total else 0.0


def resolve_csv_encoding(path: str, name: str) -> str:
    """Pick the CSV codec, preferring UTF-8 and then the most Chinese text.

    gb18030 accepts almost any byte sequence, so a plain "first codec that
    decodes" loop would never reach big5; scoring the decoded text by its
    share of CJK characters makes the fallback reachable.
    """
    if name and name.lower() != "auto":
        return name
    with open(path, "rb") as fh:
        raw = fh.read(1 << 20)
    best = None
    best_score = -1.0
    for candidate in ("utf-8-sig", "gb18030", "big5"):
        try:
            text = raw.decode(candidate)
        except UnicodeDecodeError:
            continue
        if candidate == "utf-8-sig":
            return candidate
        score = han_score(text)
        if score > best_score:
            best, best_score = candidate, score
    return best or "utf-8-sig"


def sniff_delimiter(path: str, encoding: str) -> str:
    """Pick the delimiter with the most occurrences in the header line."""
    with open(path, encoding=encoding, newline="") as fh:
        first = fh.readline()
    counts = {sep: first.count(sep) for sep in (",", ";", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def resolve_spss_encoding(name: str, csv_encoding: str):
    """Map --encoding to (codec used to write the .sps, declared /ENCODING)."""
    key = (name or "auto").strip().lower()
    if key == "auto":
        key = {"utf-8-sig": "utf-8", "utf-8": "utf-8",
               "gb18030": "gb18030", "gbk": "gbk", "big5": "big5"}.get(
                   (csv_encoding or "").lower(), "utf-8")
    if key in SPSS_ENCODINGS:
        return SPSS_ENCODINGS[key]
    # Unknown code page: still write and declare the same thing rather than
    # claiming GBK while writing UTF-8 bytes.
    return key, key.upper()


def infer(path: str, sample_rows: int = 500, encoding: str = "utf-8-sig",
          delimiter: str = ",", report: dict | None = None):
    """Infer SPSS formats from the whole file, not just the first N rows.

    Reading a sample would let long values in later rows be silently truncated
    by an A format sized on the sample, or let a text value in row 900 turn a
    column declared F into missing data. Widths are byte lengths because SPSS
    string widths are bytes, not characters. `report` is filled in place with
    the per-column diagnostics used by main() and by the tests.
    """
    rep = report if report is not None else {}
    rep.setdefault("notes", [])
    rep.setdefault("columns", [])
    rep.setdefault("ragged_rows", 0)
    rep.setdefault("rows", 0)
    if (encoding or "").lower() == "auto":
        encoding = resolve_csv_encoding(path, "auto")
    rep["encoding"] = encoding
    rep["delimiter"] = delimiter
    with open(path, encoding=encoding, newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("CSV is empty (no header row)")
        if not any((cell or "").strip() for cell in header):
            raise ValueError("CSV header has no column names")
        count = len(header)
        samples = [[] for _ in range(count)]
        numeric = [True] * count
        saw_numeric = [False] * count
        max_bytes = [0] * count
        max_int = [0] * count
        max_dec = [0] * count
        all_int = [True] * count
        na_cells = [0] * count
        first_text = [""] * count
        text_cells = [0] * count
        levels = [[] for _ in range(count)]
        level_seen = [set() for _ in range(count)]
        level_overflow = [False] * count
        sentinel_hits: set[int] = set()
        ragged = 0
        rows = 0
        keep = max(0, int(sample_rows or 0))
        for row in reader:
            rows += 1
            if len(row) != count:
                ragged += 1
            for j, value in enumerate(row[:count]):
                kind, normalized = parse_number(value)
                if kind == "missing":
                    if (value or "").strip():
                        na_cells[j] += 1
                    continue
                if len(samples[j]) < keep:
                    samples[j].append(value)
                max_bytes[j] = max(max_bytes[j], len(value.encode("utf-8")))
                if kind == "text":
                    text_cells[j] += 1
                    if numeric[j]:
                        numeric[j] = False
                        first_text[j] = (value or "").strip()[:60]
                    all_int[j] = False
                    level_value = (value or "").strip()
                else:
                    saw_numeric[j] = True
                    dec = Decimal(normalized)
                    if dec != dec.to_integral_value():
                        all_int[j] = False
                    int_digits, decimals = number_shape(normalized)
                    max_int[j] = max(max_int[j], int_digits)
                    max_dec[j] = max(max_dec[j], decimals)
                    if dec in (-99, -98, -97):
                        sentinel_hits.add(int(dec))
                    level_value = normalized
                if level_value and level_value not in level_seen[j]:
                    if len(level_seen[j]) < MAX_LEVELS:
                        level_seen[j].add(level_value)
                        levels[j].append(level_value)
                    else:
                        level_overflow[j] = True

    used: set[str] = set()
    names: list[str | None] = [None] * count
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
        is_numeric = bool(saw_numeric[i] and numeric[i])
        if is_numeric:
            decimals = min(max_dec[i], 4)
            width = max(8, min(40, max_int[i] + (decimals + 1 if decimals else 0) + 1))
            fmt = f"F{width}.{decimals}"
        else:
            width = max(20, max_bytes[i] + 20)
            fmt = f"A{min(width, 32767)}"
        mapping = {}
        if not is_numeric and not saw_numeric[i] and len(levels[i]) == 2:
            mapping = {v: BINARY_TEXT[v.lower()] for v in levels[i]
                       if v.lower() in BINARY_TEXT}
        if (mapping and len(mapping) == 2 and set(mapping.values()) == {0, 1}):
            new_name = sanitize_name(name + "_num", len(names) + len(recodes), used)
            recodes.append({"name": name, "new": new_name, "map": mapping,
                            "label": raw.strip()})
        specs.append((name, fmt))
        labels.append((name, raw.strip()))
        if not is_numeric and saw_numeric[i]:
            # Only a column that started out numeric and then met a real text
            # value is a parse fallback worth reporting; a categorical column
            # that was never numeric is expected to be a string.
            rep["notes"].append(
                f"column {raw.strip()!r} fell back to string: "
                f"{text_cells[i]} non-numeric value(s), first {first_text[i]!r}")
        rep["columns"].append({
            "raw": raw.strip(), "name": name, "format": fmt,
            "numeric": is_numeric, "all_int": bool(all_int[i]),
            "level_count": len(level_seen[i]), "level_overflow": level_overflow[i],
            "levels": list(levels[i]), "na_cells": na_cells[i],
            "samples": list(samples[i]),
        })
    rep["rows"] = rows
    rep["ragged_rows"] = ragged
    rep["sentinel_hits"] = sorted(sentinel_hits)
    rep["recodes"] = recodes
    return header, specs, labels, recodes, encoding


def variable_level(column: dict) -> str:
    """Infer the SPSS measurement level for one column."""
    if not column["numeric"]:
        return "NOMINAL"
    count = column["level_count"]
    if column["level_overflow"]:
        return "SCALE"
    if count <= 2 and column["all_int"]:
        return "NOMINAL"
    if column["all_int"] and count <= 10:
        return "ORDINAL"
    return "SCALE"


def build_syntax(csv_path: str, delimiter: str, spss_encoding: str,
                 specs, labels, recodes, columns, sentinels, sav_out=None):
    """Assemble the .sps text (kept separate so tests can inspect it)."""
    delim = "\\t" if delimiter == "\t" else delimiter
    var_lines = "\n    ".join(f"{name} {fmt}" for name, fmt in specs)
    syntax = f"""* Generated by csv_to_spss_syntax.py {SCRIPT_VERSION}.
GET DATA /TYPE=TXT
  /FILE='{csv_path.replace(chr(92), '/').replace(chr(39), chr(39) * 2)}'
  /ENCODING='{spss_encoding}'
  /DELIMITERS="{delim}"
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

    # Numeric variables: declare the standard missing sentinels (or the
    # non-conflicting triple chosen by main when the data already uses them).
    missing_lines = [f"MISSING VALUES {name} ({sentinels[0]}, {sentinels[1]}, {sentinels[2]})."
                     for (name, fmt) in specs if fmt.startswith("F")]
    if missing_lines:
        syntax += ("\n* Numeric missing-value sentinels; change them here if your "
                   "codebook uses others.\n" + "\n".join(missing_lines) + "\nEXECUTE.\n")

    level_lines = [f"  {col['name']} ({variable_level(col)})" for col in columns]
    if level_lines:
        syntax += "\nVARIABLE LEVEL\n" + "\n".join(level_lines) + ".\nEXECUTE.\n"

    # Placeholder value labels for categorical columns: value -> itself, to be
    # replaced by the codebook. Long labels are clipped to the SPSS 120-byte cap.
    value_lines = []
    for col in columns:
        if col["level_overflow"] or not (2 <= col["level_count"] <= 20):
            continue
        pairs = []
        for value in col["levels"]:
            if col["numeric"]:
                # Numeric variables take a bare number as the value label key.
                try:
                    code = format(Decimal(value), "f")
                except InvalidOperation:
                    code = value
                pairs.append(f"{code} {quote_label(value, VALUE_LABEL_BYTES)}")
            else:
                pairs.append(f"{quote_label(value, VALUE_LABEL_BYTES)} "
                             f"{quote_label(value, VALUE_LABEL_BYTES)}")
        if pairs:
            value_lines.append(f"VALUE LABELS {col['name']} " + " ".join(pairs) + ".")
    if value_lines:
        syntax += ("\n* Placeholder VALUE LABELS (value -> value); replace with the "
                   "codebook labels.\n" + "\n".join(value_lines) + "\nEXECUTE.\n")

    if recodes:
        blocks = []
        for r in recodes:
            pairs = " ".join(f"({quote_label(k, VALUE_LABEL_BYTES)}={v})"
                             for k, v in r["map"].items())
            blocks.append(f"RECODE {r['name']} {pairs} INTO {r['new']}.")
            blocks.append(f"VARIABLE LABELS {r['new']} "
                          f"{quote_label(r['label'] + '\uff080/1\uff09')}.")
            values = " ".join(f"{v} {quote_label(k, VALUE_LABEL_BYTES)}"
                              for k, v in r["map"].items())
            blocks.append(f"VALUE LABELS {r['new']} {values}.")
        syntax += "\n* \u5c06\u53ef\u8bc6\u522b\u7684\u201c\u662f/\u5426\u3001\u6709/\u65e0\u201d\u6587\u672c\u5217\u8f6c\u6210 0/1\uff0c\u4f9b Logistic \u4f7f\u7528\u3002\n" + \
                  "\n".join(blocks) + "\nEXECUTE.\n"
    if sav_out:
        sav = sav_out.replace("\\", "/").replace("'", "''")
        syntax += f"\nSAVE OUTFILE='{sav}'.\n"
    return syntax


def write_rename_map(path: str, columns) -> int:
    """Write raw -> SPSS name mapping (S9: renames must be a product, not a log)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    renamed = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["raw", "spss_name", "format", "renamed"])
        for col in columns:
            flag = 1 if col["name"] != col["raw"] else 0
            renamed += flag
            writer.writerow([col["raw"], col["name"], col["format"], flag])
    return renamed


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SPSS import syntax from CSV.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out-sps", required=True)
    parser.add_argument("--sav-out", default=None, help="optional SAVE OUTFILE path")
    parser.add_argument("--encoding", default="utf-8-sig",
                        help="encoding of the written .sps file, which is also the "
                             "encoding declared in GET DATA: utf-8-sig (UTF8, default), "
                             "gb18030/gbk (GBK), big5 (BIG5), or auto to follow the CSV")
    parser.add_argument("--csv-encoding", default="auto",
                        help="CSV encoding: auto (utf-8-sig/gb18030/big5) or a codec name")
    parser.add_argument("--delimiter", default=None,
                        help="field delimiter; default sniffs , ; tab | from the header")
    parser.add_argument("--sample-rows", type=int, default=500,
                        help="raw values kept per column for the preview report; "
                             "type and width inference always scans the whole file")
    parser.add_argument("--rename-map", default=None,
                        help="path for the raw -> SPSS name map "
                             "(default: renamed_map.csv beside --out-sps)")
    parser.add_argument("--no-recode", action="store_true",
                        help="do not add 0/1 RECODE blocks for yes/no text columns")
    args = parser.parse_args()

    csv_path = os.path.abspath(args.csv)
    if not os.path.isfile(csv_path):
        print(f"ERROR: CSV not found: {csv_path}", file=sys.stderr)
        return 2
    try:
        csv_encoding = resolve_csv_encoding(csv_path, args.csv_encoding)
        delimiter = (args.delimiter.replace("\\t", "\t")
                     if args.delimiter is not None else sniff_delimiter(csv_path, csv_encoding))
        write_codec, spss_encoding = resolve_spss_encoding(args.encoding, csv_encoding)
        report: dict = {}
        header, specs, labels, recodes, used_encoding = infer(
            csv_path, args.sample_rows, csv_encoding, delimiter, report=report)
    except Exception as exc:  # noqa: BLE001 - surfaced as a clean CLI error
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not specs:
        print("ERROR: no variables found", file=sys.stderr)
        return 2
    if len(header) == 1:
        # Only warn when the data rows really have more fields than the header,
        # which is the signature of a wrong delimiter; a genuine one-column
        # file must stay quiet.
        try:
            with open(csv_path, encoding=csv_encoding, newline="") as fh:
                fh.readline()
                probe = fh.readline()
            probe_fields = next(csv.reader([probe], delimiter=delimiter), [])
        except (OSError, StopIteration):
            probe_fields = []
        if len(probe_fields) > 1:
            print("WARN: the header parsed as a single field but data rows have "
                  f"more; check --delimiter (sniffed {delimiter!r})", file=sys.stderr)
    if report.get("ragged_rows"):
        print(f"WARN: {report['ragged_rows']} row(s) have a field count different "
              f"from the header; extra fields were dropped and missing fields "
              f"left empty", file=sys.stderr)
    for note in report.get("notes", []):
        print(f"NOTE: {note}", file=sys.stderr)

    sentinels = (-99, -98, -97)
    if set(report.get("sentinel_hits") or ()) & {-99, -98, -97}:
        sentinels = (-999999, -999998, -999997)
        print(f"NOTE: the data already contains -99/-98/-97, so MISSING VALUES "
              f"uses {sentinels} instead", file=sys.stderr)

    syntax = build_syntax(csv_path, delimiter, spss_encoding, specs, labels,
                          [] if args.no_recode else recodes, report["columns"],
                          sentinels, os.path.abspath(args.sav_out) if args.sav_out else None)
    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_sps)), exist_ok=True)
        with open(args.out_sps, "w", encoding=write_codec, newline="\n") as fh:
            fh.write(syntax)
    except (LookupError, UnicodeEncodeError) as exc:
        print(f"ERROR: cannot write the .sps file as {write_codec!r}: {exc}",
              file=sys.stderr)
        return 2

    map_path = args.rename_map or os.path.join(
        os.path.dirname(os.path.abspath(args.out_sps)), "renamed_map.csv")
    renamed = write_rename_map(map_path, report["columns"])
    numeric_count = sum(1 for _name, fmt in specs if fmt.startswith("F"))
    print(f"wrote {args.out_sps} ({len(specs)} variables, {renamed} names sanitized, "
          f"{numeric_count} numeric, encoding {spss_encoding})")
    for (name, fmt), raw in list(zip(specs, header))[:10]:
        note = f"  <- {raw.strip()}" if name != raw.strip() else ""
        print(f"  {name}: {fmt}{note}")
    if len(specs) > 10:
        print(f"  ... {len(specs) - 10} more")
    print(f"rename map: {map_path}")
    print(f"missing values: {sentinels} declared for {numeric_count} numeric variable(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
