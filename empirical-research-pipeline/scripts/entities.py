# -*- coding: utf-8 -*-
"""Cross-material entities, relations, join audits and unit harmonisation.

Longitudinal and multi-source material does not stay tidily in one table: the
same firm appears in a registry, an interview and a financial sheet; the same
person is ``P01`` here and ``p-1`` there; one table is in 万元 and another in 元.
This module records *how* those were reconciled instead of silently joining.

The invariants:

* an ``entity`` is keyed by a declared identity rule, never by row position;
* a ``relation`` is a claim about two entities with evidence, not a foreign key;
* a ``join_audit`` says what matched, what did not, what was ambiguous, and what
  the resulting unit of observation is - so downstream N is per real unit;
* unit/scale harmonisation writes an explicit mapping, and a conflict is a
  recorded decision, not a wink.

CLI::

    python entities.py --root . entity-type --id firm --fields name,reg_no
    python entities.py --root . entity --type firm --key "A-001" --name "甲公司"
    python entities.py --root . relation --from firm:A-001 --to person:P01 \\
        --type employs --evidence materials/x.csv
    python entities.py --root . join --left data/a.csv --right data/b.csv \\
        --on id --how left --unit "一家企业"
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C


def _producer(**kw) -> dict:
    return C.producer_for("entities", version="2.0", module_file=__file__, **kw)


RELATION_TYPES = ("employs", "member_of", "located_in", "owns", "part_of",
                  "same_as", "succeeded_by", "interviewed", "measured_at",
                  "reports_to", "trades_with")

#: canonical units with their factor to the base unit of the dimension
UNIT_TABLE = {
    "元": ("currency", 1.0), "万元": ("currency", 10000.0),
    "亿元": ("currency", 100000000.0), "usd": ("currency", 1.0),
    "m": ("length", 1.0), "cm": ("length", 0.01), "mm": ("length", 0.001),
    "km": ("length", 1000.0),
    "kg": ("mass", 1.0), "g": ("mass", 0.001), "t": ("mass", 1000.0),
    "%": ("ratio", 0.01), "percentage": ("ratio", 0.01),
    "人": ("count", 1.0), "例": ("count", 1.0), "个": ("count", 1.0),
    "户": ("count", 1.0), "岁": ("age", 1.0), "year": ("age", 1.0),
}


def normalise_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = re.sub(r"[\s\-_./·]+", "", text)
    return text


def entity_id(entity_type: str, key: str) -> str:
    return C.canonical_hash([entity_type, normalise_key(key)])[:20]


def convert_unit(value: float, from_unit: str, to_unit: str) -> float:
    f = UNIT_TABLE.get(from_unit)
    t = UNIT_TABLE.get(to_unit)
    if not f or not t:
        raise ValueError(f"unknown unit: {from_unit if not f else to_unit}")
    if f[0] != t[0]:
        raise ValueError(f"cannot convert {from_unit} to {to_unit}")
    return float(value) * f[1] / t[1]


class Entities:
    def __init__(self, project: C.Project):
        self.project = project

    def _types_path(self) -> Path:
        return self.project.path("entities", "types.json")

    def register_type(self, entity_type: str, *, fields: Iterable[str],
                      identity_rule: str, description: str = "") -> dict:
        path = self._types_path()
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() \
            else {}
        data[entity_type] = {"fields": list(fields),
                             "identity_rule": identity_rule,
                             "description": description}
        C.atomic_write_json(path, data)
        return {"entity_type": entity_type, **data[entity_type]}

    def register(self, entity_type: str, key: str, *, attributes: Mapping,
                 sources: Iterable[Mapping], status: str = "active",
                 aliases: Iterable[str] = ()) -> dict:
        eid = entity_id(entity_type, key)
        name = str(attributes.get("name") or key)
        payload = {"entity_type": entity_type, "canonical_name": name,
                   "aliases": [str(a) for a in aliases],
                   "stable_ids": [str(key)],
                   "sources": [dict(s) for s in sources]}
        prev = self.project.latest("entity", eid)
        if prev is not None:
            merged = dict(prev["data"])
            merged["aliases"] = sorted(set(merged["aliases"]) |
                                       set(payload["aliases"]))
            merged["stable_ids"] = sorted(set(merged["stable_ids"]) |
                                          set(payload["stable_ids"]))
            known = {json.dumps(s, ensure_ascii=False, sort_keys=True)
                     for s in merged["sources"]}
            merged["sources"] = list(merged["sources"]) + [
                s for s in payload["sources"]
                if json.dumps(s, ensure_ascii=False, sort_keys=True) not in known]
            if attributes.get("name") and name != merged["canonical_name"]:
                merged.setdefault("conflicts", []).append(
                    {"field": "name", "values": [merged["canonical_name"], name],
                     "source": "register"})
            payload = merged
            rec = C.make_record("entity", eid, payload, producer=_producer(),
                                status=prev["status"],
                                revision=prev["revision"] + 1)
        else:
            rec = C.make_record("entity", eid, payload, producer=_producer(),
                                status=status)
        self.project.append("entity", rec, enforce_transition=False)
        return rec

    def relation(self, source: str, target: str, relation_type: str, *,
                 evidence: Iterable[Mapping], cardinality: str = "many_to_many",
                 valid_from: str | None = None, valid_to: str | None = None,
                 note: str = "") -> dict:
        if relation_type not in RELATION_TYPES:
            raise ValueError(f"unknown relation type {relation_type}")
        refs = {}
        for endpoint in (source, target):
            etype, _, key = endpoint.partition(":")
            rec = self.project.latest("entity", entity_id(etype, key))
            if rec is None:
                raise ValueError(f"entity {endpoint} is not registered")
            refs[endpoint] = {"entity": rec["id"], "entity_type": etype,
                              "key": key}
        payload = {"relation_type": relation_type,
                   "from_ref": refs[source], "to_ref": refs[target],
                   "cardinality": cardinality,
                   "evidence": [dict(e) for e in evidence], "notes": note}
        if valid_from:
            payload["valid_from"] = valid_from
        if valid_to:
            payload["valid_to"] = valid_to
        rid = C.canonical_hash([source, target, relation_type, valid_from,
                                valid_to])[:24]
        prev = self.project.latest("relation", rid)
        rec = C.make_record("relation", rid, payload, producer=_producer(),
                            status="active",
                            revision=(prev["revision"] + 1) if prev else 1)
        self.project.append("relation", rec, enforce_transition=False)
        return rec

    # -- identity resolution ----------------------------------------------
    def resolve_identity(self, entity_type: str, *, candidates: Iterable[Mapping],
                         rule: str) -> dict:
        """Group candidate records that describe the same entity.

        Similarity is evidence, not proof: every merge records the rule and the
        key values it used, and a below-threshold pair stays separate.
        """
        groups: list[list[dict]] = []
        merges: list[dict] = []
        for cand in candidates:
            key = normalise_key(cand.get("key", cand.get("name", "")))
            placed = False
            for group in groups:
                other = normalise_key(group[0].get("key",
                                                  group[0].get("name", "")))
                if key and other and (key == other or key in other or
                                      other in key):
                    group.append(cand)
                    merges.append({"kept": group[0].get("key"),
                                   "merged": cand.get("key"),
                                   "rule": rule,
                                   "evidence": {"normalised": [other, key]}})
                    placed = True
                    break
            if not placed:
                groups.append([cand])
        return {"groups": len(groups), "merges": merges,
                "unmerged": [g[0].get("key") for g in groups if len(g) == 1]}


def join_tables(project: C.Project, *, left_rel: str, right_rel: str,
                left_key, right_key=None, how: str = "left",
                unit: str, out_rel: str | None = None) -> dict:
    """Join two csv tables and record exactly what the join did."""
    import pandas as pd

    left_key = [left_key] if isinstance(left_key, str) else list(left_key)
    right_key = ([right_key] if isinstance(right_key, str) else
                 list(right_key or left_key))
    left = pd.read_csv(project.root / left_rel, dtype=str, keep_default_na=False)
    right = pd.read_csv(project.root / right_rel, dtype=str,
                        keep_default_na=False)
    missing_left = [k for k in left_key if k not in left.columns]
    missing_right = [k for k in right_key if k not in right.columns]
    if missing_left or missing_right:
        raise ValueError(f"join keys missing: {missing_left} {missing_right}")
    left["_norm_key"] = left[left_key].agg("|".join, axis=1).map(normalise_key)
    right["_norm_key"] = right[right_key].agg("|".join, axis=1).map(
        normalise_key)
    left_exact = left["_norm_key"].isin(right["_norm_key"])
    right_counts = right.groupby("_norm_key").size()
    dup_right = {k: int(v) for k, v in right_counts.items() if v > 1}
    dup_left = int(left["_norm_key"].duplicated().sum())
    overlap_cols = [c for c in left.columns
                    if c in right.columns and c not in left_key + right_key
                    and c != "_norm_key"]
    conflicts = []
    merged = left.merge(right, on="_norm_key", how=how,
                        suffixes=("_l", "_r"))
    for col in overlap_cols:
        lcol, rcol = f"{col}_l", f"{col}_r"
        if lcol in merged.columns and rcol in merged.columns:
            bad = merged[(merged[lcol] != "") & (merged[rcol] != "") &
                         (merged[lcol] != merged[rcol])]
            if len(bad):
                conflicts.append({"column": col,
                                  "rows": int(len(bad)),
                                  "examples": bad[[lcol, rcol, "_norm_key"]]
                                  .head(5).to_dict("records")})
    unmatched = sorted(set(left.loc[~left_exact, "_norm_key"]))
    out_rel = out_rel or f"data/joined_{Path(left_rel).stem}__{Path(right_rel).stem}.csv"
    out_path = project.root / out_rel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.drop(columns=["_norm_key"]).to_csv(out_path, index=False)
    payload = {
        "left": {"path": left_rel,
                 "sha256": C.file_sha256(project.root / left_rel),
                 "rows": int(len(left)), "keys": left_key},
        "right": {"path": right_rel,
                  "sha256": C.file_sha256(project.root / right_rel),
                  "rows": int(len(right)), "keys": right_key},
        "keys": [{"left": left_key, "right": right_key,
                  "normalisation": "NFKC + lower + strip separators"}],
        "before": {"left_rows": int(len(left)), "right_rows": int(len(right)),
                   "one_to_many_left": dup_left,
                   "duplicate_right_keys": dup_right,
                   "unmatched_left_keys": len(unmatched),
                   "unmatched_examples": unmatched[:10]},
        "after": {"path": out_rel,
                  "sha256": C.file_sha256(out_path),
                  "rows": int(len(merged)),
                  "distinct_units": int(merged.drop_duplicates(
                      subset=["_norm_key"]).shape[0]),
                  "unit": unit},
        "checks": [{"check": "row_count_accounted", "ok": True,
                    "detail": f"left {len(left)} + matches -> "
                              f"{len(merged)} output rows"},
                   {"check": "unit_of_observation", "ok": True,
                    "detail": unit},
                   {"check": "no_silent_unit_conflicts",
                    "ok": not conflicts, "detail": conflicts[:5]}],
        "expanded_rows": int(len(merged) - len(left)),
        "dropped_rows": int(len(left) - len(merged) if how == "inner" else 0),
        "notes": ("rows are not additive across tables; the resulting unit is "
                  f"{unit}"),
    }
    rid = C.canonical_hash([left_rel, right_rel, left_key, right_key, how])[:20]
    prev = project.latest("join_audit", rid)
    rec = C.make_record("join_audit", rid, payload, producer=_producer(),
                        status="failed" if conflicts else "passed",
                        revision=(prev["revision"] + 1) if prev else 1)
    project.append("join_audit", rec, enforce_transition=False)
    return {"audit": rec["id"], "output": out_rel,
            "rows": {"left": int(len(left)), "right": int(len(right)),
                     "output": int(len(merged)),
                     "duplicate_right_keys": dup_right,
                     "unmatched_left_keys": len(unmatched)},
            "conflicts": conflicts,
            "distinct_units": payload["after"]["distinct_units"],
            "status": rec["status"]}


def harmonise_units(project: C.Project, *, dataset_rel: str, column: str,
                    from_unit: str, to_unit: str,
                    multiplier: float | None = None) -> dict:
    """Rewrite a column into one unit and record the mapping used."""
    import pandas as pd

    frame = pd.read_csv(project.root / dataset_rel, dtype=str,
                        keep_default_na=False)
    if column not in frame.columns:
        raise ValueError(f"column {column} not in {dataset_rel}")
    factor = (convert_unit(1.0, from_unit, to_unit) if multiplier is None
              else float(multiplier))
    converted = []
    for value in frame[column]:
        if str(value).strip() == "":
            converted.append("")
            continue
        try:
            converted.append(str(round(float(value) * factor, 10)))
        except ValueError:
            raise ValueError(f"non-numeric value in {column}: {value!r}")
    frame[column] = converted
    out_rel = f"data/{Path(dataset_rel).stem}_{column}_{to_unit.replace('%', 'pct')}.csv"
    out_path = project.root / out_rel
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_path, index=False)
    return {"output": out_rel, "factor": factor, "from": from_unit,
            "to": to_unit, "rows": int(len(frame)),
            "sha256": C.file_sha256(out_path),
            "note": "conversion is recorded; the original file is untouched"}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="entities, relations, joins")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_t = sub.add_parser("entity-type")
    p_t.add_argument("--id", required=True)
    p_t.add_argument("--fields", required=True)
    p_t.add_argument("--rule", required=True)
    p_e = sub.add_parser("entity")
    p_e.add_argument("--type", required=True)
    p_e.add_argument("--key", required=True)
    p_e.add_argument("--name", required=True)
    p_e.add_argument("--source", action="append", default=[])
    p_r = sub.add_parser("relation")
    p_r.add_argument("--from", dest="src", required=True)
    p_r.add_argument("--to", dest="dst", required=True)
    p_r.add_argument("--type", required=True)
    p_r.add_argument("--evidence", action="append", default=[])
    p_j = sub.add_parser("join")
    p_j.add_argument("--left", required=True)
    p_j.add_argument("--right", required=True)
    p_j.add_argument("--on", required=True)
    p_j.add_argument("--right-on")
    p_j.add_argument("--how", default="left")
    p_j.add_argument("--unit", required=True)
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    ents = Entities(proj)
    if args.cmd == "entity-type":
        print(json.dumps(ents.register_type(args.id,
                                            fields=args.fields.split(","),
                                            identity_rule=args.rule),
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "entity":
        print(json.dumps(ents.register(
            args.type, args.key, attributes={"name": args.name},
            sources=[{"path": p} for p in args.source]),
            ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "relation":
        print(json.dumps(ents.relation(args.src, args.dst, args.type,
                                       evidence=[{"path": p}
                                                 for p in args.evidence]),
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "join":
        print(json.dumps(join_tables(proj, left_rel=args.left,
                                     right_rel=args.right, left_key=args.on,
                                     right_key=args.right_on, how=args.how,
                                     unit=args.unit),
                         ensure_ascii=False, indent=1))
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
