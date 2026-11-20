#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic output-layout conformance check for any research project.

The viewer sidebar and downstream consumers need a *stable* face across runs:
physical first-level directories under ``output/`` drift with the mode and the
agent's script choices (``analysis_pack`` vs ``models`` vs ``stats``,
``chart_pack`` vs ``figures`` ...).  This script owns the closed canonical
skeleton: every known physical alias folds into one canonical group, and any
directory outside the known aliases must be declared in the project registry's
``layout`` map (``{"<canonical>": ["<physical dir>", ...]}``) or it is a stray.

It also enforces full display-name coverage for deliverable tables/documents:
every CSV/MD under the tables group and every MD/DOCX/PDF under the docs group
(or at the output root, except the manuscript itself) must have a titled entry
in ``table_map.json`` / ``doc_map.json`` (or, for manuscript-cited tables, in
``manuscript.json``).  Untitled deliverables fall back to English filenames in
the viewer, which is exactly what the naming contract forbids.  Known alias
directories cannot be rehung to another group via ``layout`` (that would dodge
coverage); deliverable tables/documents belong in the tables/docs groups, not
in groups whose files are not coverage-checked.

The resolved grouping is written to ``output/qa/layout_conformance.json`` so
read-only consumers (the workspace viewer) can render canonical groups without
embedding any alias knowledge of their own.

Exit codes: 0 = conformant; 2 = stray undeclared directory, invalid layout
declaration, missing output root, or untitled deliverable table/document.
Empty directories and unreadable optional name maps are warnings, not errors.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# 闭合规范骨架：canonical key -> (viewer label, known physical aliases).
# Aliases are historical script defaults; they fold into the canonical group
# without any registry declaration.  New/custom directories need registry.layout.
CANONICAL = {
    "output/audit": ("审计", ["output/audit"]),
    "output/coding": ("编码", ["output/coding", "output/kappa"]),
    "output/dataset": ("数据", ["output/dataset", "output/cleaning",
                               "output/datasets", "output/data_verification"]),
    "output/stats": ("统计", ["output/stats", "output/models", "output/methods",
                             "output/analysis_pack"]),
    "output/figures": ("图", ["output/figures", "output/chart_pack",
                             "output/paper_figs"]),
    "output/tables": ("表", ["output/tables", "output/reports"]),
    "output/docs": ("文档", ["output/docs", "output/review"]),
    "output/qa": ("质检", ["output/qa"]),
    "output/verify": ("溯源", ["output/verify"]),
    "output/ledger": ("台账", ["output/gates", "output/v2", "output/recheck",
                              "output/claims"]),
    "output/mining": ("挖掘", ["output/mining"]),
}

TABLE_EXTS = {".csv", ".tsv", ".md"}
DOC_EXTS = {".md", ".docx", ".pdf"}
SCAN_CAP = 10000


def _norm(rel: str) -> str:
    return os.path.normpath(str(rel)).replace("\\", "/")


def _rel_key(raw: str, root: str) -> str:
    """Map entries may carry absolute paths (figure_map convention); fold to root-rel."""
    rel = os.path.relpath(raw, root) if os.path.isabs(raw) else raw
    return _norm(rel)


def _safe_rel(value: str) -> bool:
    rel = _norm(value)
    return bool(rel) and not rel.startswith("..") and not os.path.isabs(rel)


def _alias_owner() -> dict:
    owner = {}
    for key, (_label, aliases) in CANONICAL.items():
        for alias in aliases:
            owner[alias] = key
    return owner


def load_layout(registry_path: str) -> dict:
    """registry.layout: canonical -> physical dir(s).  Missing registry = {}."""
    if not os.path.isfile(registry_path):
        return {}
    with open(registry_path, encoding="utf-8-sig") as fh:
        spec = json.load(fh)
    layout = spec.get("layout") if isinstance(spec, dict) else None
    if layout is None:
        return {}
    if not isinstance(layout, dict):
        raise ValueError("registry 'layout' must map canonical keys to physical dirs")
    return layout


