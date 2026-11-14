# -*- coding: utf-8 -*-
"""Rebuildable, version-bound full-text/structure index and executed searches.

Two rules make the search receipts trustworthy:

1. **An index knows what it was built from.**  Every entry carries the source
   path, the source SHA256 and the unit locator.  ``stale()`` re-hashes the
   sources; a stale index may not be used to answer "it is not in the material".
2. **A hit is a candidate, not a value.**  ``search`` records the query, the
   index version, the actual matched unit and its context, and returns
   references; the value still has to be opened at that locator.

A ``search_run`` is only ``executed`` if a search really ran.  ``require_executed``
is what the gap ledger and the release gate use to reject hand-written "I looked
everywhere" rows.

CLI::

    python search_index.py --root . build
    python search_index.py --root . search --query "treatment" [--limit 20]
    python search_index.py --root . status
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C
import source_units as SU


def _producer(**kw) -> dict:
    return C.producer_for("search_index", version="2.0", module_file=__file__,
                          **kw)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _rel_root(project_root: Path, root: Path) -> str:
    try:
        return root.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return root.as_posix()


class SearchIndex:
    def __init__(self, project: C.Project, units: SU.SourceUnits):
        self.project = project
        self.units = units
        self.root = Path(getattr(units, "root", project.root)).resolve()
        self.materials_root: Path | None = None
        self.path = project.path("index", "index.json")

    # -- build -------------------------------------------------------------
    def _entries(self) -> list[dict]:
        entries: list[dict] = []
        current: dict[str, str] = {}
        for unit in self.units.units():
            rep = unit["data"].get("representation")
            if not rep:
                continue
            path = self.units.representation_path(unit)
            if path.suffix.lower() not in (".txt",".md",".json",".jsonl",".csv",".tsv",".xml",".html",""):
                continue
            source = unit["data"]["source"]
            if source not in current:
                original = Path(self.materials_root or getattr(self.units, "materials_root", self.root)) / source
                current[source] = (C.file_sha256(original)
                                   if original.is_file() else "")
            if unit["data"]["source_sha256"] != current[source]:
                # the unit was recovered from an older version of the source;
                # index only representations that still describe the file
                continue
            text = path.read_text(encoding="utf-8-sig")
            if not text.strip():
                continue
            entries.append({
                "unit": unit["id"],
                "source": source,
                "source_sha256": unit["data"]["source_sha256"],
                "locator": unit["data"]["locator"],
                "text": text,
                "norm": _norm(text),
            })
        return entries

    def build(self, materials_root=None) -> dict:
        if materials_root is not None:
            self.materials_root = Path(materials_root).resolve()
        elif self.materials_root is None:
            known = getattr(self.units, "materials_root", None)
            if known is not None:
                self.materials_root = Path(known).resolve()
            else:
                prev = self.latest_record()
                if prev is not None and prev["data"].get("root"):
                    self.materials_root = self._root_for(prev)
        root = Path(self.materials_root or self.root).resolve()
        entries = self._entries()
        sources = sorted({(e["source"], e["source_sha256"]) for e in entries})
        payload = {"sources": [{"source": s, "sha256": h} for s, h in sources],
                   "built_at": C._now(), "entry_count": len(entries),
                   "root": _rel_root(self.project.root, root),
                   "inventory": [{"source": p.relative_to(root).as_posix(), "sha256": C.file_sha256(p)}
                                 for p in sorted(root.rglob("*")) if p.is_file()],
                   "path": self.path.relative_to(self.project.root).as_posix()}
        C.atomic_write_json(self.path, {"entries": entries, "meta": payload})
        payload["index_sha256"] = C.file_sha256(self.path)
        # a stable id: rebuilding the same index is a revision, not a new object
        rid = "index-" + C.canonical_hash(["search_index",
                                           payload["path"]])[:16]
        rec = C.make_record("search_index", rid, payload,
                            producer=_producer(), status="current")
        prev = self.project.latest("search_index", rec["id"])
        if prev is not None:
            rec = C.make_record("search_index", rec["id"], payload,
                                producer=_producer(), status="current",
                                revision=prev["revision"] + 1)
        self.project.append("search_index", rec, enforce_transition=False)
        return {"record": rec["id"], "entries": len(entries),
                "sources": len(sources)}

    def load(self) -> dict:
        if not self.path.is_file():
            raise SystemExit("no index built yet; run `search_index.py build`")
        rec = self.latest_record()
        if not rec or rec["data"].get("index_sha256") != C.file_sha256(self.path):
            raise ValueError("unbound or changed search index; rebuild it")
        return json.loads(self.path.read_text(encoding="utf-8"))

    def latest_record(self) -> dict | None:
        return self.project.latest("search_index")

    # -- staleness ---------------------------------------------------------
    def _root_for(self, rec: Mapping) -> Path:
        root = rec["data"].get("root")
        if not root:
            return self.root
        path = Path(root)
        return path if path.is_absolute() else self.project.root / path

    def stale(self) -> dict:
        rec = self.latest_record()
        if rec is None:
            return {"stale": True, "reason": "no index record"}
        base = self._root_for(rec)
        changed, missing = [], []
        current_inventory = {p.relative_to(base).as_posix(): C.file_sha256(p)
                             for p in base.rglob("*") if p.is_file()}
        expected_inventory = {s["source"]: s["sha256"]
                              for s in rec["data"].get("inventory", rec["data"]["sources"])}
        for src in rec["data"]["sources"]:
            path = base / src["source"]
            if not path.is_file():
                missing.append(src["source"])
                continue
            if C.file_sha256(path) != src["sha256"]:
                changed.append(src["source"])
        added = sorted(set(current_inventory) - set(expected_inventory))
        changed += [s for s,h in expected_inventory.items() if s in current_inventory and current_inventory[s] != h and s not in changed]
        missing += [s for s in expected_inventory if s not in current_inventory and s not in missing]
        # Original-file hashes alone do not bind regenerated or corrected OCR,
        # recovered tables, or tampered intermediate representations.
        try:
            if self._entries()!=self.load()["entries"]:changed.append("<source-unit representations>")
        except (OSError,ValueError,C.ContractError,SystemExit):changed.append("<source-unit representations>")
        return {"stale": bool(changed or missing or added), "changed": changed, "added": added,
                "missing": missing, "built_at": rec["data"]["built_at"]}

    # -- search ------------------------------------------------------------
    def search(self, query: str, *, limit: int = 50, rebuild: bool = False,
               gap_ids: Iterable[str] = (), mode: str = "contains",
               sources: list[str] | None = None) -> dict:
        state = self.stale()
        if state["stale"] and rebuild:
            if self.materials_root is not None:
                self.units.build(self.materials_root)
            self.build()
            state = self.stale()
        if state["stale"]:
            raise SystemExit(
                f"index is stale ({state}); rebuild before searching - a stale "
                f"index cannot support 'not found'")
        index = self.load()
        if not query.strip() or mode not in ("contains", "regex") or limit < 0:
            raise ValueError("search needs a nonempty query, supported mode and nonnegative display limit")
        pattern = (re.compile(query, re.I) if mode == "regex"
                   else None)
        needle = _norm(query)
        hits = []
        for entry in index["entries"]:
            if sources and entry["source"] not in sources:
                continue
            haystack = entry["norm"]
            if pattern is not None:
                m = pattern.search(entry["text"])
                if not m:
                    continue
                start = max(0, m.start() - 80)
                snippet = entry["text"][start:m.end() + 120]
                score = 1.0
            else:
                pos = haystack.find(needle)
                if pos < 0:
                    continue
                score = 1.0
                snippet = entry["text"][max(0, pos - 80):pos + len(query) + 120]
            hits.append({"unit": entry["unit"], "source": entry["source"],
                         "locator": entry["locator"], "snippet": snippet,
                         "score": score})
            # limit controls displayed hits; every eligible entry is scanned.
        selected = {e["source"] for e in index["entries"] if not sources or e["source"] in sources}
        covered_sources = [s for s in index["meta"]["sources"] if s["source"] in selected]
        payload = {"goal": {"description": f"search for {query!r}"},
                   "query": {"q": query, "mode": mode, "limit": limit,
                             "sources": sources},
                   "sources": covered_sources,
                   "scan_complete": True, "materials_root": index["meta"]["root"],
                   "inventory": index["meta"].get("inventory", index["meta"]["sources"]),
                   "scanned_units": [e["unit"] for e in index["entries"] if e["source"] in selected],
                   "hits": hits, "executed": True,
                   "index": {"built_at": index["meta"]["built_at"],
                             "entry_count": index["meta"]["entry_count"]},
                   "gap_ids": list(gap_ids)}
        rid = C.canonical_hash([payload["query"], payload["index"],
                                [h["unit"] for h in hits],
                                payload["sources"]])[:20]
        rec = C.make_record("search_run", rid, payload, producer=_producer(),
                            status="executed")
        prev = self.project.latest("search_run", rid)
        if prev is None:
            self.project.append("search_run", rec)
        return {"run": rec["id"], "hits": len(hits), "query": query,
                "top": hits[:limit] if limit else hits}


def require_executed(project: C.Project, run_id: str) -> dict:
    rec = project.latest("search_run", run_id)
    if rec is None:
        raise ValueError(f"search run {run_id} does not exist")
    if not rec["data"].get("executed") or rec["status"] != "executed":
        raise ValueError(f"search run {run_id} was never executed")
    data = rec["data"]
    if not data.get("scan_complete") or "materials_root" not in data:
        raise ValueError("legacy/unbounded search receipt cannot prove current coverage; rerun the search")
    base = Path(data["materials_root"])
    base = base if base.is_absolute() else project.root / base
    inventory = {p.relative_to(base).as_posix(): C.file_sha256(p) for p in base.rglob("*") if p.is_file()}
    if inventory != {s["source"]: s["sha256"] for s in data["inventory"]}:
        raise ValueError("materials changed or were added after this search; search again")
    return rec


def searches_cover(project: C.Project, run_ids: Iterable[str],
                   inventory: Iterable[Mapping]) -> dict:
    """Do the executed searches cover every source in the inventory?"""
    runs = [require_executed(project, r) for r in run_ids]
    seen: dict[str, set[str]] = {}
    for run in runs:
        for src in run["data"]["sources"]:
            seen.setdefault(src["source"], set()).add(src["sha256"])
    missing = []
    hash_mismatch = []
    for item in inventory:
        source = item["source"]
        sha = item.get("sha256")
        if source not in seen:
            missing.append(source)
        elif sha and sha not in seen[source]:
            hash_mismatch.append(source)
    return {"complete": not missing and not hash_mismatch,
            "searched_sources": sorted(seen), "missing": missing,
            "hash_mismatch": hash_mismatch, "runs": len(runs)}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="searchable unit index")
    ap.add_argument("--root", default=".")
    ap.add_argument("--materials", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    p_s = sub.add_parser("search")
    p_s.add_argument("--query", required=True)
    p_s.add_argument("--limit", type=int, default=20)
    p_s.add_argument("--mode", default="contains",
                     choices=["contains", "regex"])
    p_s.add_argument("--rebuild", action="store_true")
    sub.add_parser("status")
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    units = SU.SourceUnits(proj, root=args.materials or Path(args.root))
    index = SearchIndex(proj, units)
    if args.cmd == "build":
        print(json.dumps(index.build(), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "search":
        res = index.search(args.query, limit=args.limit, rebuild=args.rebuild,
                           mode=args.mode)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "status":
        print(json.dumps(index.stale(), ensure_ascii=False, indent=1))
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
