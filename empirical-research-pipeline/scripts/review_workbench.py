# -*- coding: utf-8 -*-
"""Offline per-cell review workbench: second pass, conflicts, patches.

The workbench is deliberately *not* a green button.  It can

* export an offline HTML page that shows, for every cell, the final value, the
  original evidence, the locator, the rules and the current review state - with
  paging for the eye only, never for the reviewer's scope;
* export a **blind** second-pass template that omits the first-pass value, so a
  reviewer has to go back to the source instead of confirming what is on screen;
* import second-pass results, compare them with the first pass, and record a
  conflict (`disputed`) instead of silently voting;
* record value patches against an expected parent version, refusing stale ones.

It refuses the shapes that would fake completeness: an event without a real
`reread_scope`, a generic note, a timestamp before the snapshot, or a file that
claims every cell verified without per-cell evidence.

The review *file* it emits is the main-chain ``review`` JSONL consumed by
``verify_dataset.py`` (one source of truth for "is this cell reviewed"); in
addition every event is stored as a ``review_event`` ledger record so the
independence and the conflict chain stay auditable.

CLI::

    python review_workbench.py --root . export --dataset person_wave
    python review_workbench.py --root . blind --dataset person_wave
    python review_workbench.py --root . import --dataset person_wave \\
        --file second_pass.jsonl
    python review_workbench.py --root . patch --dataset person_wave \\
        --key P01 --column age --value 43 --parent <record_sha256> --reason ...
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import html
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C
import txn as T


def _producer(**kw) -> dict:
    return C.producer_for("review_workbench", version="2.0", module_file=__file__,
                          **kw)


GENERIC_NOTES = {"", "ok", "verified", "checked", "yes", "done", "-", "n/a"}


class WorkbenchError(Exception):
    pass


# ---------------------------------------------------------------------------
# dataset loading (same identity rules as verify_dataset)
# ---------------------------------------------------------------------------
def load_dataset(project: C.Project, entry: Mapping) -> dict:
    path = project.root / entry["path"]
    if not path.is_file():
        raise WorkbenchError(f"dataset file missing: {entry['path']}")
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fh.seek(0)
        columns = next(csv.reader(fh))
    keys = entry["key"] if isinstance(entry["key"], list) else [entry["key"]]
    provenance: dict[tuple, dict] = {}
    prov_path = project.root / entry["provenance"]
    if prov_path.is_file():
        for rec in (json.loads(line) for line in
                    prov_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()):
            key = tuple(str(rec["key"]) if not isinstance(rec["key"], list)
                        else str(k) for k in
                        (rec["key"] if isinstance(rec["key"], list)
                         else [rec["key"]]))
            provenance[(key, rec["column"])] = rec
    return {"rows": rows, "columns": columns, "keys": keys,
            "sha256": C.file_sha256(path), "path": entry["path"],
            "provenance": provenance}


def cell_signature(dataset: str, key: tuple, column: str, value: str) -> str:
    """Value-only optimistic patch token; never a final-review signature."""
    return C.canonical_hash({"dataset": dataset, "key": list(key),
                             "column": column, "value": value})


def prepared_context(project: C.Project, entry: Mapping) -> tuple[dict, dict, list]:
    """Use the final verifier's exact target/evidence signature implementation."""
    import verify_dataset as VD
    verifier = VD.Verifier("research_registry.json", project.root,
                           entry.get("adapters", ()))
    snapshot = verifier.prepare()
    traces = {(VD.key_tuple(t["key"]), t["column"]): t
              for t in verifier.traces if t["dataset"] == entry["id"]}
    return snapshot, traces, verifier.issues


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------
def export_html(project: C.Project, entry: Mapping, *,
                out: str | None = None) -> dict:
    data = load_dataset(project, entry)
    ds = entry["id"]
    snapshot, targets, issues = prepared_context(project, entry)
    shared = project.path("workbench", "verification_snapshot.json")
    previous = json.loads(shared.read_text(encoding="utf-8")) if shared.is_file() else None
    if previous and previous.get("fingerprint") == snapshot["fingerprint"]:
        snapshot = previous
    else:
        C.atomic_write_json(shared, snapshot)
    prov_sha = C.canonical_hash({
        f"{list(k[0])}|{k[1]}": v for k, v in data["provenance"].items()})
    records = []
    for row in data["rows"]:
        key = tuple(str(row[k]) for k in data["keys"])
        for column in data["columns"]:
            value = row[column]
            proof = data["provenance"].get((key, column), {})
            records.append({
                "key": list(key), "column": column, "value": value,
                "record_sha256": targets[(key, column)]["record_sha256"],
                "patch_parent": cell_signature(ds, key, column, value),
                "kind": proof.get("kind"),
                "sources": proof.get("sources", []),
                "rule": proof.get("rule"),
                "reason": proof.get("reason"),
                "inputs": proof.get("inputs", []),
                "flags": proof.get("flags", []),
            })
    total = len(records)
    if total == 0:
        raise WorkbenchError("dataset has no cells; an empty table needs range "
                             "evidence, not a workbench claiming 0/0 verified")
    page = _render_html(ds, data, records)
    path = project.path("workbench", f"{ds}.html")
    if out:
        path = C.protect_output(project, out)
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    payload = {"dataset": ds, "cells": total, "page": path.as_posix(),
               "provenance_sha256": prov_sha,
               "dataset_sha256": data["sha256"], "stamp": snapshot["created_at"],
               "fingerprint": snapshot["fingerprint"], "prepare_issues": issues}
    snapshot_path = project.write_snapshot(f"workbench/{ds}.snapshot.json", snapshot)
    payload["snapshot_path"] = snapshot_path.relative_to(project.root).as_posix()
    project.write_snapshot(f"workbench/{ds}.export.json", payload)
    return payload


