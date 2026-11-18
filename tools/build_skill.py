#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repackage ``empirical-research-pipeline/`` into ``dist/*.skill``.

The ``.skill`` artifact is a plain zip whose entries are rooted at the skill
directory, so it can be dropped into any client that imports skill packages
(and can be unzipped straight into a ``skills/`` folder).  Packaged members
are ``SKILL.md`` plus the ``assets/``, ``references/``, ``scripts/``,
``profiles/`` and ``contracts/`` subtrees (see ``INCLUDE`` below):
``evals/`` holds development prompts and never ships.

The gate ledger ``contracts/gates/package-manifest.json`` covers the REPOSITORY
package, including ``evals/evals.json``. Inside the archive the ledger is
rewritten to list only the members that actually ship, so a consumer that
verifies an unpacked ``.skill`` against its embedded manifest does not fail on
a file the ship policy deliberately excludes. The repo-side ledger is the one
CI rebuilds and is unchanged by this rewriting.

Usage (from the repository root):

    python tools/build_skill.py            # rewrite dist/*.skill
    python tools/build_skill.py --check    # exit 1 if dist is stale
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO / "empirical-research-pipeline"
SKILL_NAME = SKILL_DIR.name
DIST = REPO / "dist" / f"{SKILL_NAME}.skill"
INCLUDE = ("SKILL.md", "assets", "profiles", "references", "scripts", "contracts")
SKIP_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db"}
SKIP_SUFFIX = {".pyc", ".pyo"}
MANIFEST_MEMBER = "contracts/gates/package-manifest.json"


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


def archive_member(f: Path) -> str:
    return f"{SKILL_NAME}/{f.relative_to(SKILL_DIR).as_posix()}"


def member_bytes(f: Path, shipped: set[str]) -> bytes:
    """Bytes as they land in the archive. The gate manifest is rewritten to
    drop members the ship policy does not include, so the embedded ledger
    matches the archive it lives in."""
    rel = f.relative_to(SKILL_DIR).as_posix()
    if rel != MANIFEST_MEMBER:
        return f.read_bytes()
    shipped_rel = {p[len(SKILL_NAME) + 1:] for p in shipped}
    ledger = json.loads(f.read_text(encoding="utf-8"))
    kept = [entry for entry in ledger["members"] if entry["path"] in shipped_rel]
    dropped_paths = {entry["path"] for entry in ledger["members"]
                     if entry["path"] not in shipped_rel}
    if dropped_paths - {"evals/evals.json"}:
        # never silently rewrite for unexpected exclusions
        raise SystemExit(f"unexpected manifest rewrite, dropped: {sorted(dropped_paths)}")
    payload = dict(ledger)
    payload["members"] = kept
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def build(path: Path, files: list[Path]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    shipped = {archive_member(f) for f in files}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(files, key=lambda item: item.relative_to(SKILL_DIR).as_posix()):
            arc = archive_member(f)
            data = member_bytes(f, shipped)
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


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        shipped = {archive_member(f) for f in files}
        with zipfile.ZipFile(DIST) as zf:
            inside = {n for n in zf.namelist()}
        expected = shipped
        missing = expected - inside
        extra = inside - expected
        with zipfile.ZipFile(DIST) as zf:
            stale = [f for f in files
                     if archive_member(f) in inside
                     and zf.read(archive_member(f)) != member_bytes(f, shipped)]
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
        if sidecar.read_text(encoding="utf-8").split("  ")[0].strip() != file_digest(DIST):
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
        f"{file_digest(DIST)}  {DIST.name}\n", encoding="utf-8")
    print(f"wrote {DIST.name}.sha256")
    return 0


if __name__ == "__main__":
    sys.exit(main())
