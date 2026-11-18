# -*- coding: utf-8 -*-
"""Structured sampling for extraction review (batch 2).

Self-selected audit samples cannot be audited: the same agent that drew
them decides what gets re-checked.  This tool replaces that with a
protocol:

* ``draw`` builds the review sample from ``extraction_review.csv`` with an
  explicit seed, a rate (or fixed n), per-stratum minimums and a mandatory
  flagged/unflagged split - ``needs_review`` rows are the risk pool and
  are never diluted into one big bucket.  The same inputs plus the same
  seed reproduce the same sample byte-for-byte, so "which rows were
  checked" is itself a checkable fact.
* ``tally`` reads the adjudicated sample back: verdicts are counted per
  stratum, recodes are listed with their corrected values, and a sample
  that is not fully adjudicated never reads as passed.

The tool samples; it never judges.  Whether a drawn value is right is a
human/LLM read of the source, anchored by the span each row carries.

CLI::

    python scripts/sample_review.py draw \
        --review output/coding/extraction_review.csv \
        --dataset output/coding/dataset.csv --strata doc_type \
        --seed 20261118 --rate 0.1 --min-per-stratum 2 \
        --out output/review
    python scripts/sample_review.py tally \
        --sample output/review/sample.csv --fail-above 0.10
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from analysis_utils import validate_csv_header, validate_csv_shape  # noqa: E402

SCRIPT_VERSION = "1.0.0"
REVIEW_COLUMNS = ["rel_path", "field", "value", "raw", "source", "span",
                  "na_hit", "cross_line", "needs_review", "flags",
                  "alternatives", "note"]
VERDICTS = {
    "保持": "agree",
    "keep": "agree",
    "agree": "agree",
    "改判": "recode",
    "recode": "recode",
    "无法核对": "unverifiable",
    "unverifiable": "unverifiable",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def error(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 2


def _read_csv(path: str) -> tuple[list[str], list[dict]]:
    offenders = validate_csv_shape(path)
    if offenders:
        shown = ", ".join(str(n) if n >= 0 else "…"
                          for n in offenders)
        raise ValueError(
            f"{path}: rows whose field count differs from the header "
            f"(first lines: {shown}); fix the file - the reader would "
            "silently absorb or pad those rows")
    problems = validate_csv_header(path)
    if problems:
        raise ValueError(f"{path}: header problems (pandas would silently "
                         f"rename these): {'; '.join(problems[:5])}")
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    return columns, rows


def _sample_id(seed: str, rel_path: str, field: str, span: str,
               row_index: int) -> str:
    digest = hashlib.sha256(
        f"{seed}|{rel_path}|{field}|{span}|{row_index}".encode("utf-8")
    ).hexdigest()
    return "sp_" + digest[:12]


def _stratum_plan(populations: dict[str, list[dict]], rate: float | None,
                  fixed_n: int | None, min_per_stratum: int
                  ) -> dict[str, int]:
    """Per-stratum sample sizes: rate-based with a floor, or a
    largest-remainder proportional split of a fixed n.

    Invariants (both paths):
    * every stratum gets at least ``min(min_per_stratum, its population)``
      - the floor is capped at the population, never eaten by trimming;
    * the plan never exceeds the stratum populations;
    * the ``fixed_n`` plan totals exactly ``fixed_n``.

    The fixed_n path allocates floors FIRST (capped at populations) and
    then splits what is left proportionally to the remaining capacity, so
    no trimming step exists that could silently break a floor it just
    raised. Raises ValueError when the floors alone cannot fit within
    fixed_n - the conflict is refused, never fudged.
    """
    keys = sorted(populations)
    if rate is not None:
        plan = {}
        for key in keys:
            size = len(populations[key])
            want = max(min_per_stratum, round(rate * size))
            plan[key] = min(size, max(0, want))
        return plan
    total = sum(len(populations[key]) for key in keys)
    if fixed_n >= total:
        return {key: len(populations[key]) for key in keys}
    # floors first, capped at each population
    plan = {key: min(min_per_stratum, len(populations[key]))
            for key in keys}
    floor_total = sum(plan.values())
    if floor_total > fixed_n:
        raise ValueError(
            f"--n {fixed_n} cannot honor --min-per-stratum "
            f"{min_per_stratum} across {len(keys)} strata after capping "
            f"floors at stratum sizes; either raise --n, lower the floor, "
            "or drop it")
    # distribute the remainder over the remaining capacity
    capacity = {key: len(populations[key]) - plan[key] for key in keys}
    room = fixed_n - floor_total
    cap_total = sum(capacity.values())
    if cap_total <= 0 or room <= 0:
        return plan
    exact = {key: room * capacity[key] / cap_total for key in keys}
    for key in keys:
        plan[key] += min(int(exact[key]), capacity[key])
    left = fixed_n - sum(plan.values())
    order = sorted(keys, key=lambda k: (-(exact[k] - int(exact[k])), k))
    for key in order:
        if left <= 0:
            break
        if capacity[key] > 0:
            plan[key] += 1
            left -= 1
    if sum(plan.values()) != fixed_n:
        # unreachable unless the capacity math above changes; keep it loud
        # rather than return a plan that breaks a stated invariant
        raise ValueError(
            f"internal: plan total {sum(plan.values())} != --n {fixed_n}")
    return plan


def cmd_draw(args) -> int:
    if not os.path.isfile(args.review):
        return error(f"--review not found: {args.review}")
    if args.dataset and not os.path.isfile(args.dataset):
        return error(f"--dataset not found: {args.dataset}")
    if args.rate is not None and args.n is not None:
        return error("give either --rate or --n, not both")
    rate = args.rate if args.rate is not None else \
        (None if args.n is not None else 0.1)
    if rate is not None and not (0 < rate <= 1):
        return error("--rate must be within (0, 1]")
    if args.n is not None and args.n < 1:
        return error("--n must be at least 1")
    if args.min_per_stratum < 0:
        return error("--min-per-stratum cannot be negative")

    try:
        review_columns, rows = _read_csv(args.review)
    except ValueError as exc:
        return error(str(exc))
    missing_columns = [c for c in REVIEW_COLUMNS if c not in review_columns]
    if missing_columns:
        return error(f"--review is not an extraction_review.csv; missing "
                     f"columns: {missing_columns}")

    strata_value: dict[str, str] = {}
    dataset_sha = None
    if args.dataset:
        try:
            _ds_columns, ds_rows = _read_csv(args.dataset)
        except ValueError as exc:
            return error(str(exc))
        if args.strata not in _ds_columns or "rel_path" not in _ds_columns:
            return error(f"--dataset has no {args.strata!r}/rel_path "
                         "columns; cannot stratify")
        for row in ds_rows:
            strata_value[row.get("rel_path", "")] = \
                row.get(args.strata, "") or "(未标)"
        dataset_sha = {"path": args.dataset, "sha256": sha256_file(args.dataset),
                       "n_rows": len(ds_rows)}

    populations: dict[str, list[dict]] = {}
    for index, row in enumerate(rows):
        flag_raw = str(row.get("needs_review", "")).strip()
        flagged = "yes" if flag_raw.lower() not in \
            ("", "false", "0", "no") else "no"
        if args.dataset:
            base = strata_value.get(row.get("rel_path", ""),
                                    "(数据集外)")
            key = f"{args.strata}={base}|flagged={flagged}"
        else:
            key = f"flagged={flagged}"
        row["_row_index"] = index
        row["_stratum"] = key
        populations.setdefault(key, []).append(row)

    try:
        plan = _stratum_plan(populations, rate, args.n, args.min_per_stratum)
    except ValueError as exc:
        return error(str(exc))
    if sum(plan.values()) == 0:
        return error("the plan draws zero rows; raise --rate/--n")

    sample_rows: list[dict] = []
    strata_report = []
    for key in sorted(populations):
        population = sorted(populations[key],
                            key=lambda r: (r.get("rel_path", ""),
                                           r.get("field", ""),
                                           r.get("span", ""),
                                           r["_row_index"]))
        want = plan[key]
        rng = random.Random(f"{args.seed}|{key}")
        picked = rng.sample(population, want) if want < len(population) \
            else list(population)
        for row in picked:
            sample_rows.append({
                "sample_id": _sample_id(args.seed, row.get("rel_path", ""),
                                        row.get("field", ""),
                                        row.get("span", ""),
                                        row["_row_index"]),
                "stratum": key,
                **{col: row.get(col, "") for col in REVIEW_COLUMNS},
                "verdict": "",
                "corrected_value": "",
                "reviewer_note": "",
            })
        strata_report.append({
            "key": key,
            "n_population": len(population),
            "n_sample": len(picked),
            "coverage": round(len(picked) / len(population), 4)
            if population else 0,
        })

    if os.path.exists(args.out) and not os.path.isdir(args.out):
        return error(f"--out exists and is not a directory: {args.out}")
    try:
        os.makedirs(args.out, exist_ok=True)
    except OSError as exc:
        return error(f"cannot create output directory {args.out} ({exc})")

    sample_path = os.path.join(args.out, "sample.csv")
    columns = ["sample_id", "stratum"] + REVIEW_COLUMNS + \
        ["verdict", "corrected_value", "reviewer_note"]
    with open(sample_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns,
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sample_rows)

    protocol = {
        "schema": "sample-protocol/1",
        "tool": "sample_review.py",
        "version": SCRIPT_VERSION,
        "mode": "draw",
        "seed": args.seed,
        "rate": rate,
        "n": args.n,
        "min_per_stratum": args.min_per_stratum,
        "strata_column": args.strata if args.dataset else None,
        "inputs": {
            "review": {"path": args.review,
                        "sha256": sha256_file(args.review),
                        "n_rows": len(rows)},
            "dataset": dataset_sha,
        },
        "strata": strata_report,
        "total": {
            "n_population": len(rows),
            "n_sample": len(sample_rows),
            "coverage": round(len(sample_rows) / len(rows), 4)
            if rows else 0,
        },
        "sample_csv_sha256": sha256_file(sample_path),
        "verdict_vocabulary": ["保持", "改判", "无法核对"],
        "note": "同一 review/dataset/seed 重跑得到同一 sample.csv；抽样"
                "不判断对错，每行带 span/raw 供回原文核对。",
        "generated_at": now_iso(),
    }
    protocol_path = os.path.join(args.out, "protocol.json")
    with open(protocol_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(protocol, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"sample: {len(sample_rows)}/{len(rows)} rows drawn "
          f"({len(strata_report)} strata) -> {sample_path}")
    print(f"protocol: {protocol_path}")
    return 0


def cmd_tally(args) -> int:
    if not os.path.isfile(args.sample):
        return error(f"--sample not found: {args.sample}")
    if args.fail_above is not None and not (0 < args.fail_above <= 1):
        return error("--fail-above must be within (0, 1]")
    try:
        columns, rows = _read_csv(args.sample)
    except ValueError as exc:
        return error(str(exc))
    for column in ("sample_id", "stratum", "verdict", "rel_path", "field"):
        if column not in columns:
            return error(f"--sample is not an adjudicated sample.csv; "
                         f"missing column: {column}")

    unknown: list[str] = []
    unfilled = 0
    recode_missing: list[str] = []
    per_stratum: dict[str, dict] = {}
    disagreements = []
    for row in rows:
        key = row.get("stratum", "")
        verdict = str(row.get("verdict", "")).strip()
        bucket = per_stratum.setdefault(
            key, {"n_sample": 0, "filled": 0, "agree": 0, "recode": 0,
                  "unverifiable": 0, "unfilled": 0})
        bucket["n_sample"] += 1
        if not verdict:
            bucket["unfilled"] += 1
            unfilled += 1
            continue
        if verdict not in VERDICTS:
            unknown.append(f"{row.get('sample_id')}: {verdict!r}")
            continue
        normalized = VERDICTS[verdict]
        bucket["filled"] += 1
        bucket[normalized] += 1
        if normalized == "recode":
            if not str(row.get("corrected_value", "")).strip():
                recode_missing.append(row.get("sample_id", ""))
                continue
            disagreements.append({
                "sample_id": row.get("sample_id", ""),
                "rel_path": row.get("rel_path", ""),
                "field": row.get("field", ""),
                "current_value": row.get("value", ""),
                "corrected_value": row.get("corrected_value", ""),
                "reviewer_note": row.get("reviewer_note", ""),
            })

    if unknown:
        return error("unknown verdict spellings (use 保持/改判/无法核对 "
                     f"or keep/recode/unverifiable): {unknown[:5]}")
    if unfilled:
        return error(f"{unfilled} sampled row(s) have no verdict; a "
                     "partially adjudicated sample is not a completed "
                     "review - fill every row or draw a smaller sample")
    if recode_missing:
        return error(
            f"verdict=改判 without corrected_value on sample_id(s) "
            f"{recode_missing[:5]}; a recode must state what the value "
            "should become - an uncorrected recode is an incomplete "
            "adjudication, not a completed review")

    def rate_of(bucket: dict) -> float:
        filled = bucket["filled"]
        return round(bucket["recode"] / filled, 4) if filled else 0.0

    strata_out = []
    overall = {"n_sample": 0, "filled": 0, "agree": 0, "recode": 0,
               "unverifiable": 0, "unfilled": 0}
    for key in sorted(per_stratum):
        bucket = per_stratum[key]
        for name in overall:
            overall[name] += bucket[name]
        strata_out.append({
            "key": key,
            **bucket,
            "recode_rate": rate_of(bucket),
        })
    overall["recode_rate"] = rate_of(overall)

    tally = {
        "schema": "sample-tally/1",
        "tool": "sample_review.py",
        "version": SCRIPT_VERSION,
        "mode": "tally",
        "sample": {"path": args.sample, "sha256": sha256_file(args.sample),
                   "n_rows": len(rows)},
        "per_stratum": strata_out,
        "overall": overall,
        "disagreements": disagreements,
        "fail_above": args.fail_above,
        "generated_at": now_iso(),
    }
    out_path = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.sample)), "tally.json")
    if os.path.exists(out_path) and not os.path.isfile(out_path):
        return error(f"--out exists and is not a file: {out_path}")
    parent = os.path.dirname(os.path.abspath(out_path))
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            return error(f"cannot create directory {parent} ({exc})")
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(tally, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(f"tally: {overall['n_sample']} rows, "
          f"agree={overall['agree']} recode={overall['recode']} "
          f"unverifiable={overall['unverifiable']}"
          f" -> {out_path}")
    if args.fail_above is not None \
            and overall["recode_rate"] > args.fail_above:
        print(f"ERROR: recode rate {overall['recode_rate']:.4f} exceeds "
              f"--fail-above {args.fail_above}; the extraction needs a "
              "wider review or a recode pass", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Structured sampling for extraction review: seeded, "
                    "stratified, coverage-accounted; never self-selected.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)

    draw = sub.add_parser("draw", help="build the review sample")
    draw.add_argument("--review", required=True,
                     help="extraction_review.csv from make_coding_sheet "
                          "--extract")
    draw.add_argument("--dataset",
                      help="optional dataset.csv; enables --strata")
    draw.add_argument("--strata", default="doc_type",
                      help="column of dataset.csv to stratify on "
                           "(default doc_type; requires --dataset)")
    draw.add_argument("--seed", required=True,
                      help="any string; recorded in protocol.json; the same "
                           "seed reproduces the same sample")
    draw.add_argument("--rate", type=float,
                     help="fraction of each stratum to draw (default 0.1)")
    draw.add_argument("--n", type=int,
                     help="fixed total sample size, split proportionally "
                          "across strata (mutually exclusive with --rate)")
    draw.add_argument("--min-per-stratum", type=int, default=0,
                     help="minimum rows per stratum regardless of --rate; "
                          "with --n it must be satisfiable within the "
                          "total (refused otherwise)")
    draw.add_argument("--out", default="output/review",
                      help="output directory (default output/review)")
    draw.set_defaults(func=cmd_draw)

    tally = sub.add_parser("tally", help="count verdicts of a filled sample")
    tally.add_argument("--sample", required=True,
                       help="sample.csv after every verdict is filled")
    tally.add_argument("--fail-above", type=float,
                       help="user-declared recode-rate ceiling; exceeding it "
                            "exits 2 (default: report only)")
    tally.add_argument("--out",
                       help="output file for tally.json "
                            "(default: beside sample.csv)")
    tally.set_defaults(func=cmd_tally)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
