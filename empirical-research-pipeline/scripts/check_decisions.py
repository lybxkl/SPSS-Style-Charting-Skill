#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate the judgment ledger (``decisions.jsonl``) before it is trusted.

A decision is a claim: "this value belongs to this field", "this document is
excluded", "this model is the one to report".  The scripts cannot judge the
claim, but they can prove whether its evidence exists and whether the value it
names was ever seen by the extraction instrument.  That is the contract this
module enforces:

* every entry has the required keys, a unique id and a confidence in 0..1;
* every evidence reference resolves to a real file and, for ``path@start-end``,
  a real span (and the optional ``quote`` must match that span);
* a ``value`` decision must name a candidate the extractor actually produced;
* two decisions for one target are a conflict unless one ``supersedes`` the
  other;
* ``needs_human=true`` blocks delivery until it is resolved.

Nothing here decides *what* the right value is.  It only refuses a ledger that
cannot be checked.

Usage:
  python scripts/check_decisions.py --decisions decisions.jsonl --root corpus \
      --review extraction_review.csv --out qa/decision_issues.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

SCRIPT_VERSION = "1.0.0"

REQUIRED = ("id", "stage", "target", "decision", "reason", "evidence", "confidence")
STAGES = {"audit", "extract", "dataset", "stats", "figures", "manuscript", "qa"}
DECISIONS = {"keep", "drop", "exclude", "include", "na", "value",
             "method", "skip", "accept", "reject", "note"}

_SPAN_RE = re.compile(r"^(?P<path>.+?)@(?P<start>\d+)-(?P<end>\d+)$")
_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")


class DecisionError(ValueError):
    """The ledger itself cannot be read."""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _read_text(path: str) -> str:
    for encoding in _ENCODINGS:
        try:
            with open(path, encoding=encoding) as fh:
                return fh.read()
        except UnicodeDecodeError:
            continue
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _resolve(path: str, root: str) -> str:
    return path if os.path.isabs(path) else os.path.join(root or ".", path)


def load_decisions(path: str) -> list[dict]:
    """Read one JSON object per line; a malformed line is a hard error."""
    out = []
    with open(path, encoding="utf-8-sig") as fh:
        for number, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DecisionError(f"{path}:{number}: invalid JSON: {exc}") from exc
            if not isinstance(item, dict):
                raise DecisionError(f"{path}:{number}: each line must be an object")
            out.append(item)
    return out


