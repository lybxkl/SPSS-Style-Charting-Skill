"""Protect frozen source files during trusted analysis runs.

This is an accidental-write guard, not a sandbox for hostile programs. Originals
are made read-only where supported, all files (including exclusions) are bound,
and changed/deleted originals are restored from content-addressed local copies.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat

from verify_dataset import sha256


class SourceGuard:
    def __init__(self, source_root, project_root):
        self.root = Path(source_root).resolve()
        self.cache = (Path(project_root).resolve() / ".research-source-backups").resolve()
        if self.cache.is_relative_to(self.root) or self.root.is_relative_to(self.cache):
            raise ValueError("source_root and local source-backup cache must be separate")
        self.records = []
        self.identities = set()

    def forbidden(self, path):
        full = Path(path).resolve()
        if full.is_relative_to(self.root) or full.is_relative_to(self.cache):
            return True
        if full.is_file():
            st = full.stat()
            return (st.st_dev, st.st_ino) in self.identities
        return False

    def freeze(self):
        if not self.root.is_dir():
            raise ValueError("frozen source_root is not a directory")
        self.cache.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            full = path.resolve()
            if not full.is_relative_to(self.root):
                raise ValueError(f"source link escapes frozen root: {path}")
            st = full.stat()
            checksum = sha256(full)
            backup = self.cache / checksum
            if not backup.exists() or sha256(backup) != checksum:
                if backup.exists():
                    backup.chmod(stat.S_IWRITE | stat.S_IREAD)
                shutil.copyfile(full, backup)
            self.records.append({"path": str(full), "sha256": checksum, "bytes": st.st_size,
                                 "mode": st.st_mode, "atime_ns": st.st_atime_ns,
                                 "mtime_ns": st.st_mtime_ns, "backup": str(backup)})
            self.identities.add((st.st_dev, st.st_ino))
            full.chmod(st.st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))

    def finish(self):
        result = {"restored": [], "added": [], "errors": []}
        expected = {r["path"] for r in self.records}
        for item in self.records:
            path = Path(item["path"])
            try:
                changed = not path.is_file() or sha256(path) != item["sha256"]
                if changed:
                    if path.exists():
                        path.chmod(stat.S_IWRITE | stat.S_IREAD)
                    # Sources are trusted files; never follow a replacement link
                    # when putting back the exact bytes that were frozen.
                    if path.is_symlink():
                        path.unlink()
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(item["backup"], path)
                    os.utime(path, ns=(item["atime_ns"], item["mtime_ns"]))
                    result["restored"].append(str(path))
                path.chmod(item["mode"])
            except Exception as exc:
                result["errors"].append(f"{path}: {exc}; recovery copy: {item['backup']}")
        try:
            actual = {str(p.resolve()) for p in self.root.rglob("*") if p.is_file()}
            result["added"] = sorted(actual - expected)
        except OSError as exc:
            result["errors"].append(str(exc))
        return result
