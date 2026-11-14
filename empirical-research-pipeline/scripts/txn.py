# -*- coding: utf-8 -*-
"""Transactional publishing: staging, immutable manifests, publish pointer, locks.

Research outputs are produced by many steps and read by many consumers.  This
module makes "publish" a real operation instead of a sequence of overwrites:

1. every run gets its own id and its own staging directory;
2. outputs are written to staging and hashed;
3. before commit the *inputs* are re-hashed and compared with the snapshot taken
   at run start (a run that raced an edit fails instead of publishing);
4. staged files are stored content-addressed (``objects/<sha256>``), so writing
   one file is atomic and two runs cannot corrupt each other;
5. a commit manifest lists every target, hash and the parent commit;
6. only after the manifest verifies does ``published.json`` (the pointer) move,
   in one atomic replace;
7. readers resolve through the pointer, so they never observe half a run.

Locks guard mutations of the same logical resource.  Failure, cancellation,
timeout and crash leave the pointer alone; the failed run keeps its own record.

CLI::

    python txn.py --root . status
    python txn.py --root . verify --commit <id>
    python txn.py --root . recover --run <id>
    python txn.py --root . read --target results/table1.csv
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import shutil
import socket
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Iterable, Mapping

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import contract_v2 as C

POINTER = "published.json"


class TxnError(Exception):
    pass


class PublishError(TxnError):
    """Staged outputs are incomplete or inconsistent; nothing was published."""


class InputChanged(TxnError):
    """An input changed between run start and commit."""


class ParentVersionError(TxnError):
    """The parent version a patch/commit expected is no longer current."""


class LockError(TxnError):
    pass


def _producer() -> dict:
    return C.producer_for("txn", version="2.0", module_file=__file__)


def _sha_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        if os.name == "nt":                       # pragma: no cover - windows
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return ctypes.get_last_error() == 5  # access denied is not proof of death
            try:
                code = wintypes.DWORD()
                return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
            finally:
                kernel.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:                             # pragma: no cover
        return False


class Lock:
    """Cross-process exclusive lock backed by an ``O_EXCL`` lock file."""

    def __init__(self, project: C.Project, name: str, *, timeout: float = 10.0,
                 stale_after: float = 3600.0):
        self.project = project
        self.name = name
        self.timeout = timeout
        self.stale_after = stale_after
        safe = name if re.fullmatch(r"[A-Za-z0-9_.-]+", name) else C.canonical_hash(name)
        self.path = project.path("locks", f"{safe}.lock")
        self.taken = False
        self.token = uuid.uuid4().hex

    def _read(self) -> dict | None:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _stale(self) -> bool:
        meta = self._read()
        if not meta:
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                return True
            return age > self.stale_after
        if meta.get("host") not in (None, "", socket.gethostname()):
            return False  # a local PID cannot establish a remote owner's death
        return not _pid_alive(int(meta.get("pid", 0)))

    def acquire(self) -> "Lock":
        deadline = time.time() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._stale():
                    try:
                        os.unlink(self.path)
                    except OSError:
                        pass
                    continue
                if time.time() >= deadline:
                    holder = self._read() or {}
                    raise LockError(
                        f"lock {self.name!r} is held by run "
                        f"{holder.get('run_id')} pid {holder.get('pid')}")
                time.sleep(0.05)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"name": self.name, "pid": os.getpid(),
                           "host": socket.gethostname(), "at": time.time(),
                           "token": self.token,
                           "run_id": os.environ.get("DSH_RUN_ID", "")}, fh)
            self.taken = True
            return self

    def release(self) -> None:
        if self.taken:
            try:
                if (self._read() or {}).get("token") == self.token:
                    os.unlink(self.path)
            except OSError:
                pass
            self.taken = False

    def __enter__(self) -> "Lock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


class Transaction:
    """One publishable run."""

    def __init__(self, project: C.Project, *, run_id: str | None = None,
                 label: str = "run", parent: str | None = None):
        self.project = project
        self.run_id = run_id or (
            time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
        self.label = label
        self.staging = project.path("runs", self.run_id, "staging")
        self.run_dir = project.path("runs", self.run_id)
        self.objects = project.path("objects")
        self.commits = project.path("commits")
        self.staged: dict[str, dict] = {}
        self.inputs: dict[str, str] = {}
        self.code: dict[str, str] = {}
        self.environment: dict = {}
        self.parent = parent
        self.expected_parents: dict[str, str] = {}
        self.base_targets = published_targets(project)
        self._state = "open"

    # -- staging -----------------------------------------------------------
    def _target(self, rel: str) -> tuple[str, Path]:
        # Test both path grammars: a Windows drive/UNC path must also be
        # rejected when an archive or fixture is inspected on another OS.
        from pathlib import PureWindowsPath
        normalized = str(rel).replace("\\", "/")
        path = Path(normalized)
        if (not normalized or path.is_absolute() or PureWindowsPath(normalized).drive
                or any(part in ("..", ".") for part in normalized.split("/"))
                or ":" in normalized or "\x00" in normalized):
            raise TxnError(f"output must be a confined relative path: {rel!r}")
        base = self.staging.resolve()
        target = (base / path).resolve()
        if target == base or base not in target.parents:
            raise TxnError(f"output escapes this run's staging: {rel!r}")
        return path.as_posix(), target

    def stage(self, rel: str, data: bytes | str) -> dict:
        if self._state != "open":
            raise TxnError(f"run {self.run_id} is {self._state}")
        raw = data.encode("utf-8") if isinstance(data, str) else data
        rel, target = self._target(rel)
        _write_atomic(target, raw)
        entry = {"target": rel, "sha256": _sha_bytes(raw),
                 "bytes": len(raw)}
        self.staged[entry["target"]] = entry
        self.expected_parents.setdefault(rel, self.base_targets.get(rel, ""))
        return entry

    def stage_json(self, rel: str, obj) -> dict:
        return self.stage(rel, json.dumps(obj, ensure_ascii=False, indent=1) + "\n")

    def stage_file(self, rel: str, src: str | os.PathLike) -> dict:
        return self.stage(rel, Path(src).read_bytes())

    # -- binding -----------------------------------------------------------
    def snapshot_inputs(self, paths: Iterable[str | os.PathLike]) -> dict[str, str]:
        for p in paths:
            path = Path(p)
            rel = path.as_posix()
            if not path.is_file():
                raise InputChanged(f"declared input does not exist: {rel}")
            self.inputs[rel] = C.file_sha256(path)
        return dict(self.inputs)

    def bind_code(self, paths: Iterable[str | os.PathLike]) -> dict[str, str]:
        for p in paths:
            path = Path(p)
            if not path.is_file():
                raise TxnError(f"declared code file does not exist: {p}")
            self.code[Path(p).as_posix()] = C.file_sha256(path)
        return dict(self.code)

    def bind_environment(self, env: Mapping) -> None:
        self.environment = dict(env)

    def expect_parent(self, target: str, sha256: str | None) -> None:
        self.expected_parents[target.replace("\\", "/")] = sha256 or ""

    def _check_parents(self) -> None:
        published = read_manifest(self.project)
        current = {e["target"]: e["sha256"]
                   for e in (published["entries"] if published else [])}
        for target, expected in self.expected_parents.items():
            actual = current.get(target)
            if (actual or "") != (expected or "") and actual != self.staged.get(target, {}).get("sha256"):
                raise ParentVersionError(
                    f"{target}: expected parent {expected or '<absent>'}, found "
                    f"{actual or '<absent>'} - another run published first")

    def _check_inputs(self) -> None:
        for rel, want in {**self.inputs, **self.code}.items():
            path = Path(rel)
            if not path.is_file():
                raise InputChanged(f"input disappeared during the run: {rel}")
            got = C.file_sha256(path)
            if got != want:
                raise InputChanged(
                    f"input changed during the run: {rel} ({want[:12]} -> "
                    f"{got[:12]}); refusing to publish results computed from "
                    f"stale inputs")

    def _store_object(self, data: bytes) -> str:
        digest = _sha_bytes(data)
        target = self.objects / digest
        if not target.is_file():
            _write_atomic(target, data)
        elif C.file_sha256(target) != digest:      # pragma: no cover - corruption
            raise PublishError(f"content store object {digest[:12]} is corrupt")
        return digest

    # -- commit ------------------------------------------------------------
    def commit(self, *, message: str = "") -> dict:
        # Check the parent and move the pointer in one critical section.
        with Lock(self.project, "project-publish", timeout=60):
            return self._commit_locked(message=message)

    def _commit_locked(self, *, message: str = "") -> dict:
        if self._state != "open":
            raise TxnError(f"run {self.run_id} already {self._state}")
        self._check_parents()
        self._check_inputs()
        previous = read_manifest(self.project)
        if previous and not verify_commit(self.project):
            raise PublishError("previous published manifest/object is corrupt")
        merged = {e["target"]: dict(e) for e in (previous or {}).get("entries", [])}
        entries: list[dict] = []
        for rel in sorted(self.staged):
            _, src = self._target(rel)
            if not src.is_file():
                raise PublishError(
                    f"staged output is missing at commit time: {rel} "
                    f"(nothing published)")
            data = src.read_bytes()
            if _sha_bytes(data) != self.staged[rel]["sha256"]:
                raise PublishError(f"staged output changed after staging: {rel}")
            self._store_object(data)
            merged[rel] = {"target": rel, "sha256": self.staged[rel]["sha256"], "bytes": len(data)}
        if not self.staged:
            raise PublishError("refusing to publish a run with no outputs")
        entries = [merged[key] for key in sorted(merged)]
        commit_id = C.canonical_hash({
            "entries": entries, "inputs": self.inputs, "code": self.code,
            "environment": self.environment, "parent": self.parent,
            "label": self.label,
        })[:32]
        manifest = {
            "commit": commit_id,
            "run_id": self.run_id,
            "label": self.label,
            "created_at": C._now(),
            "parent": self.parent or (read_pointer(self.project) or {}).get("commit"),
            "entries": entries,
            "inputs": dict(sorted(self.inputs.items())),
            "code": dict(sorted(self.code.items())),
            "environment": self.environment,
            "message": message,
            "producer": _producer(),
        }
        manifest["manifest_sha256"] = C.canonical_hash(manifest)
        manifest_path = self.commits / f"{commit_id}.json"
        # idempotent: identical content re-commits to the same manifest
        if manifest_path.is_file():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("entries") != entries:
                raise PublishError(f"commit id collision for {commit_id}")
            manifest = existing
        else:
            try:
                _write_atomic(manifest_path,
                              json.dumps(manifest, ensure_ascii=False,
                                         indent=1).encode("utf-8"))
            except OSError:
                # Two writers may race on the same content-addressed manifest;
                # if the other one won, adopt its file only when it is identical.
                if not manifest_path.is_file():
                    raise
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                if existing.get("entries") != entries:
                    raise PublishError(f"commit id collision for {commit_id}")
                manifest = existing
        if not verify_commit(self.project, commit_id):
            raise PublishError(f"commit {commit_id[:12]} failed verification; pointer not moved")
        pointer_path = self.project.dir / POINTER
        pointer = {
            "commit": commit_id,
            "run_id": self.run_id,
            "published_at": C._now(),
            "targets": {e["target"]: e["sha256"] for e in entries},
            "previous": (read_pointer(self.project) or {}).get("commit"),
            "producer": _producer(),
        }
        # The receipt is written BEFORE the pointer moves: if appending the
        # workflow step fails (a torn ledger line, a full disk), nothing has
        # been published yet and the previous version stays current.
        self._state = "publishing"
        record = C.make_record(
            "workflow_step", f"commit:{commit_id}:{self.run_id}",
            {"step": self.label, "scope": {"run_id": self.run_id},
             "inputs": [{"kind": "file", "id": k, "content_hash": v}
                        for k, v in sorted(self.inputs.items())],
             "outputs": [{"kind": "file", "id": e["target"],
                          "content_hash": e["sha256"]} for e in entries],
             "run_state": {"state": "completed", "exit_code": 0,
                           "started_at": manifest["created_at"]},
             "check_state": {"state": "passed", "checks": ["inputs_unchanged",
                                                           "outputs_hashed",
                                                           "manifest_verified"]}},
            producer=_producer(), status="completed")
        self.project.append("workflow_step", record, enforce_transition=False)
        self._check_inputs()
        _write_atomic(pointer_path,
                      json.dumps(pointer, ensure_ascii=False,
                                 indent=1).encode("utf-8"))
        self._state = "committed"
        return manifest

    # -- failure paths -----------------------------------------------------
    def fail(self, reason: str, *, exc: BaseException | None = None) -> dict:
        info = {"run_id": self.run_id, "state": "failed", "reason": reason,
                "at": C._now(), "staged": sorted(self.staged),
                "error": f"{type(exc).__name__}: {exc}" if exc else None}
        _write_atomic(self.run_dir / "failed.json",
                      json.dumps(info, ensure_ascii=False, indent=1).encode())
        self._state = "failed"
        return info

    def cancel(self, reason: str = "cancelled") -> dict:
        info = {"run_id": self.run_id, "state": "cancelled", "reason": reason,
                "at": C._now(), "staged": sorted(self.staged)}
        _write_atomic(self.run_dir / "cancelled.json",
                      json.dumps(info, ensure_ascii=False, indent=1).encode())
        self._state = "cancelled"
        return info

    @property
    def state(self) -> str:
        return self._state


# ---------------------------------------------------------------------------
# readers
# ---------------------------------------------------------------------------
def read_pointer(project: C.Project) -> dict | None:
    path = project.dir / POINTER
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_manifest(project: C.Project, commit: str | None = None) -> dict | None:
    pointer = read_pointer(project)
    cid = commit or (pointer or {}).get("commit")
    if not cid:
        return None
    path = project.path("commits", f"{cid}.json")
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_published(project: C.Project, target: str) -> bytes:
    manifest = read_manifest(project)
    if manifest is None:
        raise TxnError("nothing has been published yet")
    if not verify_commit(project):
        raise PublishError("published manifest or object failed integrity checks")
    target = target.replace("\\", "/")
    for entry in manifest["entries"]:
        if entry["target"] == target:
            obj = project.path("objects", entry["sha256"])
            if not obj.is_file():
                raise PublishError(f"published object missing for {target}")
            data = obj.read_bytes()
            if _sha_bytes(data) != entry["sha256"]:
                raise PublishError(f"published object corrupt for {target}")
            return data
    raise TxnError(f"{target} is not in the published manifest")


def published_targets(project: C.Project) -> dict[str, str]:
    manifest = read_manifest(project)
    if not manifest:
        return {}
    return {e["target"]: e["sha256"] for e in manifest["entries"]}


def verify_commit(project: C.Project, commit: str | None = None) -> bool:
    manifest = read_manifest(project, commit)
    if not manifest:
        return False
    if manifest.get("manifest_sha256") != C.canonical_hash({k:v for k,v in manifest.items() if k != "manifest_sha256"}):
        return False
    for entry in manifest["entries"]:
        obj = project.path("objects", entry["sha256"])
        if not obj.is_file():
            return False
        if C.file_sha256(obj) != entry["sha256"]:
            return False
    return True


def recover(project: C.Project, run_id: str) -> dict:
    """Classify an interrupted run without inventing a success."""
    run_dir = project.path("runs", run_id)
    if not run_dir.is_dir():
        raise TxnError(f"unknown run {run_id}")
    manifests = list(project.path("commits").glob("*.json"))
    committed = []
    for m in manifests:
        data = json.loads(m.read_text(encoding="utf-8"))
        if data.get("run_id") == run_id:
            committed.append(data["commit"])
    if committed:
        pointer = read_pointer(project) or {}
        published_id = pointer.get("commit")
        # Prefer the commit the pointer names, not whichever glob() listed last.
        chosen = published_id if published_id in committed else committed[-1]
        return {"run_id": run_id, "state": "committed",
                "commit": chosen,
                "published": published_id == chosen,
                "recoverable": True,
                "note": "state=committed only means a manifest exists; read "
                        "published to know whether it is the current version"}
    if (run_dir / "failed.json").is_file():
        return {"run_id": run_id, "state": "failed",
                "detail": json.loads((run_dir / "failed.json").read_text(
                    encoding="utf-8")), "recoverable": True}
    if (run_dir / "cancelled.json").is_file():
        return {"run_id": run_id, "state": "cancelled", "recoverable": True}
    staged = []
    staging = run_dir / "staging"
    if staging.is_dir():
        staged = sorted(p.relative_to(staging).as_posix()
                        for p in staging.rglob("*") if p.is_file())
    return {"run_id": run_id, "state": "interrupted", "staged": staged,
            "recoverable": bool(staged),
            "note": "no commit manifest exists, so this run never published; "
                    "its staged outputs are diagnostics, not results"}


# ---------------------------------------------------------------------------
# checkpoints
# ---------------------------------------------------------------------------
CHECKPOINT_LAYERS = ("inputs", "code", "rules", "environment", "review_version")


def checkpoint_state(checkpoint: Mapping, current: Mapping) -> dict:
    """Compare a stored checkpoint against the *current* run's bindings.

    All five layers must match.  A mismatch invalidates the checkpoint: the
    partial run may not be resumed as if the world had not moved.
    """
    data = checkpoint["data"]
    mismatches = []
    if checkpoint.get("status") != "valid":
        return {"valid": False,
                "mismatches": [{"layer": "status",
                                 "reason": f"checkpoint is {checkpoint.get('status')!r}"}],
                "layers_checked": list(CHECKPOINT_LAYERS)}
    for layer in CHECKPOINT_LAYERS:
        stored = data.get(layer)
        now = current.get(layer)
        if stored is None or now is None:
            mismatches.append({"layer": layer, "reason": "missing binding"})
            continue
        if C.canonical_hash(stored) != C.canonical_hash(now):
            mismatches.append({"layer": layer, "stored": stored, "current": now})
    return {"valid": not mismatches, "mismatches": mismatches,
            "layers_checked": list(CHECKPOINT_LAYERS)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="transactional publishing")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p_ver = sub.add_parser("verify")
    p_ver.add_argument("--commit")
    p_rec = sub.add_parser("recover")
    p_rec.add_argument("--run", required=True)
    p_read = sub.add_parser("read")
    p_read.add_argument("--target", required=True)
    args = ap.parse_args(argv)
    proj = C.Project(args.root, create=False)
    if args.cmd == "status":
        pointer = read_pointer(proj)
        manifest = read_manifest(proj)
        print(json.dumps({
            "pointer": pointer, "entries": len(manifest["entries"]) if manifest
            else 0, "verified": verify_commit(proj) if manifest else None}, ensure_ascii=False,
            indent=1))
        return 0
    if args.cmd == "verify":
        ok = verify_commit(proj, args.commit)
        print("OK" if ok else "FAIL")
        return 0 if ok else 2
    if args.cmd == "recover":
        print(json.dumps(recover(proj, args.run), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "read":
        sys.stdout.buffer.write(read_published(proj, args.target))
        return 0
    return 2


if __name__ == "__main__":            # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