def load_review(path: str | None) -> dict[tuple[str, str], dict]:
    """Index ``extraction_review.csv`` by (rel_path, field)."""
    if not path:
        return {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {(row.get("rel_path", ""), row.get("field", "")): row for row in rows}


def _alternatives(row: dict) -> list[str]:
    raw = row.get("alternatives") or ""
    values = []
    for part in str(raw).split("|"):
        part = part.strip()
        if part and part not in values:
            values.append(part)
    return values


def _same_value(left, right) -> bool:
    """67 and "67.0" are the same reading; a dict/list never is a cell value."""
    if isinstance(left, (dict, list)) or isinstance(right, (dict, list)):
        return False
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return str(left).strip() == str(right).strip()


def _issue(severity: str, check: str, item: dict, detail: str) -> dict:
    return {"severity": severity, "check": check,
            "id": item.get("id", ""), "target": item.get("target", ""),
            "detail": detail}


def _check_evidence(item: dict, root: str) -> list[dict]:
    issues = []
    refs = item.get("evidence")
    if not isinstance(refs, list) or not refs:
        return [_issue("error", "evidence", item, "evidence must be a non-empty list")]
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            issues.append(_issue("error", "evidence", item, "empty evidence reference"))
            continue
        if "::" in ref:
            path, locator = ref.split("::", 1)
            if not locator.strip():
                issues.append(_issue("error", "evidence", item,
                                     f"empty locator in {ref!r}"))
            if not os.path.exists(_resolve(path, root)):
                issues.append(_issue("error", "evidence", item,
                                     f"file not found: {path}"))
            continue
        match = _SPAN_RE.match(ref)
        if not match:
            if not os.path.exists(_resolve(ref, root)):
                issues.append(_issue("error", "evidence", item,
                                     f"file not found: {ref}"))
            continue
        path = match.group("path")
        full = _resolve(path, root)
        if not os.path.exists(full):
            issues.append(_issue("error", "evidence", item,
                                 f"file not found: {path}"))
            continue
        start, end = int(match.group("start")), int(match.group("end"))
        text = _read_text(full)
        if start < 0 or end <= start or end > len(text):
            issues.append(_issue(
                "error", "evidence", item,
                f"span out of range: {ref} (file length {len(text)})"))
            continue
        quote = item.get("quote")
        if quote:
            slice_n = _norm(text[start:end])
            quote_n = _norm(quote)
            if quote_n not in slice_n and slice_n not in quote_n:
                issues.append(_issue(
                    "error", "evidence", item,
                    f"quote does not match {ref}: {quote_n[:40]!r} vs {slice_n[:40]!r}"))
    return issues


def _check_target(item: dict, root: str) -> list[dict]:
    target = item.get("target")
    if not isinstance(target, str) or not target.strip():
        return [_issue("error", "schema", item, "target must be a non-empty string")]
    if "#" in target:
        path = target.rsplit("#", 1)[0]
        if os.path.splitext(path)[1] and not os.path.exists(_resolve(path, root)):
            return [_issue("error", "target", item, f"target file not found: {path}")]
    return []


def _check_candidate(item: dict, review: dict) -> list[dict]:
    if item.get("stage") != "extract":
        return []
    target = str(item.get("target") or "")
    if "#" not in target:
        return []
    rel_path, field = target.rsplit("#", 1)
    row = review.get((rel_path, field))
    if row is None:
        return [_issue("error", "candidate", item,
                       f"target not present in extraction_review.csv: {target}")]
    if item.get("decision") != "value":
        return []
    value = item.get("value")
    if value is None:
        return [_issue("error", "candidate", item,
                       "decision=value requires a non-null value")]
    seen = _alternatives(row)
    current = str(row.get("value") or "").strip()
    if current:
        seen.append(current)
    if isinstance(value, (dict, list)):
        return [_issue("error", "candidate", item,
                       "value must be a scalar, not a list/dict")]
    if not any(_same_value(value, candidate) for candidate in seen):
        return [_issue(
            "error", "candidate", item,
            f"value {value!r} was never a candidate for {target}; "
            f"candidates: {seen[:6]}")]
    return []


def validate_decisions(decisions: list[dict], root: str = ".",
                       review: dict | None = None,
                       allow_unresolved: bool = False) -> list[dict]:
    """Return every issue; an empty list means the ledger is trustworthy."""
    review = review or {}
    issues: list[dict] = []
    seen_ids: set[str] = set()
    targets: dict[str, dict] = {}

    for item in decisions:
        missing = [key for key in REQUIRED if key not in item]
        if missing:
            issues.append(_issue("error", "schema", item,
                                 f"missing required keys: {', '.join(missing)}"))
            continue
        ident = str(item.get("id") or "")
        if not ident:
            issues.append(_issue("error", "schema", item, "id must be non-empty"))
        elif ident in seen_ids:
            issues.append(_issue("error", "schema", item, f"duplicate id: {ident}"))
        seen_ids.add(ident)

        stage = item.get("stage")
        if stage not in STAGES:
            issues.append(_issue("error", "schema", item,
                                 f"unknown stage: {stage!r}"))
        decision = item.get("decision")
        if decision not in DECISIONS:
            issues.append(_issue("error", "schema", item,
                                 f"unknown decision: {decision!r}"))
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError):
            confidence = -1.0
        if not 0.0 <= confidence <= 1.0:
            issues.append(_issue("error", "schema", item,
                                 "confidence must be between 0 and 1"))
        if not _norm(item.get("reason")):
            issues.append(_issue("error", "schema", item, "reason must be non-empty"))
        if not isinstance(item.get("needs_human", False), bool):
            issues.append(_issue("error", "schema", item,
                                 "needs_human must be true or false"))

        issues.extend(_check_target(item, root))
        issues.extend(_check_evidence(item, root))
        issues.extend(_check_candidate(item, review))

        target = str(item.get("target") or "")
        previous = targets.get(target)
        if previous is not None and item.get("supersedes") != previous.get("id"):
            issues.append(_issue(
                "error", "duplicate", item,
                f"target {target!r} already decided by {previous.get('id')}; "
                "supersedes must name that exact previous decision id"))
        elif previous is None and item.get("supersedes"):
            issues.append(_issue("error", "supersedes", item, "supersedes names no earlier decision for this target"))
        targets[target] = item

    for item in targets.values():
        if item.get("needs_human") and not allow_unresolved:
            issues.append(_issue("error", "unresolved", item,
                                 "needs_human=true; resolve it or pass --allow-unresolved"))

    return issues


def write_issues(path: str, issues: list[dict]) -> None:
    fields = ["severity", "check", "id", "target", "detail"]
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(issues)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate decisions.jsonl (schema, evidence, candidates).")
    parser.add_argument("--decisions", required=True, help="decisions.jsonl")
    parser.add_argument("--root", default=".", help="root for relative evidence paths")
    parser.add_argument("--review", default=None,
                        help="extraction_review.csv; enables the candidate check")
    parser.add_argument("--out", default=None,
                        help="issues CSV (default: next to the decisions file)")
    parser.add_argument("--allow-unresolved", action="store_true",
                        help="permit needs_human=true entries (draft review only)")
    args = parser.parse_args(argv)

    try:
        decisions = load_decisions(args.decisions)
    except (OSError, DecisionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    review = load_review(args.review)
    issues = validate_decisions(decisions, args.root, review,
                                args.allow_unresolved)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.decisions)),
                                   "decision_issues.csv")
    write_issues(out, issues)

    errors = sum(1 for issue in issues if issue["severity"] == "error")
    warnings = len(issues) - errors
    print(f"decisions: {len(decisions)}  errors: {errors}  warnings: {warnings}")
    print(f"issues: {out}")
    if errors:
        for issue in issues[:8]:
            if issue["severity"] == "error":
                print(f"ERROR [{issue['check']}] {issue['id'] or '-'}: "
                      f"{issue['detail']}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