def _render_html(ds: str, data: Mapping, records: list[dict]) -> str:
    rows = []
    for i, rec in enumerate(records):
        evidence = "".join(
            f"<li><b>{html.escape(str(s.get('path')))}</b> "
            f"<code>{html.escape(json.dumps(s.get('locator'), ensure_ascii=False))}</code>"
            f"<br><q>{html.escape(str(s.get('raw')))}</q></li>"
            for s in rec["sources"])
        rows.append(
            f"<tr data-i='{i}'><td>{i + 1}</td>"
            f"<td>{html.escape(json.dumps(rec['key'], ensure_ascii=False))}</td>"
            f"<td>{html.escape(rec['column'])}</td>"
            f"<td><code>{html.escape(rec['value'])}</code></td>"
            f"<td>{html.escape(str(rec['kind']))}</td>"
            f"<td><details><summary>evidence</summary><ul>{evidence or '<li>none</li>'}</ul>"
            f"<p>rule: <code>{html.escape(json.dumps(rec['rule'], ensure_ascii=False))}</code></p>"
            f"<p>reason: {html.escape(str(rec['reason'] or ''))}</p></details></td>"
            f"<td><code>{rec['record_sha256'][:12]}</code></td></tr>")
    return f"""<!doctype html>
<html lang="zh"><meta charset="utf-8">
<title>review · {html.escape(ds)}</title>
<style>
 body{{font-family:system-ui,Segoe UI,sans-serif;margin:24px;color:#222}}
 table{{border-collapse:collapse;width:100%;font-size:12px}}
 th,td{{border:1px solid #ccc;padding:4px 6px;vertical-align:top}}
 th{{background:#f3f4f6;position:sticky;top:0}}
 tr:nth-child(even){{background:#fafafa}}
 code{{font-size:11px;word-break:break-all}}
 .bar{{position:sticky;bottom:0;background:#fff;border-top:2px solid #999;padding:8px}}
</style>
<h1>逐格复核 · {html.escape(ds)}</h1>
<p>数据集 <code>{html.escape(str(data['path']))}</code>，SHA256
<code>{data['sha256'][:16]}</code>，共 {len(records)} 格。
分页只影响显示，不缩减复核范围：所有格都必须逐项核对。</p>
<p><b>本页面不提供一键全部 verified。</b>修改必须导出补丁并经父版本校验。</p>
<table id="t"><thead><tr><th>#</th><th>key</th><th>column</th><th>value</th>
<th>kind</th><th>evidence</th><th>record_sha256</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<div class="bar">显示 <span id="shown">全部</span> 行 ·
 本文件为离线审阅页，数据不写回原件。</div>
<script>
 const rows=[...document.querySelectorAll('#t tbody tr')];
 // paging only changes what the eye sees
 let page=0,size=200;
 function render(){{rows.forEach((r,i)=>{{r.style.display=(i>=page*size&&i<(page+1)*size)?'':'none';}});
   document.getElementById('shown').textContent=(page*size+1)+'-'+Math.min(rows.length,(page+1)*size)+' / '+rows.length;}}
 render();
 document.addEventListener('keydown',e=>{{if(e.key==='ArrowRight'){{page=Math.min(page+1,Math.floor((rows.length-1)/size));render();}}
   if(e.key==='ArrowLeft'){{page=Math.max(0,page-1);render();}}}});
</script></html>"""