def _titled_files(path: str, wrapper: str, file_keys: tuple, root: str) -> dict:
    """rel(normalized) -> title for entries with a non-empty title."""
    titles = {}
    if not os.path.isfile(path):
        return titles
    with open(path, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    items = data if isinstance(data, list) else (data.get(wrapper) if isinstance(data, dict) else None)
    if not isinstance(items, list):
        raise ValueError(f"{os.path.basename(path)}: expected a list of titled entries")
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        raw = ""
        for k in file_keys:
            raw = str(it.get(k) or "").strip()
            if raw:
                break
        if title and raw:
            titles[_rel_key(raw, root)] = title
    return titles


def _manuscript_titles(spec_path: str, root: str) -> tuple:
    """(table csv rel -> caption, has_title_block)."""
    tables = {}
    has_title = False
    if not os.path.isfile(spec_path):
        return tables, has_title
    with open(spec_path, encoding="utf-8-sig") as fh:
        spec = json.load(fh)
    blocks = spec.get("blocks") if isinstance(spec, dict) else None
    if not isinstance(blocks, list):
        return tables, has_title
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "title" and str(b.get("text") or "").strip():
            has_title = True
        if b.get("type") == "table" and str(b.get("caption") or "").strip():
            raw = str(b.get("csv") or "").strip()
            if raw:
                tables[_rel_key(raw, root)] = str(b["caption"]).strip()
    return tables, has_title


def _walk_files(root: str, rel_dir: str) -> list:
    out = []
    base = os.path.join(root, rel_dir)
    stack = [base]
    while stack and len(out) < SCAN_CAP:
        current = stack.pop()
        try:
            items = os.listdir(current)
        except OSError:
            continue
        for name in sorted(items):
            if name.startswith("."):
                continue
            abs_path = os.path.join(current, name)
            if os.path.islink(abs_path):
                continue
            if os.path.isdir(abs_path):
                stack.append(abs_path)
            elif os.path.isfile(abs_path):
                out.append(_norm(os.path.relpath(abs_path, root)))
                if len(out) >= SCAN_CAP:
                    break
    return out


def check(root: str, registry: str, table_map: str, doc_map: str,
          manuscript_spec: str) -> dict:
    result = {"root": root, "errors": [], "warnings": [], "groups": [], "stray": []}
    out_root = os.path.join(root, "output")
    if not os.path.isdir(out_root):
        result["errors"].append("output/ directory missing; nothing to conform")
        result["error_count"] = len(result["errors"])
        result["warning_count"] = len(result["warnings"])
        return result

    try:
        layout = load_layout(registry)
    except (OSError, ValueError) as exc:
        result["errors"].append(f"registry layout unreadable: {type(exc).__name__}: {exc}"[:200])
        layout = {}

    owner = _alias_owner()
    declared = {}
    for key, value in layout.items():
        if key not in CANONICAL:
            result["errors"].append(f"layout key {key!r} is not a canonical group")
            continue
        dirs = value if isinstance(value, list) else [value]
        for d in dirs:
            if not isinstance(d, str) or not _safe_rel(d):
                result["errors"].append(f"layout dir {d!r} must be a project-relative path")
                continue
            rel = _norm(d)
            # layout 只接受一级 output 目录：嵌套声明对一级归组无意义，徒增混淆
            if not rel.startswith("output/") or rel.count("/") != 1:
                result["errors"].append(f"layout dir {rel} must be a first-level output directory")
                continue
            # 已知别名不得改挂其他组：否则把表组目录挂去不核覆盖的组即可逃避命名契约
            if rel in owner and owner[rel] != key:
                result["errors"].append(
                    f"alias directory {rel} belongs to {owner[rel]}; layout cannot rehang it to {key}")
                continue
            if rel in declared and declared[rel] != key:
                result["errors"].append(f"directory {rel} declared under two groups: {declared[rel]} and {key}")
                continue
            declared[rel] = key

    physical = []
    for name in sorted(os.listdir(out_root)):
        if name.startswith("."):
            continue
        abs_path = os.path.join(out_root, name)
        if os.path.islink(abs_path) or not os.path.isdir(abs_path):
            continue
        physical.append(f"output/{name}")

    all_files = _walk_files(root, "output")
    if len(all_files) >= SCAN_CAP:
        result["warnings"].append(f"scan cap {SCAN_CAP} reached; naming coverage may be incomplete")
    groups = {key: [] for key in CANONICAL}
    for rel in physical:
        key = declared.get(rel) or owner.get(rel)
        if not key:
            result["stray"].append(rel)
            result["errors"].append(
                f"undeclared directory {rel}; fold it into a canonical group via registry layout")
            continue
        groups[key].append(rel)
        if not any(f.startswith(rel + "/") for f in all_files):
            result["warnings"].append(f"empty directory {rel}")

    for key, (label, _aliases) in CANONICAL.items():
        if groups[key]:
            result["groups"].append({"key": key, "label": label, "dirs": groups[key]})

    # 命名覆盖：表组与文档组的交付件必须都有中文标题来源
    try:
        table_titles = _titled_files(table_map, "tables", ("file", "csv"), root)
    except (OSError, ValueError) as exc:
        result["warnings"].append(f"table_map unreadable: {type(exc).__name__}: {exc}"[:200])
        table_titles = {}
    try:
        doc_titles = _titled_files(doc_map, "docs", ("file",), root)
    except (OSError, ValueError) as exc:
        result["warnings"].append(f"doc_map unreadable: {type(exc).__name__}: {exc}"[:200])
        doc_titles = {}
    try:
        ms_tables, _has_title = _manuscript_titles(manuscript_spec, root)
    except (OSError, ValueError) as exc:
        result["warnings"].append(f"manuscript spec unreadable: {type(exc).__name__}: {exc}"[:200])
        ms_tables = {}

    def covered(rel: str, ext: str) -> bool:
        if ext in {".csv", ".tsv"}:
            return rel in table_titles or rel in ms_tables
        return rel in doc_titles or rel in table_titles

    for group in result["groups"]:
        exts = TABLE_EXTS if group["key"] == "output/tables" else (
            DOC_EXTS if group["key"] == "output/docs" else set())
        if not exts:
            continue
        for rel_dir in group["dirs"]:
            for rel in all_files:
                if not rel.startswith(rel_dir + "/"):
                    continue
                ext = os.path.splitext(rel)[1].lower()
                if ext in exts and not covered(rel, ext):
                    result["errors"].append(f"untitled deliverable {rel}; add a titled entry to table_map/doc_map")

    for rel in all_files:
        if "/" in rel[len("output/"):]:
            continue
        ext = os.path.splitext(rel)[1].lower()
        base = os.path.basename(rel)
        if ext not in DOC_EXTS or base in {"manuscript.docx", "manuscript.pdf"}:
            continue
        if not covered(rel, ext):
            result["errors"].append(f"untitled deliverable {rel}; add a titled entry to doc_map")

    result["error_count"] = len(result["errors"])
    result["warning_count"] = len(result["warnings"])
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument("--root", default=".", help="project root (contains output/ and research_registry.json)")
    ap.add_argument("--registry", default=None, help="registry JSON (default <root>/research_registry.json)")
    ap.add_argument("--table-map", default=None, help="table_map.json (default <root>/output/table_map.json)")
    ap.add_argument("--doc-map", default=None, help="doc_map.json (default <root>/output/doc_map.json)")
    ap.add_argument("--manuscript-spec", default=None, help="manuscript.json (default <root>/manuscript.json)")
    ap.add_argument("--out", default=None, help="write layout report here (default <root>/output/qa/layout_conformance.json)")
    ap.add_argument("--exit-zero", action="store_true", help="always exit 0 (do not use in CI)")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    registry = args.registry or os.path.join(root, "research_registry.json")
    table_map = args.table_map or os.path.join(root, "output", "table_map.json")
    doc_map = args.doc_map or os.path.join(root, "output", "doc_map.json")
    spec = args.manuscript_spec or os.path.join(root, "manuscript.json")
    try:
        result = check(root, registry, table_map, doc_map, spec)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    out = args.out or os.path.join(root, "output", "qa", "layout_conformance.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    result["out"] = out
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["error_count"] and not args.exit_zero:
        print(f"LAYOUT FAILED: {result['error_count']} error(s), {result['warning_count']} warning(s)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())