#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clean an extracted dataset by executing a recipe the project authored.

This script does NOT decide what to clean. Every transformation - which rows
to drop, which values to map, which ranges are out of bounds - is declared in
a JSON recipe (draft/cleaning.json) written by whoever read the sample. The
engine executes those declarations mechanically, records every step (row
counts in/out, cells changed, values dropped, content fingerprints), and
refuses anything the recipe did not declare. Nothing is cleaned by default:
a recipe with an empty steps list is an explicit "nothing to clean".

The run is deterministic: same dataset file + same recipe -> the same
clean_dataset.csv and the same fingerprint chain in cleaning_log.jsonl, so a
reviewer verifies by replay. All inputs are read as exact strings
(keep_default_na=False); numbers exist only where a coerce_type step created
them, the empty string ALWAYS counts as missing, and the recipe's na_values
only add to that vocabulary (no library NA guessing).

Outputs (under --out):
    clean_dataset.csv    the cleaned table (utf-8-sig, missing as empty)
    cleaning_log.jsonl   header + one record per step + summary (audit trail)
    cleaning_log.md      the same trail, readable
    flow.csv             stage/n/note rows mergeable into sample_flow.csv

Usage:
    python scripts/clean_data.py --dataset output/coding/dataset.csv \\
        --recipe draft/cleaning.json --out output/cleaning
    python scripts/clean_data.py --emit-template draft/cleaning.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
from datetime import datetime, timezone

from analysis_utils import (read_csv_auto, validate_csv_header,
                            validate_csv_shape)

SCRIPT_VERSION = "1.0.0"

# Separators for the deterministic content fingerprint. They are control
# characters that never occur in CSV cell text read as utf-8.
FIELD_SEP = "\x1f"
ROW_SEP = "\x1e"
COL_SEP = "\x1d"
MISSING_MARK = "\x00"

# op -> execution metadata. label is the flow.csv stage when the op changes
# the row count; drops_rows ops count toward the max_drop_fraction guard.
OPS: dict[str, dict] = {
    "drop_exact_duplicates": {"label": "去重后", "drops_rows": True,
                              "keys": {"columns"}},
    "map_values": {"label": None, "drops_rows": False,
                   "keys": {"column", "map", "unmapped"}},
    "coerce_type": {"label": None, "drops_rows": False,
                    "keys": {"column", "to", "on_fail"}},
    "flag_outliers": {"label": None, "drops_rows": False,
                      "keys": {"column", "rule", "action"}},
    "drop_rows_if_missing": {"label": "缺失剔除后", "drops_rows": True,
                             "keys": {"columns", "mode", "reason"}},
    "rename_column": {"label": None, "drops_rows": False,
                      "keys": {"from", "to"}},
    "keep_columns": {"label": None, "drops_rows": False,
                     "keys": {"columns"}},
}

TEMPLATE = {
    "_doc": "清洗配方。由读过这批样本的人/模型填写；clean_data.py 只执行这里"
            "声明的步骤，不做任何未声明的清洗。steps 为空 = 不执行任何步骤"
            "（na_values 词汇表仍生效）。",
    "_ops": {
        "drop_exact_duplicates": "按 columns 组合去掉完全重复的行，保留首行。",
        "map_values": "把 column 里命中 map 的值换成新值。unmapped=error 时出现"
                      "映射表外的非缺失值直接报错；keep 时保留原值。",
        "coerce_type": "把 column 转成 int/float/text。数值解析总是先忽略首尾"
                       "空白（数字不是文本）；on_fail=error 时解析失败直接报"
                       "错，missing 时记为缺失；trim=true 额外作用于 text 列。"
                       "1_000 这类字面分隔符是值不是数。",
        "flag_outliers": "按 rule 的 min/max（闭区间）标记越界值。action="
                         "set_missing 记为缺失；report_only 只记录不改值。",
        "drop_rows_if_missing": "columns 里 any/all 模式命中缺失的行整行剔除，"
                                "reason 必填并进 flow 备注。",
        "rename_column": "重命名一列。",
        "keep_columns": "只保留列出的列（顺序按清单，不得重复）；其余列被丢弃"
                        "并记录。",
    },
    "_guards": "max_drop_fraction 必填：累计丢行比例超过它即中止（exit 2）。"
               "id_columns 声明后在每步之后与结束时必须唯一（初始重复 id 只能"
               "靠去重步消除）。空串恒为缺失；na_values 是在此之上追加的"
               "补充缺失词汇（NaN/inf 拼写是值不是数）。",
    "recipe_version": 1,
    "id_columns": [],
    "max_drop_fraction": None,
    "na_values": [""],
    "steps": [],
}


