# -*- coding: utf-8 -*-
"""Fault injection and scale helpers for the research pipeline's tests.

These helpers exist so failure scenarios can be *observed* instead of asserted
from imagination.  They are test instruments: nothing here is used by the
production stages and nothing here pretends the pipeline is fault tolerant.
The point is the opposite - to make the pipeline fail in a controlled, real
way and then look at what it left behind.

``disk_full(path, after_bytes=None)``
    A context manager that turns every write whose destination is ``path`` (a
    file or a directory) into a *real truncated write*: a prefix of the payload
    is written to the destination with the genuine ``os.write`` call, then
    ``OSError(errno.ENOSPC)`` is raised.  The failure therefore always leaves a
    half-written file behind; it is never a bare ``raise``.

    Three write primitives are intercepted:

    * ``os.replace(src, dst)`` - the atomic-publish step used by
      ``txn._write_atomic``.  The destination is truncated to a prefix of
      ``src`` and the error is raised; ``src`` is left in place so the caller's
      own cleanup still runs.  This models a publisher that wrote straight to
      the final path and died mid-write, which is exactly the hazard the
      temp-file + rename protocol exists to prevent.
    * ``pathlib.Path.write_bytes`` / ``pathlib.Path.write_text`` - direct,
      non-atomic writers.

    Writes that bypass these primitives (for example a ledger appended through
    ``open(path, "a")``) are *not* intercepted; use :func:`crash_at` with a
    callable step for those.  The context manager is single-threaded and
    in-process only.

``crash_at(step, counter=1)``
    A hook that calls ``os._exit(code)`` while the run is at a named write
    point.  Use it inside a child process (it kills the *current* process, so
    calling it from the test runner would kill the runner)::

        with faults.crash_at("pointer", 1, marker="crash.json"):
            transaction.commit()

    ``step`` is one of ``"replace"``, ``"pointer"``, ``"manifest"``,
    ``"objects"``, ``"staging"``, ``"write"``, ``"any"`` or a callable
    ``predicate(destination) -> bool``.  ``counter`` selects the n-th matching
    call (1-based).  ``when="before"`` (default) dies *before* the operation is
    performed, ``when="after"`` dies after it.  ``marker`` writes a small JSON
    receipt with the real crash point just before exiting, so the parent can
    prove the child reached that point instead of guessing from an exit code.

``big_csv(path, rows, cols=6, seed=1)``
    Streams a deterministic synthetic CSV (one row at a time) and returns the
    number of data rows written.  ``case_id`` is ``C{i:07d}`` (0-based) and the
    last column ``y`` is a linear combination of the ``x`` columns plus noise.
    File size is proportional to ``rows``; memory use is constant.

``kill_process(cmd, after_seconds)``
    Starts ``cmd``, force-kills it after ``after_seconds`` (if it is still
    alive) and returns the exit code.  A child that finished on its own is
    reported with its own code.

``files_identical(a, b)``
    SHA-256 content comparison; ``False`` when either side is missing.
"""
from __future__ import annotations

import csv
import errno
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

__all__ = ["ENOSPC", "disk_full", "crash_at", "big_csv", "kill_process",
           "files_identical"]

ENOSPC = errno.ENOSPC

_CHUNK = 1 << 20


# ---------------------------------------------------------------------------
# small primitives
# ---------------------------------------------------------------------------
def _sha256_file(path, chunk: int = _CHUNK) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def files_identical(a, b) -> bool:
    """True when both paths are files with identical bytes (SHA-256)."""
    try:
        pa, pb = Path(a), Path(b)
        if not pa.is_file() or not pb.is_file():
            return False
        if pa.stat().st_size != pb.stat().st_size:
            return False
        return _sha256_file(pa) == _sha256_file(pb)
    except OSError:
        return False


_BINARY = getattr(os, "O_BINARY", 0)     # Windows: never translate \n -> \r\n


