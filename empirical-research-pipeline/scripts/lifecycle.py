# -*- coding: utf-8 -*-
"""Environment binding, honest caching, and an open step scheduler.

Three small but load-bearing pieces:

**Environment** - a run is bound to the interpreter, the packages that matter,
external engines and the rule/config files.  A snapshot is taken *before* the run
and compared *after* it; drift is recorded, not hidden.  Seeds are not treated as
proof of reproducibility.

**Cache** - an entry is reusable only for exactly the inputs, code, rules and
environment it was built from.  Re-use writes a *new* run record that points at
the old artifact (``reused_cache``), it never re-dates the old result to look
freshly executed.

**Scheduler** - steps declare dependencies and a token/time budget; the scheduler
offers the ready ones and records every step's real state.  It does not prescribe
which tool or engine a step uses.

CLI::

    python lifecycle.py --root . env --snapshot --name run1
    python lifecycle.py --root . env --compare --name run1
    python lifecycle.py --root . cache --get <key>
    python lifecycle.py --root . next [--start ID | --finish ID]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C

PACKAGES = ("pandas", "numpy", "scipy", "statsmodels", "matplotlib",
            "fitz", "docx", "openpyxl", "PIL", "pdfplumber",
            "rapidocr_onnxruntime", "vosk")
EXTERNALS = ("ffmpeg", "soffice", "pandoc", "Rscript", "julia", "tesseract")


def _producer(**kw) -> dict:
    return C.producer_for("lifecycle", version="2.0", module_file=__file__, **kw)


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------
def _package_version(name: str) -> str | None:
    try:
        module = __import__(name)
    except Exception:                            # noqa: BLE001
        return None
    for attr in ("__version__", "version"):
        value = getattr(module, attr, None)
        if isinstance(value, str):
            return value
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:                            # noqa: BLE001
        return None


def _external(name: str) -> dict:
    path = shutil.which(name)
    out = {"available": bool(path), "path": path}
    if path:
        try:
            proc = subprocess.run([path, "-version" if name == "ffmpeg" else
                                   "--version"], capture_output=True, text=True,
                                  timeout=15)
            out["first_line"] = (proc.stdout or proc.stderr).splitlines()[0][:160]
        except Exception as exc:                 # noqa: BLE001
            out["probe_error"] = str(exc)
    return out


def _rules(project: C.Project, ruledir: str | None) -> dict:
    out = {}
    if ruledir:
        base = project.root / ruledir
        for path in sorted(base.rglob("*")):
            if path.is_file():
                out[path.relative_to(project.root).as_posix()] = \
                    C.file_sha256(path)
    return out


def snapshot(project: C.Project, *, name: str, ruledir: str | None = None,
             config: Mapping | None = None, fonts: Iterable[str] = (),
             seeds: Mapping | None = None) -> dict:
    payload = {
        "phase": name,
        "python": {"version": platform.python_version(),
                   "implementation": platform.python_implementation(),
                   "executable": sys.executable,
                   "bits": platform.architecture()[0]},
        "packages": {p: _package_version(p) for p in PACKAGES},
        "engines": {e: _external(e) for e in EXTERNALS},
        "fonts": list(fonts),
        "seeds": dict(seeds or {}),
        "system": {"system": platform.system(), "release": platform.release(),
                   "machine": platform.machine(),
                   "processor": platform.processor()},
        "external_inputs": [{"path": p, "sha256": h}
                            for p, h in sorted(_rules(project, ruledir).items())],
        "limits": [{"name": "rules_root", "value": ruledir},
                   {"name": "config", "value": json.loads(
                       json.dumps(config or {}, ensure_ascii=False))}],
        "notes": f"taken {C._now()}",
    }
    rid = f"env:{name}"
    prev = project.latest("environment_snapshot", rid)
    rec = C.make_record("environment_snapshot", rid, payload,
                        producer=_producer(), status="recorded",
                        revision=(prev["revision"] + 1) if prev else 1)
    project.append("environment_snapshot", rec, enforce_transition=False)
    return rec


def compare(project: C.Project, name: str) -> dict:
    rec = project.latest("environment_snapshot", f"env:{name}")
    if rec is None:
        raise SystemExit(f"no snapshot named {name}")
    before = rec["data"]
    after = snapshot(project, name=name + ":after",
                     seeds=before.get("seeds"))["data"]
    changes = []
    for section in ("python", "system"):
        for key, value in before[section].items():
            if after[section].get(key) != value:
                changes.append({"section": section, "key": key,
                                "before": value,
                                "after": after[section].get(key)})
    for pkg, version in before["packages"].items():
        if after["packages"].get(pkg) != version:
            changes.append({"section": "packages", "key": pkg,
                            "before": version,
                            "after": after["packages"].get(pkg)})
    for ext, info in before["engines"].items():
        if after["engines"][ext]["available"] != info["available"]:
            changes.append({"section": "engines", "key": ext,
                            "before": info["available"],
                            "after": after["engines"][ext]["available"]})
    incoming = {i["path"]: i["sha256"] for i in before.get("external_inputs", [])}
    for rel, old_sha in incoming.items():
        path = Path(rel)
        if not path.is_absolute():
            path = project.root / rel
        if not path.is_file():
            changes.append({"section": "external_inputs", "key": rel,
                            "before": old_sha, "after": "missing"})
        elif C.file_sha256(path) != old_sha:
            changes.append({"section": "external_inputs", "key": rel,
                            "before": old_sha,
                            "after": C.file_sha256(path)})
    if changes:
        drifted = C.transition(rec, "drifted", producer=_producer(),
                               reason=f"{len(changes)} environment changes")
        project.append("environment_snapshot", drifted, enforce_transition=False)
    return {"name": name, "before": rec["id"], "changes": changes,
            "drifted": bool(changes),
            "note": "a seed does not make a run reproducible; this compares "
                    "the actual environment"}


# ---------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------
def cache_key(*, inputs: Mapping[str, str], code: Mapping[str, str],
              rules: Mapping[str, str], environment: Mapping,
              label: str = "") -> str:
    material = {"inputs": dict(sorted(inputs.items())),
                "code": dict(sorted(code.items())),
                "rules": dict(sorted(rules.items())),
                "environment": environment, "label": label}
    return C.canonical_hash(material)[:24]


def _runtime_environment():
    import execution
    aliases={"docx":"python-docx","fitz":"PyMuPDF","PIL":"Pillow"}
    state = execution.environment(tuple(aliases.get(p,p) for p in PACKAGES))
    state["engines"] = {name: {"path":path,"sha256":C.file_sha256(path) if path else None}
                        for name in EXTERNALS for path in [shutil.which(name)]}
    return state


def put(project: C.Project, key: str, *, artifact: str,
        inputs: Mapping[str, str], code: Mapping[str, str],
        rules: Mapping[str, str], environment: Mapping,
        origin_run: str = "manual") -> dict:
    path = project.root / artifact
    if not path.is_file():
        raise SystemExit(f"artifact missing: {artifact}")
    payload = {"key": key,
               "inputs": {**{f"file:{k}": v for k, v in inputs.items()},
                          **{f"rule:{k}": v for k, v in rules.items()}},
               "code": dict(code), "environment": dict(environment), "runtime_environment":_runtime_environment(),
               "origin_run": origin_run,
               "outputs": [{"path": artifact,
                            "sha256": C.file_sha256(path)}],
               "reuse": {"count": 0, "last_run": None}}
    previous=project.latest("cache_entry",key)
    rec = C.make_record("cache_entry", key, payload, producer=_producer(),
                        status="valid",revision=previous["revision"]+1 if previous else 1)
    validation=is_valid(project,rec)
    if not validation["valid"]:
        raise ValueError(f"cache bindings are not current: {validation['problems']}")
    project.append("cache_entry", rec, enforce_transition=False)
    return rec


def is_valid(project: C.Project, rec: Mapping) -> dict:
    data = rec["data"]
    problems = []
    if rec.get("status") not in ("valid", "current"):
        problems.append({"path": "<cache-entry>",
                         "problem": f"status={rec.get('status')}"})
    for rel, sha in data["inputs"].items():
        rel = rel.split(":", 1)[1]
        path = Path(rel)
        if not path.is_absolute():
            path = project.root / rel
        if not path.is_file():
            problems.append({"path": rel, "problem": "missing"})
        elif C.file_sha256(path) != sha:
            problems.append({"path": rel, "problem": "changed"})
    for output in data.get("outputs", []):
        path = project.root / output["path"]
        if not path.is_file():
            problems.append({"path": output["path"], "problem": "missing"})
        elif C.file_sha256(path) != output["sha256"]:
            problems.append({"path": output["path"], "problem": "changed"})
    for rel,digest in data["code"].items():
        path=Path(rel);path=path if path.is_absolute() else project.root/path
        if not path.is_file() or C.file_sha256(path)!=digest:
            problems.append({"path":rel,"problem":"implementation missing or changed"})
    if data.get("runtime_environment") != _runtime_environment():
        problems.append({"path":"<runtime>","problem":"actual runtime changed or legacy binding is missing"})
    return {"valid": not problems, "problems": problems}


def reuse(project: C.Project, key: str, *, run_id: str) -> dict:
    """Reuse a cache entry by writing a NEW run record, never re-dating hits."""
    rec = project.latest("cache_entry", key)
    if rec is None:
        raise SystemExit(f"no cache entry {key}")
    state = is_valid(project, rec)
    if not state["valid"]:
        stale = C.transition(rec, "stale", producer=_producer(),
                             reason=f"inputs changed: {state['problems'][:3]}")
        project.append("cache_entry", stale, enforce_transition=False)
        return {"reused": False, "state": "stale",
                "problems": state["problems"]}
    previous_run=project.latest("workflow_step",f"reuse:{key}:{run_id}")
    if previous_run:
        if previous_run["data"]["outputs"] != rec["data"]["outputs"]:
            raise ValueError("reuse run ID already belongs to a different cache version")
        return {"reused":True,"state":"valid","run":previous_run["id"],"idempotent":True,
                "artifact":[o["path"] for o in rec["data"]["outputs"]]}
    payload = {"step": f"reuse:{key}:{run_id}",
               "scope": {"cache_entry": key,
                         "artifact": [o["path"] for o in rec["data"]["outputs"]]},
               "inputs": [{"cache_key": key, "inputs": rec["data"]["inputs"]}],
               "outputs": rec["data"]["outputs"],
               "run_state": {"status": "completed", "ran_again": False,
                             "reused_at": C._now(), "origin_run":
                             rec["data"]["origin_run"]},
               "check_state": {"status": "not_applicable",
                               "reason": "reuse does not re-check the numbers"},
               "notes": "cache hit: a new run record points at the old "
                        "artifact; the old result is not re-dated"}
    step = C.make_record("workflow_step", payload["step"], payload,
                         producer=_producer(), status="completed")
    project.append("workflow_step", step, enforce_transition=False)
    updated = dict(rec["data"])
    updated["reuse"] = {"count": int(updated["reuse"]["count"]) + 1,
                        "last_run": run_id}
    project.append("cache_entry",
                   C.make_record("cache_entry", key, updated,
                                 producer=_producer(), status="valid",
                                 revision=rec["revision"] + 1),
                   enforce_transition=False)
    return {"reused": True, "state": "valid", "run": step["id"],
            "artifact": [o["path"] for o in rec["data"]["outputs"]]}


# ---------------------------------------------------------------------------
# scheduler
# ---------------------------------------------------------------------------
def _step_payload(payload: Mapping, *, status: str, **run) -> dict:
    out = json.loads(json.dumps(payload))
    out["run_state"].update(run)
    out["run_state"]["status"] = status
    return out


def plan(project: C.Project, steps: Iterable[Mapping]) -> list[dict]:
    steps=list(steps)
    ids=[s.get("id") for s in steps]
    if len(set(ids))!=len(ids):raise ValueError("duplicate workflow step IDs")
    existing=states(project)
    dependencies={key:_deps(rec) for key,rec in existing.items()}
    dependencies.update({s["id"]:list(s.get("depends_on",[])) for s in steps if s.get("id")})
    visited=set();active=set()
    def visit(key):
        if key in active:raise ValueError("workflow dependency cycle")
        if key in visited:return
        if key not in dependencies:raise ValueError(f"unknown workflow dependency: {key}")
        active.add(key)
        for parent in dependencies[key]:visit(parent)
        active.remove(key);visited.add(key)
    for step in steps:
        if not step.get("id") or not step.get("goal"):raise ValueError("workflow steps need ID and goal before any records are written")
        visit(step["id"])
    out = []
    for step in steps:
        for key in ("id", "goal"):
            if not step.get(key):
                raise SystemExit(f"step needs {key}")
        payload = {"step": step["id"],
                   "scope": {"goal": step["goal"],
                             "tool": step.get("tool", "open"),
                             "budget": step.get("budget", {})},
                   "inputs": [{"depends_on": d} for d in
                              step.get("depends_on", [])] +
                             [{"consumes": c} for c in step.get("consumes", [])],
                   "outputs": list(step.get("produces", [])),
                   "run_state": {"status": "planned"},
                   "check_state": {"status": "planned"},
                   "blocked_by": list(step.get("depends_on", [])),
                   "notes": step.get("notes", "")}
        prev = project.latest("workflow_step", step["id"])
        rec = C.make_record("workflow_step", step["id"], payload,
                            producer=_producer(), status="planned",
                            revision=(prev["revision"] + 1) if prev else 1)
        project.append("workflow_step", rec, enforce_transition=False)
        out.append(rec)
    return out


def states(project: C.Project) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for rec in project.read("workflow_step"):
        if rec["id"] not in latest or rec["revision"] > latest[rec["id"]]["revision"]:
            latest[rec["id"]] = rec
    return latest


def _deps(rec: Mapping) -> list[str]:
    return [i["depends_on"] for i in rec["data"].get("inputs", [])
            if "depends_on" in i]


def ready(project: C.Project) -> list[str]:
    latest = states(project)
    out = []
    for sid, rec in latest.items():
        if rec["status"] != "planned":
            continue
        if all(latest.get(d, {}).get("status") == "completed"
               for d in _deps(rec)):
            out.append(sid)
    return sorted(out)


def start(project: C.Project, step_id: str, *,
          token_budget: int | None = None) -> dict:
    latest = states(project)
    rec = latest.get(step_id)
    if rec is None:
        raise SystemExit(f"unknown step {step_id}")
    if rec["status"] != "planned":
        raise SystemExit(f"step {step_id} is {rec['status']}, not planned")
    missing = [d for d in _deps(rec)
               if latest.get(d, {}).get("status") != "completed"]
    if missing:
        raise SystemExit(f"step {step_id} waits on {missing}")
    payload = _step_payload(rec["data"], status="running",
                            started_at=C._now(),
                            token_budget=token_budget)
    payload["blocked_by"] = []
    new = C.make_record("workflow_step", step_id, payload, producer=_producer(),
                        status="running", revision=rec["revision"] + 1)
    project.append("workflow_step", new)
    return new


def finish(project: C.Project, step_id: str, *, status: str,
           detail: str = "", tokens_used: int | None = None) -> dict:
    if status not in ("completed", "failed", "blocked", "cancelled", "stale"):
        raise SystemExit(f"bad terminal status {status}")
    latest = states(project)
    rec = latest.get(step_id)
    if rec is None:
        raise SystemExit(f"unknown step {step_id}")
    payload = _step_payload(rec["data"], status=status,
                            finished_at=C._now(), detail=detail,
                            tokens_used=tokens_used)
    budget = (payload["scope"].get("budget") or {}).get("tokens")
    if budget and tokens_used and tokens_used > budget:
        payload["run_state"]["over_budget"] = True
    new = C.make_record("workflow_step", step_id, payload,
                        producer=_producer(), status=status,
                        revision=rec["revision"] + 1)
    project.append("workflow_step", new)
    return new


def blocked_by(project: C.Project) -> dict:
    latest = states(project)
    out = {}
    for sid, rec in latest.items():
        if rec["status"] in ("planned", "blocked"):
            waiting = [d for d in _deps(rec)
                       if latest.get(d, {}).get("status") != "completed"]
            if waiting:
                out[sid] = waiting
    return out


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="lifecycle helpers")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_env = sub.add_parser("env")
    p_env.add_argument("--snapshot", action="store_true")
    p_env.add_argument("--compare", action="store_true")
    p_env.add_argument("--name", default="run")
    p_env.add_argument("--rules")
    p_cache = sub.add_parser("cache")
    p_cache.add_argument("--key")
    p_cache.add_argument("--get")
    p_next = sub.add_parser("next")
    p_next.add_argument("--start")
    p_next.add_argument("--finish")
    p_next.add_argument("--status", default="completed")
    p_next.add_argument("--detail", default="")
    args = ap.parse_args(argv)
    proj = C.Project(args.root)
    if args.cmd == "env":
        if args.snapshot:
            print(json.dumps(snapshot(proj, name=args.name,
                                      ruledir=args.rules)["data"],
                             ensure_ascii=False, indent=1))
            return 0
        print(json.dumps(compare(proj, args.name), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "cache":
        if args.get:
            print(json.dumps(reuse(proj, args.get, run_id="cli"),
                             ensure_ascii=False, indent=1))
            return 0
        rec = proj.latest("cache_entry", args.key)
        print(json.dumps({"key": args.key,
                          "valid": is_valid(proj, rec) if rec else None},
                         ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "next":
        if args.start:
            print(json.dumps(start(proj, args.start), ensure_ascii=False,
                             indent=1))
            return 0
        if args.finish:
            print(json.dumps(finish(proj, args.finish, status=args.status,
                                    detail=args.detail),
                             ensure_ascii=False, indent=1))
            return 0
        print(json.dumps({"ready": ready(proj), "blocked": blocked_by(proj)},
                         ensure_ascii=False, indent=1))
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
