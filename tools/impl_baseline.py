#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Record the concrete baseline / delivery fingerprint of this repository.

Used for T01 (freeze the pre-change baseline) and again for T36 (prove the
final tree, the packaged ``.skill`` and the recorded hashes agree).

    python tools/impl_baseline.py                 # write the baseline record
    python tools/impl_baseline.py --out path.json
    python tools/impl_baseline.py --compare a.json # exit 1 when the tree moved

The record contains only facts that can be recomputed: the git commit, the
dirty-file list, a SHA256 per skill source file, the packaged archive digest,
and the interpreter/package versions the suite actually ran under.  It never
claims a test passed; test results live in the log files next to it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "empirical-research-pipeline"
DIST = REPO / "dist" / "empirical-research-pipeline.skill"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
        return out.stdout.strip()
    except Exception as exc:                     # pragma: no cover - defensive
        return f"<git failed: {exc}>"


def tree_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        rel = path.relative_to(REPO).as_posix()
        out[rel] = sha256_file(path)
    return out


def env_facts() -> dict:
    facts = {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cwd": os.getcwd(),
        "env": {k: v for k, v in os.environ.items()
                if k in ("PYTHONUTF8", "PYTHONIOENCODING", "DSH_HOME")},
        "packages": {},
    }
    for name in ("pandas", "numpy", "scipy", "statsmodels", "matplotlib",
                 "fitz", "docx", "openpyxl", "PIL", "lxml", "pypdf",
                 "pdfplumber", "rapidocr_onnxruntime", "vosk", "onnxruntime",
                 "cv2"):
        try:
            mod = __import__(name)
            facts["packages"][name] = getattr(mod, "__version__", "?")
        except Exception:
            facts["packages"][name] = None
    return facts


def external_tools() -> dict:
    out: dict[str, str | None] = {}
    for name in ("tesseract", "ffmpeg", "soffice", "pandoc", "Rscript",
                 "julia", "stata"):
        found = None
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            for ext in ("", ".exe", ".bat", ".cmd"):
                cand = Path(entry) / (name + ext)
                if cand.is_file():
                    found = str(cand)
                    break
            if found:
                break
        out[name] = found
    return out


def collect() -> dict:
    sources = tree_hashes(SKILL)
    dist = {}
    if DIST.is_file():
        dist = {
            "path": DIST.relative_to(REPO).as_posix(),
            "bytes": DIST.stat().st_size,
            "sha256": sha256_file(DIST),
            "sidecar": None,
        }
        side = DIST.with_suffix(DIST.suffix + ".sha256")
        if side.is_file():
            dist["sidecar"] = side.read_text(encoding="utf-8").strip()
    return {
        "recorded_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(
                timespec="seconds"),
        "git": {
            "commit": git("rev-parse", "HEAD"),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": [ln for ln in git("status", "--porcelain=v1").splitlines()
                      if ln.strip()],
        },
        "skill_source": {"count": len(sources), "sha256": sources},
        "dist": dist,
        "environment": env_facts(),
        "external_tools": external_tools(),
    }


def compare(old_path: Path) -> int:
    old = json.loads(old_path.read_text(encoding="utf-8"))
    new = collect()
    changed = sorted(
        k for k in set(old["skill_source"]["sha256"]) |
        set(new["skill_source"]["sha256"])
        if old["skill_source"]["sha256"].get(k) != new["skill_source"]["sha256"].get(k))
    if changed:
        print(f"FAIL: {len(changed)} skill source file(s) differ from the record")
        for k in changed[:40]:
            print("  changed:", k)
        return 1
    print(f"OK: {new['skill_source']['count']} skill source files match "
          f"{old_path.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None,
                    help="target JSON (default docs/implementation/verification/"
                         "baseline/baseline.json)")
    ap.add_argument("--compare", default=None,
                    help="compare the current tree against a previous record")
    args = ap.parse_args(argv)
    if args.compare:
        return compare(Path(args.compare))
    out = Path(args.out) if args.out else (
        REPO / "docs" / "implementation" / "verification" / "baseline" /
        "baseline.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    record = collect()
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"wrote {out.relative_to(REPO) if out.is_relative_to(REPO) else out}")
    print(f"  commit     {record['git']['commit'][:12]}")
    print(f"  skill files {record['skill_source']['count']}")
    print(f"  dist       {record['dist'].get('sha256', '-')[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