def _write_prefix(target, data: bytes, count: int) -> int:
    """Write exactly ``count`` bytes of ``data`` to ``target`` (real I/O)."""
    full = Path(target)
    parent = full.parent
    if str(parent):
        parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(os.fspath(full),
                 os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY, 0o666)
    written = 0
    try:
        block = memoryview(data)[:count]
        while written < len(block):
            written += os.write(fd, block[written:])
        os.fsync(fd)                 # the prefix really reaches the disk
    finally:
        os.close(fd)
    return written


def _normalise(target) -> Path:
    try:
        return Path(target).resolve()
    except OSError:                  # pragma: no cover - exotic paths
        return Path(os.path.abspath(os.fspath(target)))


class _PatchSet:
    """Save/restore the three write primitives that get monkeypatched."""

    _ATTRS = (("replace", os, "replace"),
              ("write_bytes", Path, "write_bytes"),
              ("write_text", Path, "write_text"))

    def __init__(self):
        self._saved: dict[str, tuple] = {}

    def install(self, *, replace, write_bytes, write_text) -> None:
        if self._saved:              # pragma: no cover - nesting guard
            raise RuntimeError("write primitives are already patched")
        self._saved = {"replace": (os, "replace", os.replace),
                       "write_bytes": (Path, "write_bytes", Path.write_bytes),
                       "write_text": (Path, "write_text", Path.write_text)}
        os.replace = replace
        Path.write_bytes = write_bytes
        Path.write_text = write_text

    def original(self, name: str):
        return self._saved[name][2]

    def restore(self) -> None:
        for name, (owner, attr, value) in self._saved.items():
            setattr(owner, attr, value)
        self._saved = {}


class _Interceptor:
    """Monkeypatch context manager with a shared save/restore protocol."""

    def __init__(self) -> None:
        self._patches = _PatchSet()

    def __enter__(self):
        outer = self

        def replace(src, dst, *args, **kwargs):
            return outer._handle_replace(src, dst, args, kwargs)

        def write_bytes(path_self, data, *args, **kwargs):
            return outer._handle_direct(path_self, data, "write_bytes",
                                        args, kwargs)

        def write_text(path_self, data, *args, **kwargs):
            return outer._handle_direct(path_self, data, "write_text",
                                        args, kwargs)

        self._patches.install(replace=replace, write_bytes=write_bytes,
                              write_text=write_text)
        return self

    def __exit__(self, *exc_info):
        self._patches.restore()
        return False

    # -- dispatch ----------------------------------------------------------
    def _handle_replace(self, src, dst, args, kwargs):
        raise NotImplementedError

    def _handle_direct(self, path_self, data, kind, args, kwargs):
        raise NotImplementedError

    def _original(self, name):
        return self._patches.original(name)

    @staticmethod
    def _encode_text(data, args, kwargs) -> bytes:
        encoding = kwargs.get("encoding")
        if encoding is None and args:
            encoding = args[0]
        return str(data).encode(encoding or "utf-8")


