"""Version-bound execution for built-in, Python and command-array adapters.

Adapters are explicitly selected trusted code, never commands extracted from a
source document. The same before/after input, code and source protection applies
to every engine. Result shape remains the adapter's declared research output.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib.metadata
import inspect
import json
from pathlib import Path
import platform
import subprocess
import shutil
import sys
import time

import contract_v2 as C


class ExecutionError(Exception):
    pass


def environment(packages=()):
    versions = {}
    for name in sorted(set(("numpy", "scipy", "statsmodels", "pandas", *packages))):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {"python": sys.version, "executable": sys.executable,
            "platform": platform.platform(), "packages": versions}


def code_paths(project, spec, runner=None):
    paths = {Path(__file__).with_name(name).resolve() for name in
             ("execution.py", "models.py", "contract_v2.py", "source_guard.py", "verify_dataset.py")}
    for name in [*spec.get("code", []), *(spec.get("executor") or {}).get("code", [])]:
        path = Path(name)
        paths.add((path if path.is_absolute() else project.root / path).resolve())
    command = (spec.get("executor") or {}).get("command")
    if command:
        executable = shutil.which(command[0])
        if executable:
            paths.add(Path(executable).resolve())
    if callable(runner):
        path = inspect.getsourcefile(runner)
        if not path:
            raise ExecutionError("a Python adapter must have a bindable source file")
        paths.add(Path(path).resolve())
    for target in (spec.get("runner"), spec.get("conditions_runner"), spec.get("target"), (spec.get("parameters") or {}).get("objective"),
                   (spec.get("parameters") or {}).get("rhs"),
                   *(c.get("fun") for c in (spec.get("parameters") or {}).get("constraints", []) if isinstance(c, dict))):
        if isinstance(target, str) and ":" in target:
            path = Path(target.rsplit(":", 1)[0])
            paths.add((path if path.is_absolute() else project.root / path).resolve())
    return sorted(paths)


def binding(project, spec, runner=None):
    paths = {}
    for item in spec["inputs"]:
        path = Path(item["dataset"])
        path = (path if path.is_absolute() else project.root / path).resolve()
        if not path.is_file() or C.file_sha256(path) != item["sha256"]:
            raise ExecutionError(f"input missing or changed: {path}")
        paths[str(path)] = item["sha256"]
    code = {str(p): C.file_sha256(p) for p in code_paths(project, spec, runner)}
    return {"spec_sha256": C.canonical_hash(spec), "inputs": paths, "code": code,
            "environment": environment(spec.get("packages", ())), "started_at": C._now()}


def current(project, spec, recorded):
    try:
        now = binding(project, spec)
        return all(now[k] == recorded.get(k) for k in ("spec_sha256", "inputs", "environment")) and all(
            Path(path).is_file() and C.file_sha256(path) == sha for path, sha in recorded.get("code", {}).items())
    except (OSError, ExecutionError):
        return False


@contextmanager
def protected(project, spec, runner=None):
    before = binding(project, spec, runner)
    registry_path = project.root / "research_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.is_file() else {}
    source = Path(registry.get("source_root") or "materials")
    source = (source if source.is_absolute() else project.root / source).resolve()
    guard = None
    if source.is_dir():
        from source_guard import SourceGuard
        guard = SourceGuard(source, project.root)
        guard.freeze()
    try:
        yield before
        after = binding(project, spec, runner)
        if any(before[k] != after[k] for k in ("spec_sha256", "inputs", "code", "environment")):
            raise ExecutionError("inputs, code or environment changed during execution")
    finally:
        if guard:
            restored = guard.finish()
            if any(restored[k] for k in ("restored", "added", "errors")):
                raise ExecutionError(f"original materials changed during execution: {restored}")


def run_adapter(project, spec, runner=None):
    """Python runner(project, spec) -> result dict, or any declared command array."""
    if runner is not None:
        return runner(project, spec), {"adapter": "python_callable"}
    if spec.get("runner"):
        import models
        target = spec["runner"]
        path, name = target.rsplit(":", 1)
        path = Path(path)
        target = str(path if path.is_absolute() else project.root / path) + ":" + name
        return models._load_callable(target, "runner")(project, spec), {"adapter": target}
    executor = spec.get("executor") or {}
    command = executor.get("command")
    if not isinstance(command, list) or not command or any(not isinstance(s, str) for s in command):
        raise ExecutionError("external models need an explicit Python runner or command array executor")
    if not executor.get("code") or not executor.get("result"):
        raise ExecutionError("command executors must declare code and a JSON result path")
    result_path = C.protect_output(project, executor["result"])
    protected_paths = {str(Path(project.root / i["dataset"]).resolve()) for i in spec["inputs"]}
    protected_paths.update(str(p) for p in code_paths(project, spec))
    if str(result_path) in protected_paths:
        raise ExecutionError("native result path overlaps input/code")
    old = (C.file_sha256(result_path), result_path.stat().st_mtime_ns) if result_path.is_file() else None
    started = time.monotonic()
    proc = subprocess.run(command, cwd=project.root, shell=False, capture_output=True,
                          timeout=executor.get("timeout_seconds") or spec.get("budget_seconds") or None)
    import base64,hashlib
    receipt = {"command": command, "exit_code": proc.returncode,
               "stdout":proc.stdout.decode("utf-8",errors="backslashreplace"),"stderr":proc.stderr.decode("utf-8",errors="backslashreplace"),
               "raw_logs":{name:{"base64":base64.b64encode(raw).decode("ascii"),"sha256":hashlib.sha256(raw).hexdigest()} for name,raw in (("stdout",proc.stdout),("stderr",proc.stderr))},
               "elapsed_s": time.monotonic() - started}
    if proc.returncode:
        raise ExecutionError(f"adapter failed: {receipt}")
    if not result_path.is_file() or old == (C.file_sha256(result_path), result_path.stat().st_mtime_ns):
        raise ExecutionError("adapter did not produce a current native result")
    import verify_dataset as VD
    def reject_constant(value):raise ExecutionError(f"native JSON contains nonfinite constant: {value}")
    result = json.loads(result_path.read_text(encoding="utf-8-sig"),object_pairs_hook=VD._pairs,parse_constant=reject_constant)
    if not isinstance(result,dict):raise ExecutionError("native result must be a JSON object")
    result.update(native_path=str(result_path), native_sha256=C.file_sha256(result_path))
    return result, receipt