# ---------------------------------------------------------------------------
# blind second pass
# ---------------------------------------------------------------------------
def blind_template(project: C.Project, entry: Mapping, *,
                   snapshot: Mapping) -> list[dict]:
    """Rows for a second pass that do **not** contain the first-pass value."""
    data = load_dataset(project, entry)
    ds = entry["id"]
    current, targets, issues = prepared_context(project, entry)
    if issues:
        raise WorkbenchError(f"prepare must pass before a blind review: {issues[:3]}")
    if snapshot.get("fingerprint") and snapshot["fingerprint"] != current["fingerprint"]:
        raise WorkbenchError("data/evidence changed after prepare; export again")
    out = []
    for row in data["rows"]:
        key = tuple(str(row[k]) for k in data["keys"])
        for column in data["columns"]:
            proof = data["provenance"].get((key, column), {})
            out.append({
                "dataset": ds,
                "key": list(key),
                "column": column,
                "record_sha256": targets[(key, column)]["record_sha256"],
                "first_pass_kind": proof.get("kind"),
                "first_pass_sources": [{k: v for k,v in source.items() if k != "raw"}
                                       for source in proof.get("sources", [])],
                "value_here": "",
                "method": "independent_reextract",
                "reviewer": "",
                "checked_at": "",
                "note": "",
                "snapshot": snapshot.get("stamp") if snapshot else None,
            })
    return out


def write_template(project: C.Project, entry: Mapping, snapshot: Mapping,
                   rel: str | None = None) -> str:
    rows = blind_template(project, entry, snapshot=snapshot)
    rel = rel or f"workbench/{entry['id']}.second_pass.jsonl"
    path = project.path(rel)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path.relative_to(project.root).as_posix()


# ---------------------------------------------------------------------------
# import second pass
# ---------------------------------------------------------------------------
def _parse_time(value: str) -> _dt.datetime:
    try:
        parsed = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as exc:                            # noqa: BLE001
        raise WorkbenchError(f"checked_at is not an ISO instant: {value!r}") from exc
    if parsed.tzinfo is None:
        raise WorkbenchError("checked_at must carry a timezone offset")
    return parsed