# ---------------------------------------------------------------------------
# disk full
# ---------------------------------------------------------------------------
class disk_full(_Interceptor):
    """Make writes under ``path`` leave a torn file and raise ``ENOSPC``.

    Parameters
    ----------
    path:
        File or directory; any destination that is the path itself or lives
        below it is considered "on the full disk".
    after_bytes:
        How many bytes to write before failing.  ``None`` (default) writes
        ``max(1, len // 2)`` bytes, i.e. a genuinely half-written file.

    Attributes (evidence for assertions)
    -------------------------------------
    ``records``   one dict per injected failure: target, source primitive,
                  requested bytes, bytes actually written
    ``failures``  number of injected ENOSPC errors
    ``attempts``  number of intercepted writes that matched the root
    """

    def __init__(self, path, after_bytes: int | None = None):
        super().__init__()
        self.root = _normalise(path)
        if after_bytes is not None and int(after_bytes) < 0:
            raise ValueError("after_bytes must be >= 0")
        self.after_bytes = None if after_bytes is None else int(after_bytes)
        self.records: list[dict] = []
        self.failures = 0
        self.attempts = 0

    # -- matching ----------------------------------------------------------
    def _matches(self, target) -> bool:
        full = _normalise(target)
        return full == self.root or self.root in full.parents

    def _limit(self, size: int) -> int:
        if self.after_bytes is None:
            return max(1, size // 2) if size else 0
        return min(self.after_bytes, size)

    def _error(self, target) -> OSError:
        return OSError(ENOSPC, os.strerror(ENOSPC), os.fspath(target))

    def _inject(self, target, data: bytes, source: str) -> None:
        count = self._limit(len(data))
        written = _write_prefix(target, data, count)
        self.failures += 1
        self.records.append({"target": os.fspath(target), "source": source,
                             "requested_bytes": len(data),
                             "written_bytes": written,
                             "after_bytes": self.after_bytes})

    # -- patched primitives ------------------------------------------------
    def _handle_replace(self, src, dst, args, kwargs):
        if not self._matches(dst):
            return self._original("replace")(src, dst, *args, **kwargs)
        self.attempts += 1
        try:
            data = Path(src).read_bytes()
        except OSError:              # pragma: no cover - unreadable temp file
            data = b""
        # Leave ``src`` untouched: the caller's cleanup owns it.  The torn file
        # is the destination, which is what a crashing writer would leave.
        self._inject(dst, data, source="os.replace")
        raise self._error(dst)

    def _handle_direct(self, path_self, data, kind, args, kwargs):
        if not self._matches(path_self):
            return self._original(kind)(path_self, data, *args, **kwargs)
        self.attempts += 1
        raw = (self._encode_text(data, args, kwargs)
               if kind == "write_text" else bytes(data))
        self._inject(path_self, raw, source=f"Path.{kind}")
        raise self._error(path_self)


# ---------------------------------------------------------------------------
# crash at a named write point
# ---------------------------------------------------------------------------
class crash_at(_Interceptor):
    """Kill the *current* process with ``os._exit`` at a named write point.

    ``step`` may be one of ``"replace"``, ``"pointer"`` (the publish pointer
    ``published.json``), ``"manifest"`` (``commits/``), ``"objects"``
    (``objects/``), ``"staging"``, ``"write"`` (only direct
    ``Path.write_bytes``/``write_text``), ``"any"``, or a callable predicate
    receiving the destination path.

    ``counter`` is the 1-based n-th matching call.  ``when`` decides whether
    the crash happens before or after that operation.  ``marker`` (a path)
    receives a JSON receipt right before ``os._exit``.
    """

    STEPS = ("replace", "pointer", "manifest", "objects", "staging", "write",
             "any")

    def __init__(self, step, counter: int = 1, *, code: int = 9,
                 when: str = "before", marker=None):
        super().__init__()
        if not callable(step) and step not in self.STEPS:
            raise ValueError(f"unknown step {step!r}; expected one of "
                             f"{self.STEPS} or a callable")
        if int(counter) < 1:
            raise ValueError("counter is 1-based")
        if when not in ("before", "after"):
            raise ValueError("when must be 'before' or 'after'")
        self.step = step
        self.counter = int(counter)
        self.code = int(code)
        self.when = when
        self.marker = marker
        self.matches = 0

    # -- matching ----------------------------------------------------------
    def _matches(self, target, kind: str) -> bool:
        if callable(self.step):
            return bool(self.step(target))
        name = Path(target).name
        parts = Path(target).parts
        if self.step == "any":
            return True
        if self.step == "replace":
            return kind == "replace"
        if self.step == "write":
            return kind == "write"
        if self.step == "pointer":
            return name == "published.json"
        if self.step == "manifest":
            return "commits" in parts
        if self.step == "objects":
            return "objects" in parts
        if self.step == "staging":
            return "staging" in parts
        raise ValueError(f"unknown step {self.step!r}")   # pragma: no cover

    def _hit(self, target, kind: str) -> bool:
        if not self._matches(target, kind):
            return False
        self.matches += 1
        return self.matches == self.counter

    def _die(self, target, kind: str) -> None:
        if self.marker:
            payload = json.dumps({"step": self.step if isinstance(
                self.step, str) else "<callable>", "counter": self.counter,
                "kind": kind, "target": os.fspath(target),
                "pid": os.getpid(), "code": self.code},
                ensure_ascii=False).encode("utf-8")
            marker = Path(self.marker)
            marker.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(os.fspath(marker),
                         os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY,
                         0o666)
            try:
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:            # pragma: no cover - streams already gone
            pass
        os._exit(self.code)

    # -- patched primitives ------------------------------------------------
    def _handle_replace(self, src, dst, args, kwargs):
        kind = "replace"
        hit = self._hit(dst, kind)
        if hit and self.when == "before":
            self._die(dst, kind)
        result = self._original("replace")(src, dst, *args, **kwargs)
        if hit and self.when == "after":
            self._die(dst, kind)
        return result

    def _handle_direct(self, path_self, data, kind, args, kwargs):
        direct = "write"
        hit = self._hit(path_self, direct)
        if hit and self.when == "before":
            self._die(path_self, direct)
        result = self._original(kind)(path_self, data, *args, **kwargs)
        if hit and self.when == "after":
            self._die(path_self, direct)
        return result


# ---------------------------------------------------------------------------
# scale fixture
# ---------------------------------------------------------------------------
def big_csv(path, rows: int = 200_000, cols: int = 6, seed: int = 1) -> int:
    """Stream a synthetic CSV to ``path`` and return the data-row count.

    Columns: ``case_id`` (``C{i:07d}``, 0-based), ``group``
    (``control``/``treatment``), ``cols - 3`` numeric ``x`` columns and a
    numeric ``y`` that is a linear combination of them plus noise.  With
    ``cols == 2`` the file is ``case_id,y``.

    The file is written one row at a time, so memory stays constant regardless
    of ``rows``.  Values are deterministic for a given ``seed``.
    """
    rows = int(rows)
    cols = int(cols)
    if rows < 0:
        raise ValueError("rows must be >= 0")
    if cols < 2:
        raise ValueError("cols must be >= 2")
    rng = random.Random(seed)
    if cols == 2:
        header = ["case_id", "y"]
        x_names: list[str] = []
    else:
        # case_id + group + (cols - 3) x-columns + y == cols columns
        x_names = [f"x{i}" for i in range(1, cols - 2)]
        header = ["case_id", "group", *x_names, "y"]

    target = Path(path)
    if str(target.parent):
        target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for i in range(rows):
            xs = [rng.gauss(0.0, 1.0) for _ in x_names]
            y = (1.25 * xs[0] if xs else 0.0)
            if len(xs) > 1:
                y += 0.5 * xs[1]
            y += rng.gauss(0.0, 0.25)
            base = [f"C{i:07d}"]
            if cols > 2:
                base.append("treatment" if i % 2 else "control")
            row = base + [f"{value:.4f}" for value in xs] + [f"{y:.4f}"]
            writer.writerow(row)
    return rows


# ---------------------------------------------------------------------------
# process helpers
# ---------------------------------------------------------------------------
def _argv(cmd) -> list[str]:
    if isinstance(cmd, (str, bytes, os.PathLike)):
        import shlex
        return shlex.split(os.fspath(cmd), posix=(os.name != "nt"))
    return [os.fspath(part) for part in cmd]


def kill_process(cmd, after_seconds: float = 1.0) -> int:
    """Run ``cmd``, force-kill it after ``after_seconds``, return its code."""
    args = _argv(cmd)
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        return proc.wait(timeout=max(float(after_seconds), 0.001))
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except OSError:                  # pragma: no cover - already gone
        pass
    try:
        return proc.wait(timeout=30)
    except subprocess.TimeoutExpired:            # pragma: no cover
        proc.terminate()
        return proc.wait(timeout=30)
