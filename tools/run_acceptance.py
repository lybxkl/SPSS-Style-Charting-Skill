"""Execute the real unittest suite and retain per-test observations and hashes.

This receipt proves a specific execution scope, not that a hand-written mapping
exhausts a research requirement. Mapping review and actual visual review remain
explicit responsibilities. Source files are not accepted as execution receipts.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def instant():
    return datetime.now(timezone.utc).isoformat()


def process_memory():
    """Real process counters; peak is cumulative for this Python process."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in
                ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                 "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        call = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        call.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        call.restype = wintypes.BOOL
        if call(wintypes.HANDLE(-1), ctypes.byref(counters), counters.cb):
            return {"working_set_bytes": counters.WorkingSetSize, "process_peak_working_set_bytes": counters.PeakWorkingSetSize}
    return {"measurement": "unavailable"}


def observed(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"nonfinite": repr(value)}
    if isinstance(value, dict):
        return {str(k): observed(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [observed(v) for v in value]
    return {"type": type(value).__name__, "repr": repr(value)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--map", dest="mapping")
    ap.add_argument("--pattern", default="test_*.py")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "empirical-research-pipeline/scripts")]
    sources = sorted([*ROOT.glob("empirical-research-pipeline/scripts/*.py"), *ROOT.glob("tests/*.py"), *ROOT.glob("tools/*.py")])
    frozen = {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}
    started = instant()
    mapping_path = Path(args.mapping).resolve() if args.mapping else None
    frozen_mapping = {"path": mapping_path.relative_to(ROOT).as_posix(), "sha256": sha(mapping_path)} if mapping_path else None
    tests, assertions = {}, {}
    originals = {}
    names = ("assertEqual", "assertNotEqual", "assertTrue", "assertFalse", "assertAlmostEqual",
             "assertGreater", "assertGreaterEqual", "assertLess", "assertLessEqual", "assertIn", "assertNotIn", "assertIsNone")
    for name in names:
        original = getattr(unittest.TestCase, name)
        originals[name] = original
        def capture(self, *values, _name=name, _original=original, **kwargs):
            assertions.setdefault(self.id(), []).append({"assertion": _name, "values": observed(values), "options": observed(kwargs)})
            return _original(self, *values, **kwargs)
        setattr(unittest.TestCase, name, capture)

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            tests[test.id()] = {"status": "running", "started_at": instant(), "memory_before": process_memory()}
            self._start = time.monotonic()
            super().startTest(test)
        def stopTest(self, test):
            tests[test.id()].update(finished_at=instant(), elapsed_seconds=time.monotonic()-self._start,
                                    memory_after=process_memory(),
                                    observations=assertions.get(test.id(), []))
            super().stopTest(test)
        def addSuccess(self, test):
            tests[test.id()]["status"] = "passed"
            super().addSuccess(test)
        def addSubTest(self, test, subtest, err):
            if err is not None:
                tests[test.id()].update(status="failed", detail=self._exc_info_to_string(err, test))
            super().addSubTest(test, subtest, err)
        def addFailure(self, test, err):
            tests[test.id()].update(status="failed", detail=self._exc_info_to_string(err, test))
            super().addFailure(test, err)
        def addError(self, test, err):
            tests.setdefault(test.id(), {}).update(status="error", detail=self._exc_info_to_string(err, test))
            super().addError(test, err)
        def addSkip(self, test, reason):
            tests[test.id()].update(status="skipped", reason=reason)
            super().addSkip(test, reason)
        def addExpectedFailure(self, test, err):
            tests[test.id()].update(status="expected_failure")
            super().addExpectedFailure(test, err)
        def addUnexpectedSuccess(self, test):
            tests[test.id()].update(status="unexpected_success")
            super().addUnexpectedSuccess(test)

    try:
        suite = unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=args.pattern)
        with open(out/"execution.log", "w", encoding="utf-8") as stream:
            command = [sys.executable, str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])]
            stream.write("command: " + json.dumps(command, ensure_ascii=False) + "\n")
            stream.flush()
            result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Result).run(suite)
    finally:
        for name, original in originals.items():
            setattr(unittest.TestCase, name, original)
    after = {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}
    receipt = {"schema_version": 1, "producer": "tools/run_acceptance.py", "started_at": started, "finished_at": instant(),
               "command": command, "environment": {"python": sys.version, "executable": sys.executable, "platform": platform.platform()},
               "oracle_files": {p:h for p,h in frozen.items() if p.startswith("tests/")},
               "production_before": {p:h for p,h in frozen.items() if not p.startswith("tests/")},
               "production_after": {p:h for p,h in after.items() if not p.startswith("tests/")},
               "sources_unchanged": frozen == after, "tests": tests, "tests_run": result.testsRun,
               "execution_log": "execution.log", "execution_log_sha256": sha(out/"execution.log"),
               "result": "passed" if result.wasSuccessful() and not result.skipped and frozen == after else "not_passed"}
    if args.mapping:
        receipt["mapping"] = frozen_mapping
        if sha(mapping_path) != frozen_mapping["sha256"]:
            receipt["result"] = "not_passed"
    (out/"execution.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                      "skipped": len(result.skipped), "sources_unchanged": frozen == after, "receipt": str(out/"execution.json")}))
    return 0 if receipt["result"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