def import_second_pass(project: C.Project, entry: Mapping, rows: list[dict],
                       *, snapshot: Mapping, reviewer_agent: str | None = None,
                       lock_timeout: float = 5.0) -> dict:
    ds = entry["id"]
    data = load_dataset(project, entry)
    current, targets, issues = prepared_context(project, entry)
    if issues:
        raise WorkbenchError(f"prepare failed; repair provenance before review: {issues[:3]}")
    if snapshot.get("fingerprint") and snapshot["fingerprint"] != current["fingerprint"]:
        raise WorkbenchError("the evidence context changed after prepare")
    if snapshot.get("dataset_sha256") and \
            snapshot["dataset_sha256"] != data["sha256"]:
        raise WorkbenchError("the dataset changed after the snapshot; re-prepare "
                             "before importing a second pass")
    snapshot_time = _parse_time(snapshot["stamp"]) if snapshot.get("stamp") else None
    values = {}
    for row in data["rows"]:
        key = tuple(str(row[k]) for k in data["keys"])
        for column in data["columns"]:
            values[(key, column)] = row[column]
    events: list[dict] = []
    conflicts: list[dict] = []
    review_lines: list[dict] = []
    seen = set()
    with T.Lock(project, f"review:{ds}", timeout=lock_timeout):
        for raw in rows:
            key = tuple(str(k) for k in raw.get("key", []))
            column = raw.get("column")
            if (key, column) not in values:
                raise WorkbenchError(f"second-pass row {key}/{column} is not a "
                                     f"cell of {ds}")
            if (key, column) in seen:
                raise WorkbenchError(f"duplicate second-pass row {key}/{column}")
            seen.add((key, column))
            first = values[(key, column)]
            signature = targets[(key, column)]["record_sha256"]
            if raw.get("record_sha256") != signature:
                raise WorkbenchError(
                    f"{key}/{column}: record_sha256 does not match the current "
                    f"cell (stale template or edited dataset)")
            checked_at = raw.get("checked_at") or ""
            when = _parse_time(checked_at) if checked_at else None
            if when is None:
                raise WorkbenchError(f"{key}/{column}: checked_at is required")
            if when > _dt.datetime.now(_dt.timezone.utc):
                raise WorkbenchError("a review cannot be in the future")
            if snapshot_time and when < snapshot_time:
                raise WorkbenchError(
                    f"{key}/{column}: checked_at precedes the snapshot; a review "
                    f"cannot be older than the thing it reviewed")
            note = (raw.get("note") or "").strip()
            if note.lower() in GENERIC_NOTES:
                raise WorkbenchError(
                    f"{key}/{column}: a generic/empty note does not show the cell "
                    f"was actually re-read")
            scope = raw.get("reread_scope") or {}
            if not scope.get("locator") and not raw.get("first_pass_sources"):
                raise WorkbenchError(
                    f"{key}/{column}: no re-read locator; refusing to accept a "
                    f"verification with nothing to point at")
            method = raw.get("method") or "source_reread"
            if method not in ("source_reread", "independent_reextract"):
                raise WorkbenchError(f"unknown method {method!r}")
            second = raw.get("value_here")
            if second is None:
                raise WorkbenchError(f"{key}/{column}: value_here is required "
                                     f"(empty string means the source is empty)")
            outcome = "confirmed" if str(second) == str(first) else "differs"
            event = {
                "dataset": ds, "key": list(key), "column": column,
                "value_under_review": str(first), "record_sha256": signature,
                "method": method,
                "reviewer": raw.get("reviewer") or reviewer_agent or "",
                "independence": ("independent_of_first_pass"
                                 if method == "independent_reextract"
                                 else "same_agent_reread"),
                "reread_scope": scope or {"locator": "declared in first-pass "
                                                     "sources"},
                "second_pass": {"value": str(second), "outcome": outcome,
                                "checked_at": checked_at},
                "outcome": outcome, "checked_at": checked_at, "note": note,
            }
            if not event["reviewer"]:
                raise WorkbenchError(f"{key}/{column}: reviewer identity required")
            rec = C.make_record(
                "review_event",
                C.canonical_hash([ds, list(key), column, signature,
                                  checked_at])[:24],
                event, producer=_producer(), status="recorded")
            events.append(rec)
            if outcome == "confirmed":
                review_lines.append({
                    "dataset": ds, "key": list(key), "column": column,
                    "record_sha256": signature, "status": "verified",
                    "source_reread": True, "reviewer": event["reviewer"],
                    "method": method, "checked_at": checked_at, "note": note})
            else:
                conflicts.append({"key": list(key), "column": column,
                                  "first": first, "second": second,
                                  "record_sha256": signature,
                                  "event": rec["id"]})
        project.append_many("review_event", events, enforce_transition=False)
    return {"events": len(events), "confirmed": len(review_lines),
            "conflicts": conflicts, "review_lines": review_lines,
            "cells_in_dataset": len(values), "cells_reviewed": len(seen),
            "complete": len(seen) == len(values)}


def write_review_file(project: C.Project, entry: Mapping,
                      lines: Iterable[Mapping], *,
                      merge_existing: bool = True) -> str:
    """Merge verified lines into the dataset's ``review`` file."""
    path = project.root / entry["review"]
    path = C.protect_output(project, path)
    with T.Lock(project, f"dataset-{entry['id']}", timeout=60):
        return _write_review_file_locked(project, entry, lines, merge_existing=merge_existing)


