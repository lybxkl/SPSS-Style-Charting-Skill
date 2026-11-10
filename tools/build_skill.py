#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repackage ``empirical-research-pipeline/`` into ``dist/*.skill``.

The ``.skill`` artifact is a plain zip whose entries are rooted at the skill
directory, so it can be dropped into any client that imports skill packages
(and can be unzipped straight into a ``skills/`` folder).  Nothing but
``SKILL.md``, ``assets/``, ``references/`` and ``scripts/`` is packaged:
``evals/`` holds development prompts and never ships.

Usage (from the repository root):

    python tools/build_skill.py            # rewrite dist/*.skill
    python tools/build_skill.py --check    # exit 1 if dist is stale
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "empirical-research-pipeline"
SKILL_NAME = SKILL_DIR.name
DIST = REPO / "dist" / f"{SKILL_NAME}.skill"
INCLUDE = ("SKILL.md", "assets", "profiles", "references", "scripts")
SKIP_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def iter_files() -> list[Path]:
    out: list[Path] = []
    for name in INCLUDE:
        target = SKILL_DIR / name
        if target.is_file():
            out.append(target)
            continue
        if not target.is_dir():
            raise SystemExit(f"missing {target}")
        for path in sorted(target.rglob("*")):
            if not path.is_file():
                continue
            if path.name in SKIP_NAMES or path.suffix in SKIP_SUFFIX:
                continue
            if any(part in SKIP_NAMES for part in path.parts):
                continue
            out.append(path)
    return out


def build(path: Path, files: list[Path]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            arc = f"{SKILL_NAME}/{f.relative_to(SKILL_DIR).as_posix()}"
            data = f.read_bytes()
            digest.update(arc.encode("utf-8"))
            digest.update(data)
            # fixed timestamp so rebuilds are byte-stable
            info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, data)
    return digest.hexdigest()


def archive_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as zf:
        for name in sorted(zf.namelist()):
            digest.update(name.encode("utf-8"))
            digest.update(zf.read(name))
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 when dist is out of date")
    args = ap.parse_args(argv)

    files = iter_files()
    if args.check:
        if not DIST.is_file():
            print(f"FAIL: {DIST} is missing")
            return 1
        with zipfile.ZipFile(DIST) as zf:
            inside = {n for n in zf.namelist()}
        expected = {f"{SKILL_NAME}/{f.relative_to(SKILL_DIR).as_posix()}" for f in files}
        missing = expected - inside
        extra = inside - expected
        stale = [f for f in files
                 if f"{SKILL_NAME}/{f.relative_to(SKILL_DIR).as_posix()}" in inside
                 and zipfile.ZipFile(DIST).read(
                     f"{SKILL_NAME}/{f.relative_to(SKILL_DIR).as_posix()}") != f.read_bytes()]
        if missing or extra or stale:
            for label, items in (("missing", missing), ("unexpected", extra), ("stale", stale)):
                for it in sorted(items):
                    print(f"{label}: {it}")
            return 1
        print(f"OK: {DIST.name} matches the source tree ({len(files)} files)")
        sidecar = DIST.with_suffix(DIST.suffix + ".sha256")
        if not sidecar.is_file():
            print(f"FAIL: {sidecar.name} is missing (run without --check first)")
            return 1
        if sidecar.read_text(encoding="utf-8").split("  ")[0].strip() != archive_digest(DIST):
            print(f"FAIL: {sidecar.name} does not match the archive")
            return 1
        return 0

    digest = build(DIST, files)
    print(f"wrote {DIST}  ({len(files)} files, {DIST.stat().st_size} bytes)")
    print(f"content-sha256: {digest}")
    assert digest == archive_digest(DIST), "archive is not byte-stable"
    # The digest is the only way a user can tell whether the .skill they
    # imported is the one CI built: the file name and mtime prove nothing.
    DIST.with_suffix(DIST.suffix + ".sha256").write_text(
        f"{digest}  {DIST.name}\n", encoding="utf-8")
    print(f"wrote {DIST.name}.sha256")
    return 0


if __name__ == "__main__":
    sys.exit(main())