class RecipeError(Exception):
    """Raised for anything wrong in the recipe or the dataset shape."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_fingerprint(columns: list[str], rows: list[dict]) -> str:
    """Deterministic fingerprint of the in-memory table state.

    Not a file hash: a canonical digest over columns and cell values so the
    chain sha_in -> sha_out of consecutive steps is verifiable by replay.
    """
    digest = hashlib.sha256()
    digest.update(COL_SEP.join(columns).encode("utf-8"))
    for row in rows:
        parts = [MISSING_MARK if row.get(col) is None else str(row[col])
                 for col in columns]
        digest.update(FIELD_SEP.join(parts).encode("utf-8"))
        digest.update(ROW_SEP.encode("utf-8"))
    return digest.hexdigest()


def write_csv(path: str, columns: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns,
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: ("" if row.get(col) is None else row[col])
                             for col in columns})


# ---------------------------------------------------------------------------
# recipe loading and static validation
# ---------------------------------------------------------------------------

def load_recipe(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            recipe = json.load(handle)
    except OSError as exc:
        raise RecipeError(f"recipe not readable: {path} ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise RecipeError(f"recipe is not valid JSON: {path} ({exc})") from exc
    if not isinstance(recipe, dict):
        raise RecipeError("recipe must be a JSON object")

    version = recipe.get("recipe_version")
    if version != 1:
        raise RecipeError(f"recipe_version must be 1, got {version!r}")

    id_columns = recipe.get("id_columns", [])
    if not isinstance(id_columns, list) or not all(
            isinstance(col, str) for col in id_columns):
        raise RecipeError("id_columns must be a list of column names")

    fraction = recipe.get("max_drop_fraction")
    if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) \
            or not 0 <= fraction <= 1:
        raise RecipeError(
            "max_drop_fraction is required and must be a number in [0, 1] "
            "(the guard that stops a runaway drop rule)")

    na_values = recipe.get("na_values", [""])
    if not isinstance(na_values, list) or not na_values or not all(
            isinstance(v, str) for v in na_values):
        raise RecipeError("na_values must be a non-empty list of strings "
                          "(default [\"\"] = only empty means missing)")

    steps = recipe.get("steps", [])
    if not isinstance(steps, list):
        raise RecipeError("steps must be a list")
    return recipe


def validate_steps(steps: list[dict], columns: list[str],
                   na_values: list[str]) -> None:
    """Static check against a simulated column-set evolution."""
    current = list(columns)
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise RecipeError(f"step {index}: must be an object")
        op = step.get("op")
        if op not in OPS:
            known = ", ".join(sorted(OPS))
            raise RecipeError(f"step {index}: unknown op {op!r}; "
                              f"valid ops: {known}")
        missing = OPS[op]["keys"] - set(step)
        if missing:
            raise RecipeError(f"step {index} ({op}): missing keys "
                              f"{sorted(missing)}")
        for key in ("columns",):
            if key in step:
                value = step[key]
                if not isinstance(value, list) or not value or not all(
                        isinstance(col, str) for col in value):
                    raise RecipeError(
                        f"step {index} ({op}): {key} must be a non-empty "
                        "list of column names")
                if len(set(value)) != len(value):
                    raise RecipeError(
                        f"step {index} ({op}): {key} lists a column twice; "
                        "duplicate output columns break round-trips")
        if op == "map_values":
            mapping = step["map"]
            if not isinstance(mapping, dict) or not mapping:
                raise RecipeError(
                    f"step {index}: map must be a non-empty object "
                    "{old value: new value}")
            for key, value in mapping.items():
                if not isinstance(value, str):
                    raise RecipeError(
                        f"step {index}: map value for {key!r} must be a "
                        "string (numbers/booleans would silently become "
                        "their Python spellings; write them as quoted "
                        "strings)")
                if key == "" or key in na_values:
                    raise RecipeError(
                        f"step {index}: map key {key!r} never matches - "
                        "the empty string (and every na_values entry) is "
                        "always read as missing before map_values runs; "
                        "to give these cells a value, fix the source file "
                        "instead of mapping it")
            if step["unmapped"] not in ("error", "keep"):
                raise RecipeError(
                    f"step {index}: unmapped must be 'error' or 'keep'")
        if op == "coerce_type":
            if step["to"] not in ("int", "float", "text"):
                raise RecipeError(f"step {index}: to must be int/float/text")
            if step["on_fail"] not in ("error", "missing"):
                raise RecipeError(
                    f"step {index}: on_fail must be 'error' or 'missing'")
            if "trim" in step and not isinstance(step["trim"], bool):
                raise RecipeError(f"step {index}: trim must be true/false")
        if op == "flag_outliers":
            rule = step["rule"]
            if not isinstance(rule, dict):
                raise RecipeError(f"step {index}: rule must be an object "
                                  "with optional min/max numbers")
            for bound in ("min", "max"):
                if bound in rule and (isinstance(rule[bound], bool) or
                                      not isinstance(rule[bound],
                                                     (int, float))):
                    raise RecipeError(
                        f"step {index}: rule.{bound} must be a number")
            if "min" not in rule and "max" not in rule:
                raise RecipeError(f"step {index}: rule needs at least "
                                  "one of min/max")
            if step["action"] not in ("set_missing", "report_only"):
                raise RecipeError(
                    f"step {index}: action must be set_missing/report_only")
        if op == "drop_rows_if_missing":
            if step["mode"] not in ("any", "all"):
                raise RecipeError(f"step {index}: mode must be any/all")
            if not isinstance(step["reason"], str) or not step["reason"].strip():
                raise RecipeError(
                    f"step {index}: reason is required and goes into "
                    "the flow ledger")
        if op == "rename_column":
            if not isinstance(step["to"], str) or not step["to"]:
                raise RecipeError(f"step {index}: to must be a column name")
            if step["from"] == step["to"]:
                raise RecipeError(
                    f"step {index}: renaming a column to itself")

        # column references must exist at this point of the evolution
        refs: list[str] = []
        if op in ("map_values", "coerce_type", "flag_outliers"):
            refs = [step["column"]]
        elif op in ("drop_rows_if_missing", "keep_columns",
                    "drop_exact_duplicates"):
            refs = list(step["columns"])
        elif op == "rename_column":
            refs = [step["from"]]
            if step["to"] in current and step["to"] != step["from"]:
                raise RecipeError(
                    f"step {index}: renaming to {step['to']!r} collides "
                    "with an existing column")
        unknown = [col for col in refs if col not in current]
        if unknown:
            raise RecipeError(
                f"step {index} ({op}): column(s) not in dataset: "
                f"{unknown}; columns are {current}")
        # evolve the simulated column set
        if op == "rename_column":
            current = [step["to"] if col == step["from"] else col
                       for col in current]
        elif op == "keep_columns":
            current = list(step["columns"])


# ---------------------------------------------------------------------------
# op execution
# ---------------------------------------------------------------------------

def ids_of(row: dict, id_columns: list[str]) -> tuple:
    return tuple(row.get(col) for col in id_columns)


def assert_unique_ids(rows: list[dict], id_columns: list[str],
                      where: str) -> None:
    if not id_columns:
        return
    seen: dict[tuple, int] = {}
    for row in rows:
        key = ids_of(row, id_columns)
        seen[key] = seen.get(key, 0) + 1
    dupes = {key: n for key, n in seen.items() if n > 1}
    if dupes:
        sample = list(dupes.items())[:5]
        shown = ", ".join(repr(key) for key, _ in sample)
        raise RecipeError(
            f"{where}: id_columns are no longer unique ({len(dupes)} "
            f"duplicated id(s), e.g. {shown})")


def canonical_float(value: float) -> str:
    """Shortest string that round-trips to the same float (repr semantics).

    Lossless by construction: two different floats never canonicalize to
    the same text, so the fingerprint chain stays honest for pathological
    values like 1.0000000000000002.
    """
    return repr(value)


def parse_number(text: str, to: str):
    """Parse text as int/float; returns (value, canonical) or raises.

    Leading/trailing whitespace is always ignored for numbers (a number is
    not text; use a text step if padding matters). 'nan'/'inf' spellings,
    Python literal separators like '1_000', and values that OVERFLOW to
    infinity (e.g. '1e999') are rejected: they are values, not numbers -
    map them to missing explicitly or let on_fail fire.
    """
    s = text.strip()
    if not s:
        raise ValueError("empty")
    if "_" in s:
        raise ValueError("digit separators are not numbers")
    lowered = s.lower()
    if lowered in ("nan", "inf", "-inf", "+inf", "infinity", "-infinity"):
        raise ValueError("not a finite number")
    if to == "int":
        try:
            return int(s), str(int(s))
        except ValueError:
            parsed = float(s)
            if not math.isfinite(parsed):
                raise ValueError("overflows to infinity") from None
            if parsed != int(parsed):
                raise ValueError(f"{s!r} is not an integer") from None
            return int(parsed), str(int(parsed))
    parsed = float(s)
    if not math.isfinite(parsed):
        raise ValueError("overflows to infinity")
    return parsed, canonical_float(parsed)


def run_step(step: dict, columns: list[str], rows: list[dict],
             id_columns: list[str]) -> dict:
    """Execute one step in place; returns the record for the log."""
    op = step["op"]
    record: dict = {"record": "step", "op": op,
                    "config": {key: value for key, value in step.items()
                               if not key.startswith("_")},
                    "n_in": len(rows)}
    changed_cells = 0

    if op == "drop_exact_duplicates":
        keys = step["columns"]
        seen: set[tuple] = set()
        kept: list[dict] = []
        dropped_ids: list = []
        for row in rows:
            key = tuple(row.get(col) for col in keys)
            if key in seen:
                dropped_ids.append(ids_of(row, id_columns))
                continue
            seen.add(key)
            kept.append(row)
        rows[:] = kept
        record["n_dropped"] = len(dropped_ids)
        record["dropped_ids_sample"] = [list(ids) for ids in
                                        dropped_ids[:20]]
        record["dedupe_columns"] = keys

    elif op == "map_values":
        column = step["column"]
        mapping = dict(step["map"])
        unmapped_mode = step["unmapped"]
        unmapped_values: dict[str, int] = {}
        for row in rows:
            value = row.get(column)
            if value is None:
                continue
            if value in mapping:
                new = mapping[value]
                if new != value:
                    row[column] = new
                    changed_cells += 1
                continue
            unmapped_values[value] = unmapped_values.get(value, 0) + 1
        if unmapped_values and unmapped_mode == "error":
            sample = sorted(unmapped_values)[:10]
            raise RecipeError(
                f"map_values on {column!r}: {len(unmapped_values)} value(s) "
                f"not in the map and unmapped=error, e.g. {sample}; "
                "extend the map or set unmapped=keep")
        record["n_cells_changed"] = changed_cells
        record["n_unmapped_kept"] = (sum(unmapped_values.values())
                                     if unmapped_values else 0)

    elif op == "coerce_type":
        column = step["column"]
        to = step["to"]
        on_fail = step["on_fail"]
        trim = bool(step.get("trim", False))
        failures: dict[str, int] = {}
        set_missing = 0
        coerced = 0
        for row in rows:
            value = row.get(column)
            if value is None:
                continue
            text = value.strip() if trim else value
            if to == "text":
                if trim and text != value:
                    row[column] = text
                    changed_cells += 1
                continue
            try:
                _, canonical = parse_number(text, to)
            except (ValueError, TypeError):
                if on_fail == "error":
                    failures[text] = failures.get(text, 0) + 1
                    continue
                row[column] = None
                set_missing += 1
                continue
            if canonical != value:
                row[column] = canonical
                changed_cells += 1
            coerced += 1
        if failures:
            sample = sorted(failures)[:10]
            raise RecipeError(
                f"coerce_type on {column!r} to {to}: "
                f"{sum(failures.values())} unparseable value(s) and "
                f"on_fail=error, e.g. {sample}")
        record["n_coerced"] = coerced
        record["n_cells_changed"] = changed_cells
        record["n_set_missing"] = set_missing

    elif op == "flag_outliers":
        column = step["column"]
        rule = step["rule"]
        action = step["action"]
        # every present value must already be numeric: outliers are a range
        # check, not a type coercion
        parsed_rows: list[tuple[dict, float]] = []
        for row in rows:
            value = row.get(column)
            if value is None:
                continue
            try:
                parsed, _ = parse_number(value, "float")
            except (ValueError, TypeError) as exc:
                raise RecipeError(
                    f"flag_outliers on {column!r}: value {value!r} is not "
                    "numeric - run a coerce_type step first "
                    f"({exc})") from exc
            parsed_rows.append((row, parsed))
        low = rule.get("min")
        high = rule.get("max")
        outliers = 0
        samples: list[str] = []
        for row, parsed in parsed_rows:
            if (low is not None and parsed < low) or \
                    (high is not None and parsed > high):
                outliers += 1
                if len(samples) < 10:
                    samples.append(str(row.get(column)))
                if action == "set_missing":
                    row[column] = None
        record["n_outliers"] = outliers
        record["outlier_values_sample"] = samples
        record["bounds"] = {"min": low, "max": high}
        record["action"] = action
        if action == "set_missing":
            changed_cells = outliers

    elif op == "drop_rows_if_missing":
        cols = step["columns"]
        mode = step["mode"]
        kept: list[dict] = []
        dropped_ids: list = []
        for row in rows:
            missing = [row.get(col) is None for col in cols]
            hit = any(missing) if mode == "any" else all(missing)
            if hit:
                dropped_ids.append(ids_of(row, id_columns))
                continue
            kept.append(row)
        rows[:] = kept
        record["n_dropped"] = len(dropped_ids)
        record["dropped_ids_sample"] = [list(ids) for ids in
                                        dropped_ids[:20]]
        record["reason"] = step["reason"]

    elif op == "rename_column":
        old, new = step["from"], step["to"]
        index = columns.index(old)
        columns[index] = new
        for row in rows:
            row[new] = row.pop(old)
        record["renamed"] = {"from": old, "to": new}

    elif op == "keep_columns":
        keep = step["columns"]
        dropped = [col for col in columns if col not in keep]
        for row in rows:
            for col in dropped:
                row.pop(col, None)
        columns[:] = list(keep)
        record["columns_kept"] = list(keep)
        record["columns_dropped"] = dropped

    record["n_out"] = len(rows)
    record["columns_after"] = list(columns)
    if op not in ("drop_exact_duplicates", "drop_rows_if_missing") \
            and changed_cells:
        record["n_cells_changed"] = changed_cells
    return record


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def emit_template(path: str) -> int:
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = json.loads(json.dumps(TEMPLATE))          # deep copy
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError as exc:
        print(f"ERROR: cannot write the template to {path} ({exc}); the "
              "path or its parent directory is not writable",
              file=sys.stderr)
        return 2
    print(f"template written: {path}")
    print("fill id_columns / max_drop_fraction / steps, then run with "
          "--dataset ... --recipe ...")
    return 0


def write_log(path: str, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False,
                                    sort_keys=True))
            handle.write("\n")


def _reject_control_chars(columns: list[str], rows: list[dict]) -> None:
    for col in columns:
        if any(ch in col for ch in (FIELD_SEP, ROW_SEP, COL_SEP,
                                    MISSING_MARK)):
            raise RecipeError(
                f"column name {col!r} contains a control character "
                f"({MISSING_MARK!r}/{COL_SEP!r}/{ROW_SEP!r}/{FIELD_SEP!r})"
                " that collides with the fingerprint separators; fix the "
                "header")
    for row in rows:
        for col in columns:
            value = row[col]
            if value is not None and any(ch in value for ch in
                                        (FIELD_SEP, ROW_SEP, COL_SEP,
                                         MISSING_MARK)):
                raise RecipeError(
                    f"cell in column {col!r} contains a control character "
                    f"({MISSING_MARK!r}/{COL_SEP!r}/{ROW_SEP!r}/{FIELD_SEP!r}"
                    ") that collides with the fingerprint separators; "
                    "map or remove it before cleaning")


# stages this tool owns; re-merging replaces its previous rows instead of
# piling up duplicates, so repeated clean runs stay idempotent
OWNED_STAGE_PREFIXES = ("去重后", "缺失剔除后")
OWNED_STAGES = {"清洗前", "清洗后"}


def merge_flow(path: str, flow_rows: list[dict]) -> None:
    """Append the cleaning stages into an existing sample_flow.csv.

    Keeps the file's column layout: a kind column (written by
    make_coding_sheet when decisions were applied) gets kind=stage for the
    cleaning rows; without it the rows stay three-column - a fresh file is
    created three-column too, since the kind column belongs to the coding
    step that owns the file. Rows from a previous clean run are replaced,
    not duplicated. The file is read with the same encoding candidates as
    the datasets (utf-8-sig first), and always written back as utf-8-sig.
    """
    fieldnames = ["stage", "n", "note"]
    existing: list[dict] = []
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            raw = handle.read()
        text = None
        for encoding in ("utf-8-sig", "gb18030", "big5"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise UnicodeDecodeError(
                "utf-8/gb18030/big5", raw, 0, 1, "not decodable")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        fieldnames = list(reader.fieldnames or ["stage", "n", "note"])
        existing = [dict(row) for row in reader]

    def is_own(row: dict) -> bool:
        stage = row.get("stage", "")
        return (stage in OWNED_STAGES
                or any(stage.startswith(prefix)
                       for prefix in OWNED_STAGE_PREFIXES))

    kept = [row for row in existing if not is_own(row)]
    for row in flow_rows:
        new = {"stage": row["stage"], "n": row["n"], "note": row["note"]}
        if "kind" in fieldnames:
            new["kind"] = "stage"
        kept.append(new)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)


def write_log_md(path: str, records: list[dict]) -> None:
    header = records[0] if records and records[0].get("record") == "header" \
        else None
    summary = records[-1] if records[-1].get("record") == "summary" else None
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# 清洗台账\n\n")
        if header:
            handle.write(f"- 数据集：{header['dataset']['path']} "
                         f"(sha256 `{header['dataset']['sha256'][:12]}…`, "
                         f"{header['dataset']['n_rows']} 行 × "
                         f"{header['dataset']['n_columns']} 列)\n")
            handle.write(f"- 配方：{header['recipe']['path']} "
                         f"(sha256 `{header['recipe']['sha256'][:12]}…`)\n")
            handle.write(f"- 缺失判据：{header['na_values']}\n")
            handle.write(f"- id 列：{header['id_columns'] or '（未声明）'}\n\n")
        else:
            # the run failed before the header was written (unreadable or
            # empty dataset); the failure section below is all there is
            handle.write("- （无 header 记录：清洗在读取数据集时失败）\n\n")
        handle.write("| # | 步骤 | 行数(入→出) | 丢行 | 改格 | 备注 |\n")
        handle.write("|---|------|--------------|------|------|------|\n")
        for record in records:
            if record.get("record") != "step":
                continue
            note_parts = []
            if record.get("n_cells_changed"):
                note_parts.append(f"{record['n_cells_changed']} 格改动")
            if record.get("n_outliers"):
                note_parts.append(f"{record['n_outliers']} 越界")
            if record.get("n_unmapped_kept"):
                note_parts.append(f"{record['n_unmapped_kept']} 保留未映射值")
            if record.get("n_set_missing"):
                note_parts.append(f"{record['n_set_missing']} 转缺失")
            if record.get("columns_dropped"):
                note_parts.append("弃列 " +
                                  ",".join(record["columns_dropped"]))
            if record.get("reason"):
                note_parts.append(record["reason"])
            handle.write(
                f"| {record['step_index']} | {record['op']} "
                f"| {record['n_in']}→{record['n_out']} "
                f"| {record.get('n_dropped', 0)} "
                f"| {record.get('n_cells_changed', 0) or ''} "
                f"| {'；'.join(note_parts)} |\n")
        if summary:
            handle.write(
                f"\n**结果：{summary['n_start']} → {summary['n_final']} 行"
                f"（丢 {summary['n_dropped_total']} 行），"
                f"clean_dataset.csv sha256 "
                f"`{summary['final_sha256'][:12]}…`**\n\n")
            handle.write("复核方式：同一 dataset + 同一 recipe 重跑，"
                         "比对 cleaning_log.jsonl 的 sha_in/sha_out 链。\n")
        if records[-1].get("record") == "failure":
            handle.write(f"\n**失败中止**：{records[-1]['error']}\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute a project-authored cleaning recipe on a "
                    "dataset; every step is recorded and replayable.")
    parser.add_argument("--dataset", help="input CSV, required unless "
                        "--emit-template (e.g. output/coding/dataset.csv)")
    parser.add_argument("--recipe", help="cleaning recipe JSON, required "
                        "unless --emit-template (draft/cleaning.json)")
    parser.add_argument("--out", default="output/cleaning",
                        help="output directory (default output/cleaning)")
    parser.add_argument("--flow-out", metavar="PATH",
                        help="also merge the cleaning stages into this "
                             "sample_flow.csv (replaces rows from a "
                             "previous clean run; adds kind=stage when the "
                             "file has a kind column)")
    parser.add_argument("--emit-template", metavar="PATH",
                        help="write a skeleton recipe to PATH and exit")
    args = parser.parse_args(argv)

    if args.emit_template:
        return emit_template(args.emit_template)
    if not args.dataset or not args.recipe:
        parser.error("--dataset and --recipe are required "
                     "(or use --emit-template)")
    if not os.path.isfile(args.dataset):
        print(f"ERROR: dataset not found: {args.dataset}", file=sys.stderr)
        return 2
    if not os.path.isfile(args.recipe):
        print(f"ERROR: recipe not found: {args.recipe}", file=sys.stderr)
        return 2

    try:
        recipe = load_recipe(args.recipe)
    except RecipeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if os.path.exists(args.out) and not os.path.isdir(args.out):
        print(f"ERROR: --out exists and is not a directory: {args.out}",
              file=sys.stderr)
        return 2
    try:
        os.makedirs(args.out, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: cannot create output directory {args.out} ({exc})",
              file=sys.stderr)
        return 2
    log_records: list[dict] = []

    def fail(message: str) -> int:
        print(f"ERROR: {message}", file=sys.stderr)
        log_records.append({"record": "failure", "error": message,
                            "generated_at": now_iso(), "status": "failed"})
        write_log(os.path.join(args.out, "cleaning_log.jsonl"), log_records)
        write_log_md(os.path.join(args.out, "cleaning_log.md"), log_records)
        return 2

    try:
        frame = read_csv_auto(args.dataset, dtype=str, keep_default_na=False)
    except Exception as exc:                              # noqa: BLE001
        return fail(f"dataset not readable: {exc}")

    # pandas absorbs rows with more fields than the header by promoting the
    # extra fields to an index column (and pads short rows) - silent
    # structural rewriting a provenance tool must refuse
    try:
        offenders = validate_csv_shape(args.dataset)
    except ValueError as exc:
        return fail(str(exc))
    if offenders:
        shown = ", ".join(str(n) if n >= 0 else "…"
                          for n in offenders)
        return fail(
            f"dataset has rows whose field count differs from the header "
            f"(first lines: {shown}); fix the file - the reader would "
            "silently absorb or pad those rows")
    # duplicate/empty header names: pandas renames them before anyone
    # sees the file; the ledger must record the names as they are
    try:
        problems = validate_csv_header(args.dataset)
    except ValueError as exc:
        return fail(str(exc))
    if problems:
        return fail("dataset header problems (pandas would silently "
                    f"rename these): {'; '.join(problems[:5])}")

    columns = [str(col) for col in frame.columns.tolist()]
    if not columns or frame.empty:
        return fail("dataset has no columns or no rows")
    rows = [{col: (None if val == "" else val)
             for col, val in zip(columns, vals)}
            for vals in frame.values.tolist()]
    # the fingerprint separators must be collision-proof: control characters
    # in cells could forge column/row boundaries, so refuse them up front
    try:
        _reject_control_chars(columns, rows)
    except RecipeError as exc:
        return fail(str(exc))
    # apply the recipe's missing-value vocabulary to the raw strings
    na_values = list(recipe.get("na_values", [""]))
    if na_values != [""]:
        blanks = set(na_values) - {""}
        for row in rows:
            for col in columns:
                if row[col] in blanks:
                    row[col] = None

    id_columns = list(recipe.get("id_columns", []))
    steps = list(recipe.get("steps", []))
    max_drop_fraction = recipe.get("max_drop_fraction")

    unknown_ids = [col for col in id_columns if col not in columns]
    if unknown_ids:
        return fail(f"id_columns not in dataset: {unknown_ids}; "
                    f"columns are {columns}")

    log_records.append({
        "record": "header",
        "tool": "clean_data.py",
        "version": SCRIPT_VERSION,
        "dataset": {"path": args.dataset,
                    "sha256": sha256_file(args.dataset),
                    "n_rows": len(rows), "n_columns": len(columns),
                    # snapshot: later steps mutate the column list in place
                    # (rename/keep), and the header must keep stating the
                    # INPUT columns, not the cleaned ones
                    "columns": list(columns)},
        "recipe": {"path": args.recipe,
                   "sha256": sha256_file(args.recipe)},
        "na_values": na_values,
        "id_columns": id_columns,
        "max_drop_fraction": max_drop_fraction,
        "generated_at": now_iso(),
    })

    try:
        validate_steps(steps, columns, na_values)

        n_start = len(rows)
        total_dropped = 0
        flow_rows = [{"stage": "清洗前", "n": n_start,
                      "note": f"rows in {os.path.basename(args.dataset)}"}]
        stage_counts: dict[str, int] = {}

        for index, step in enumerate(steps, start=1):
            fingerprint_in = content_fingerprint(columns, rows)
            record = run_step(step, columns, rows, id_columns)
            record["step_index"] = index
            record["sha_in"] = fingerprint_in
            record["sha_out"] = content_fingerprint(columns, rows)
            record["generated_at"] = now_iso()
            log_records.append(record)

            assert_unique_ids(rows, id_columns,
                              f"after step {index} ({step['op']})")

            if OPS[step["op"]]["drops_rows"]:
                total_dropped = n_start - len(rows)
                fraction = total_dropped / n_start if n_start else 0.0
                if fraction > max_drop_fraction:
                    raise RecipeError(
                        f"step {index} ({step['op']}): cumulative drop "
                        f"{total_dropped}/{n_start} rows = "
                        f"{fraction:.1%} exceeds max_drop_fraction "
                        f"{float(max_drop_fraction):.1%}; confirm the rule "
                        "and raise the guard explicitly")
                label = OPS[step["op"]]["label"]
                stage_counts[label] = stage_counts.get(label, 0) + 1
                stage_name = (label if stage_counts[label] == 1
                              else f"{label} {stage_counts[label]}")
                flow_rows.append({
                    "stage": stage_name, "n": len(rows),
                    "note": f"step {index} {step['op']}"
                            + (f": {step['reason']}"
                               if step.get("reason") else "")})

        # the id invariant is enforced after every step and at the end:
        # a pre-run check would make "dedupe first, then clean" impossible,
        # while the final check still refuses an undeclared duplicate id
        assert_unique_ids(rows, id_columns, "after cleaning")

        n_final = len(rows)
        # the closing 清洗后 row is always written: it is the anchor the
        # analysis N cites, even when the last step dropped nothing
        flow_rows.append({"stage": "清洗后", "n": n_final,
                          "note": f"after {len(steps)} step(s)"})

        if args.flow_out:
            try:
                merge_flow(args.flow_out, flow_rows)
            except (OSError, UnicodeDecodeError, csv.Error) as exc:
                raise RecipeError(
                    f"cannot merge the cleaning stages into "
                    f"{args.flow_out} ({exc}); the file is not a readable "
                    "sample_flow.csv or its directory is not writable"
                ) from exc

        # outputs
        clean_path = os.path.join(args.out, "clean_dataset.csv")
        write_csv(clean_path, columns, rows)
        flow_path = os.path.join(args.out, "flow.csv")
        with open(flow_path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=["stage", "n", "note"])
            writer.writeheader()
            writer.writerows(flow_rows)

        log_records.append({
            "record": "summary", "status": "ok",
            "n_start": n_start, "n_final": n_final,
            "n_dropped_total": n_start - n_final,
            "steps_run": len(steps),
            "final_sha256": sha256_file(clean_path),
            "outputs": {"clean_dataset.csv": clean_path,
                        "flow.csv": flow_path},
            "generated_at": now_iso(),
        })
        write_log(os.path.join(args.out, "cleaning_log.jsonl"), log_records)
        write_log_md(os.path.join(args.out, "cleaning_log.md"), log_records)

        print(f"cleaned: {n_start} -> {n_final} rows "
              f"({n_start - n_final} dropped) -> {clean_path}")
        print(f"log: {os.path.join(args.out, 'cleaning_log.jsonl')}")
        print(f"flow: {flow_path}")
        if args.flow_out:
            print(f"flow merged: {args.flow_out}")
        return 0
    except RecipeError as exc:
        return fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())