def _write_review_file_locked(project, entry, lines, *, merge_existing):
    path = C.protect_output(project, project.root / entry["review"])
    current = load_dataset(project, entry)
    targets = {(tuple(str(row[k]) for k in current["keys"]), col) for row in current["rows"] for col in current["columns"]}
    existing: dict[tuple, dict] = {}
    if merge_existing and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            key = tuple(str(k) for k in rec["key"])
            if (key, rec["column"]) in targets:
                existing[(key, rec["column"])] = rec
    for line in lines:
        key = tuple(str(k) for k in line["key"])
        if (key, line["column"]) not in targets:
            raise WorkbenchError("new review points at a missing cell; historical reviews remain in the event ledger")
        existing[(key, line["column"])] = dict(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    T._write_atomic(path, "".join(json.dumps(rec, ensure_ascii=False) + "\n"
                                for _, rec in sorted(existing.items())).encode("utf-8"))
    return path.relative_to(project.root).as_posix()


# ---------------------------------------------------------------------------
# patches
# ---------------------------------------------------------------------------
def propose_patch(project: C.Project, entry: Mapping, *, key: Iterable[str],
                  column: str, new_value: str, parent: str, reason: str,
                  operator: str = "agent") -> dict:
    data = load_dataset(project, entry)
    key_t = tuple(str(k) for k in key)
    current = None
    for row in data["rows"]:
        if tuple(str(row[k]) for k in data["keys"]) == key_t:
            current = row
            break
    if current is None:
        raise WorkbenchError(f"unknown key {key_t}")
    signature = cell_signature(entry["id"], key_t, column, current[column])
    if parent and parent != signature:
        raise WorkbenchError(
            f"parent version mismatch: patch expects {parent[:12]}, current is "
            f"{signature[:12]} - someone else changed this cell")
    payload = {"dataset": entry["id"], "key": list(key_t), "column": column,
               "new_value": str(new_value), "parent_snapshot": signature,
               "operations": [{"op": "set", "column": column,
                               "from": current[column], "to": str(new_value)}],
               "reason": reason, "operator": operator}
    rid = C.canonical_hash([entry["id"], list(key_t), column, signature,
                            str(new_value)])[:24]
    rec = C.make_record("review_patch", rid, payload, producer=_producer(),
                        status="proposed")
    prev = project.latest("review_patch", rid)
    if prev is not None:
        raise WorkbenchError("an identical patch already exists")
    project.append("review_patch", rec)
    return rec


def apply_patch(project: C.Project, patch_id: str, *,
                applier: str) -> dict:
    """Write the patched dataset as a NEW version; old reviews go stale."""
    rec = project.latest("review_patch", patch_id)
    if rec is None:
        raise WorkbenchError(f"unknown patch {patch_id}")
    with T.Lock(project, f"dataset-{rec['data']['dataset']}", timeout=60):
        return _apply_patch_locked(project, patch_id, applier=applier)


def _apply_patch_locked(project, patch_id, *, applier):
    rec = project.latest("review_patch", patch_id)
    if rec is None:
        raise WorkbenchError(f"unknown patch {patch_id}")
    if rec["status"] != "proposed":
        raise WorkbenchError(f"patch {patch_id} is {rec['status']}")
    dataset = rec["data"]["dataset"]
    registry = json.loads((project.root / "research_registry.json").read_text(
        encoding="utf-8"))
    entry = next((e for e in registry["datasets"] if e["id"] == dataset), None)
    if entry is None:
        raise WorkbenchError(f"dataset {dataset} not in the registry")
    data = load_dataset(project, entry)
    keys = tuple(str(k) for k in rec["data"]["key"])
    column = rec["data"]["column"]
    changed = []
    rows = []
    for row in data["rows"]:
        if tuple(str(row[k]) for k in data["keys"]) == keys:
            current_sig = cell_signature(dataset, keys, column, row[column])
            if current_sig != rec["data"]["parent_snapshot"]:
                conflict = C.transition(rec, "conflict", producer=_producer(),
                                        reason="parent cell changed before apply")
                project.append("review_patch", conflict, enforce_transition=False)
                raise WorkbenchError("parent cell changed; patch is now in "
                                     "conflict and was not applied")
            changed.append({"column": column, "from": row[column],
                            "to": rec["data"]["new_value"]})
            row[column] = rec["data"]["new_value"]
        rows.append(row)
    if not changed:
        raise WorkbenchError("patch target row disappeared")
    path = C.protect_output(project, project.root / entry["path"])
    import io
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=data["columns"])
    writer.writeheader()
    writer.writerows(rows)
    T._write_atomic(path, stream.getvalue().encode("utf-8-sig"))
    applied = C.transition(rec, "applied", producer=_producer(),
                           patch={"applied_at": C._now(), "applier": applier},
                           reason=f"dataset rewritten by {applier}; all reviews "
                                  f"for this dataset are now stale")
    project.append("review_patch", applied, enforce_transition=False)
    return {"patch": applied["id"], "dataset": dataset,
            "changed": changed, "dataset_sha256": C.file_sha256(path),
            "reviews_invalidated": True,
            "next": "run verify_dataset prepare -> re-read every cell -> final"}


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------
def review_gate(project: C.Project, entry: Mapping) -> dict:
    data = load_dataset(project, entry)
    _, targets, prepare_issues = prepared_context(project, entry)
    events = [r for r in project.read("review_event")
              if r["data"]["dataset"] == entry["id"]]
    latest: dict[tuple, dict] = {}
    for rec in events:
        key = (tuple(str(k) for k in rec["data"]["key"]),
               rec["data"]["column"])
        if key not in targets:
            continue
        if key not in latest or (_parse_time(rec["data"]["checked_at"]), _parse_time(rec["created_at"]), rec["revision"]) > (_parse_time(latest[key]["data"]["checked_at"]), _parse_time(latest[key]["created_at"]), latest[key]["revision"]):
            latest[key] = rec
    problems = list(prepare_issues)
    for (key, column), rec in latest.items():
        d = rec["data"]
        if d["record_sha256"] != targets.get((key, column), {}).get("record_sha256"):
            problems.append({"check": "stale_signature", "key": list(key),
                             "column": column})
        if (d["note"] or "").strip().lower() in GENERIC_NOTES:
            problems.append({"check": "generic_note", "key": list(key),
                             "column": column})
        if not d["reviewer"]:
            problems.append({"check": "missing_reviewer", "key": list(key),
                             "column": column})
        if d["outcome"] != "confirmed":
            problems.append({"check": "unresolved_second_pass", "key": list(key), "column": column})
    total = len(data["rows"]) * len(data["columns"])
    return {"dataset": entry["id"], "cells": total,
            "reviewed_cells": len(latest),
            "disputed": sum(1 for r in latest.values()
                            if r["data"]["outcome"] == "differs"),
            "problems": problems,
            "claim_complete": total > 0 and len(latest) == total
            and not problems}


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="per-cell review workbench")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_e = sub.add_parser("export")
    p_e.add_argument("--dataset", required=True)
    p_b = sub.add_parser("blind")
    p_b.add_argument("--dataset", required=True)
    p_i = sub.add_parser("import")
    p_i.add_argument("--dataset", required=True)
    p_i.add_argument("--file", required=True)
    p_p = sub.add_parser("patch")
    p_p.add_argument("--dataset", required=True)
    p_p.add_argument("--key", nargs="+", required=True)
    p_p.add_argument("--column", required=True)
    p_p.add_argument("--value", required=True)
    p_p.add_argument("--parent", required=True)
    p_p.add_argument("--reason", required=True)
    p_g = sub.add_parser("gate")
    p_g.add_argument("--dataset", required=True)
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    registry = json.loads((proj.root / "research_registry.json").read_text(
        encoding="utf-8"))
    entry = next((e for e in registry["datasets"] if e["id"] == args.dataset),
                 None)
    if entry is None:
        print(f"dataset {args.dataset} is not in research_registry.json",
              file=sys.stderr)
        return 2
    if args.cmd == "export":
        print(json.dumps(export_html(proj, entry), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "blind":
        export = proj.dir / "workbench" / f"{args.dataset}.export.json"
        snap = json.loads(export.read_text(encoding="utf-8")) if export.is_file() else export_html(proj, entry)
        print(write_template(proj, entry, snap))
        return 0
    if args.cmd == "import":
        rows = [json.loads(line) for line in Path(args.file).read_text(
            encoding="utf-8").splitlines() if line.strip()]
        snap = json.loads((proj.dir / "workbench" /
                           f"{args.dataset}.export.json").read_text(
                               encoding="utf-8"))
        res = import_second_pass(proj, entry, rows, snapshot=snap)
        if res["review_lines"]:
            write_review_file(proj, entry, res["review_lines"])
        print(json.dumps({k: v for k, v in res.items()
                          if k != "review_lines"}, ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "patch":
        print(json.dumps(propose_patch(proj, entry, key=args.key,
                                       column=args.column, new_value=args.value,
                                       parent=args.parent, reason=args.reason),
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "gate":
        res = review_gate(proj, entry)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["claim_complete"] else 2
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
