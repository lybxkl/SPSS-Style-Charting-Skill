# -*- coding: utf-8 -*-
"""Dependency graph over research objects: nodes, typed edges, change events.

The graph answers one question for the whole pipeline: *when X changes, which
datasets, reviews, models, figures, claims and manuscript blocks are no longer
trustworthy?*  It therefore has to model more than "derives from":

* ``supplies``     - a source/dataset provides a value to a consumer
* ``derived``      - deterministic computation
* ``compares``     - a comparison/spec uses two results together
* ``excludes``     - a *negative* judgement ("this source has no such field")
* ``missing_judgment`` - a missing-value adjudication that new material changes
* ``presents``     - a figure/table shows a result
* ``cites``        - a claim rests on a reference or a result
* ``depends_on``   - generic structural dependency

The negative edge types exist because adding material can invalidate "we looked
and it was not there" even when no value is overwritten (plan R07.3 / P19).

Cycle rule: a single *version* of derivations must be acyclic.  Feedback loops
in the research workflow are expressed as new versions (new revision, new
event), never as an edge that closes a loop.

CLI::

    python depgraph.py --root . register --type source --id materials/a.pdf \
        --version sha256:... --label a.pdf
    python depgraph.py --root . edge --from src:a.pdf --to dataset:d1 \
        --type supplies
    python depgraph.py --root . impact --changed src:a.pdf
    python depgraph.py --root . events --since 0
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict, deque
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C

EDGE_TYPES = ("supplies", "derived", "compares", "excludes",
              "missing_judgment", "presents", "cites", "depends_on")
#: Edge types whose downstream consumers must be re-examined when the tail
#: changes.  ``presents`` and ``cites`` are included on purpose: a changed
#: result invalidates the figure/claim that presented it.
PROPAGATING = frozenset(EDGE_TYPES)
#: Edge types that encode a *judgement about absence*, which new material can
#: overturn even though nothing was overwritten.
NEGATIVE = frozenset({"excludes", "missing_judgment"})

EVENTS = ("created", "content_changed", "removed", "status_changed",
          "decision_changed", "environment_changed", "rejudged", "reused_cache")


class GraphError(Exception):
    pass


class CycleError(GraphError):
    pass


def _producer() -> dict:
    return C.producer_for("depgraph", version="2.0", module_file=__file__)


class DependencyGraph:
    """Append-only node/edge/event ledger with a cached in-memory view."""

    def __init__(self, project: C.Project):
        self.project = project
        self._nodes: dict[str, dict] | None = None
        self._edges: list[dict] | None = None
        self._events: list[dict] | None = None

    # -- loading -----------------------------------------------------------
    def _load(self) -> None:
        if self._nodes is not None:
            return
        self._nodes = {}
        for rec in self.project.read("dependency_node"):
            self._nodes[rec["id"]] = rec
        self._edges = self.project.read("dependency_edge")
        self._events = self.project.read("dependency_event")

    def reload(self) -> None:
        self._nodes = self._edges = self._events = None
        self._load()

    # -- nodes -------------------------------------------------------------
    def node_key(self, node_type: str, stable_id: str) -> str:
        return f"{node_type}:{stable_id}"

    def register(self, node_type: str, stable_id: str, version: str, *,
                 label: str | None = None, path: str | None = None,
                 status: str = "active") -> dict:
        self._load()
        key = self.node_key(node_type, stable_id)
        prev = self._nodes.get(key)
        payload = {"stable_id": stable_id, "node_type": node_type,
                   "content_version": version}
        if label:
            payload["label"] = label
        if path:
            payload["path"] = path
        if prev is None:
            rec = C.make_record("dependency_node", key, payload,
                                producer=_producer(), status=status)
            self.project.append("dependency_node", rec)
            self._event(key, "created", {"version": version})
            self._nodes[key] = rec
            return rec
        if prev["data"]["content_version"] == version:
            return prev
        rec = C.make_record("dependency_node", key, payload, producer=_producer(),
                            status=status, revision=prev["revision"] + 1,
                            supersedes=f"dependency_node:{key}@r{prev['revision']}")
        self.project.append("dependency_node", rec)
        self._event(key, "content_changed",
                    {"from": prev["data"]["content_version"], "to": version})
        self._nodes[key] = rec
        return rec

    def get(self, key: str) -> dict | None:
        self._load()
        return self._nodes.get(key)

    def nodes(self) -> list[dict]:
        self._load()
        return list(self._nodes.values())

    # -- edges -------------------------------------------------------------
    def add_edge(self, src: str, dst: str, edge_type: str, *,
                 evidence: str | None = None, note: str | None = None) -> dict:
        if edge_type not in EDGE_TYPES:
            raise GraphError(f"unknown edge type {edge_type!r}; "
                             f"expected one of {EDGE_TYPES}")
        self._load()
        eid = C.canonical_hash({"from": src, "to": dst, "type": edge_type})[:24]
        for rec in self._edges:
            if rec["id"] == eid:
                return rec
        payload = {"from": src, "to": dst, "edge_type": edge_type}
        if evidence:
            payload["evidence"] = evidence
        if note:
            payload["note"] = note
        if src == dst:
            raise CycleError(f"self edge {src} ({edge_type})")
        # a derivation edge may not close a loop on the *current* version
        if edge_type in ("derived", "supplies", "depends_on"):
            if self._reachable(dst, src, ("derived", "supplies", "depends_on")):
                raise CycleError(
                    f"{src} -> {dst} would close a derivation cycle "
                    f"({dst} already reaches {src}); express the feedback as a "
                    f"new version instead")
        rec = C.make_record("dependency_edge", eid, payload, producer=_producer())
        self.project.append("dependency_edge", rec)
        self._edges.append(rec)
        return rec

    def edges(self) -> list[dict]:
        self._load()
        return list(self._edges)

    def _adjacency(self, types: Iterable[str]) -> dict[str, set[str]]:
        self._load()
        wanted = set(types)
        adj: dict[str, set[str]] = defaultdict(set)
        for rec in self._edges:
            if rec["status"] != "active":
                continue
            if rec["data"]["edge_type"] in wanted:
                adj[rec["data"]["from"]].add(rec["data"]["to"])
        return adj

    def _reachable(self, start: str, target: str,
                   types: Iterable[str]) -> bool:
        adj = self._adjacency(types)
        seen: set[str] = set()
        dq = deque([start])
        while dq:
            cur = dq.popleft()
            if cur == target:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            dq.extend(adj.get(cur, ()))
        return False

    # -- impact ------------------------------------------------------------
    def impact(self, changed: Iterable[str]) -> dict:
        """Transitive closure of everything downstream of ``changed``.

        Returns affected nodes grouped by node type plus the *negative*
        judgements that must be re-examined (those are not "wrong", they are
        "needs a fresh look because new material arrived").
        """
        adj = self._adjacency(PROPAGATING)
        negative = {rec["data"]["to"] for rec in self._edges or []
                    if rec["data"]["edge_type"] in NEGATIVE
                    and rec["status"] == "active"}
        seen: set[str] = set()
        order: list[str] = []
        dq = deque(changed)
        while dq:
            cur = dq.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            order.append(cur)
            dq.extend(sorted(adj.get(cur, ())))
        affected = [n for n in order if n not in set(changed)]
        groups: dict[str, list[str]] = defaultdict(list)
        for key in affected:
            node = (self._nodes or {}).get(key)
            ntype = node["data"]["node_type"] if node else key.split(":", 1)[0]
            groups[ntype].append(key)
        need_rejudgement = sorted(set(affected) & negative)
        return {
            "changed": sorted(changed),
            "affected": affected,
            "affected_count": len(affected),
            "by_type": {k: sorted(v) for k, v in sorted(groups.items())},
            "rejudge_negative": need_rejudgement,
            "edges_followed": sorted(PROPAGATING),
        }

    def mark_stale(self, keys: Iterable[str], *, reason: str) -> list[dict]:
        out: list[dict] = []
        self._load()
        for key in keys:
            prev = self._nodes.get(key)
            if prev is None or prev["status"] != "active":
                continue
            rec = C.transition(prev, "stale", producer=_producer(),
                               reason=reason)
            self.project.append("dependency_node", rec)
            self._nodes[key] = rec
            self._event(key, "status_changed", {"to": "stale",
                                                "reason": reason})
            out.append(rec)
        return out

    # -- events ------------------------------------------------------------
    def _event(self, node: str, event: str, detail: Mapping,
               *, old: str | None = None, new: str | None = None) -> dict:
        payload = {"node": node, "event": event, "detail": dict(detail)}
        if old:
            payload["old_version"] = old
        if new:
            payload["new_version"] = new
        rid = f"{node}@{C._now()}#{len(self.project.read('dependency_event')) + 1}"
        rec = C.make_record("dependency_event", rid, payload,
                            producer=_producer())
        self.project.append("dependency_event", rec)
        if self._events is not None:
            self._events.append(rec)
        return rec

    def events(self, since: int = 0) -> list[dict]:
        self._load()
        return list(self._events[since:])

    def replay(self) -> list[str]:
        """Ordered description of every event (for audit output)."""
        out = []
        for rec in self.events():
            d = rec["data"]
            out.append(f"{rec['created_at']} {d['event']} {d['node']} "
                       f"{json.dumps(d['detail'], ensure_ascii=False, sort_keys=True)}")
        return out

    # -- checks ------------------------------------------------------------
    def check(self) -> dict:
        self._load()
        problems: list[str] = []
        for rec in self._edges:
            d = rec["data"]
            for end in (d["from"], d["to"]):
                if end not in self._nodes:
                    problems.append(f"edge {rec['id']} references unknown node "
                                    f"{end}")
            if d["edge_type"] not in EDGE_TYPES:
                problems.append(f"edge {rec['id']} has unknown type "
                                f"{d['edge_type']}")
        # derivation acyclicity over the current active graph
        adj = self._adjacency(("derived", "supplies", "depends_on"))
        state: dict[str, int] = {}

        def dfs(node: str, stack: list[str]) -> None:
            state[node] = 1
            for nxt in adj.get(node, ()):  # noqa: B007
                if state.get(nxt) == 1:
                    problems.append("derivation cycle: " + " -> ".join(
                        stack + [node, nxt]))
                elif state.get(nxt, 0) == 0:
                    dfs(nxt, stack + [node])
            state[node] = 2

        for node in list(self._nodes):
            if state.get(node, 0) == 0:
                dfs(node, [])
        return {"ok": not problems, "problems": problems,
                "nodes": len(self._nodes), "edges": len(self._edges),
                "events": len(self._events or [])}

    def to_dot(self) -> str:
        lines = ["digraph research {", '  rankdir=LR;']
        for rec in self._nodes.values():
            d = rec["data"]
            lines.append(f'  "{rec["id"]}" [label="{d["node_type"]}:'
                         f'{d["stable_id"]}\\n{d["content_version"][:12]}"];')
        for rec in self._edges:
            d = rec["data"]
            style = ' [style=dashed]' if d["edge_type"] in NEGATIVE else ""
            lines.append(f'  "{d["from"]}" -> "{d["to"]}" '
                         f'[label="{d["edge_type"]}"]{style};')
        lines.append("}")
        return "\n".join(lines)


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="research dependency graph")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_reg = sub.add_parser("register")
    p_reg.add_argument("--type", required=True)
    p_reg.add_argument("--id", required=True)
    p_reg.add_argument("--version", required=True)
    p_reg.add_argument("--label")
    p_reg.add_argument("--path")
    p_edge = sub.add_parser("edge")
    p_edge.add_argument("--from", dest="src", required=True)
    p_edge.add_argument("--to", dest="dst", required=True)
    p_edge.add_argument("--type", required=True, choices=list(EDGE_TYPES))
    p_edge.add_argument("--evidence")
    p_imp = sub.add_parser("impact")
    p_imp.add_argument("--changed", nargs="+", required=True)
    sub.add_parser("check")
    p_ev = sub.add_parser("events")
    p_ev.add_argument("--since", type=int, default=0)
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    g = DependencyGraph(proj)
    if args.cmd == "register":
        rec = g.register(args.type, args.id, args.version, label=args.label,
                         path=args.path)
        print(f"{rec['id']} r{rec['revision']} {rec['data']['content_version']}")
        return 0
    if args.cmd == "edge":
        rec = g.add_edge(args.src, args.dst, args.type, evidence=args.evidence)
        print(f"{rec['id']}")
        return 0
    if args.cmd == "impact":
        print(json.dumps(g.impact(args.changed), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "check":
        res = g.check()
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    if args.cmd == "events":
        for line in g.replay()[args.since:]:
            print(line)
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
