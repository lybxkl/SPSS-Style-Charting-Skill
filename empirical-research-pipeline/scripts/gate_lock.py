"""Project mutation lease shared by Python inspection and the desktop runner.

Elapsed time never proves that an owner is dead. Recovery is allowed only for
this host, after both the owner and all registered foreground children exit.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import socket

from gate_contract import atomic_json, now, read_json,resolve


class LeaseConflict(FileExistsError):
    pass


def alive(pid):
    from txn import _pid_alive

    return _pid_alive(int(pid))


class ProjectLease:
    def __init__(self, root, inherited_token=None):
        self.root = Path(root).resolve()
        self.path = resolve(self.root,'output/gates/publication.lock')
        self.token = inherited_token or secrets.token_hex(24)
        self.borrowed = bool(inherited_token)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.borrowed:
            owner = read_json(self.path)
            if owner.get('token') != self.token or owner.get('hostname') != socket.gethostname():
                raise LeaseConflict('invalid inherited project lease')
            if not alive(owner.get('pid', 0)):
                raise LeaseConflict('inherited owner is no longer running')
            return self
        value = {
            'schema': 'dsa.gate-lease/1', 'token': self.token,
            'pid': os.getpid(), 'hostname': socket.gethostname(),
            'children': [], 'kind': 'inspection', 'createdAt': now(),
        }
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise LeaseConflict('project is already being written or inspected') from exc
        try:
            import json
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            # A failed creation belongs to us; an unrelated existing lock never does.
            self.path.unlink(missing_ok=True)
            raise
        return self

    def __exit__(self, *_):
        if not self.borrowed and self.path.exists():
            if read_json(self.path).get('token') == self.token:
                self.path.unlink()


def recover(root):
    root = Path(root).resolve()
    path = resolve(root,'output/gates/publication.lock')
    if path.exists():
        record = read_json(path)
        if record.get('hostname') != socket.gethostname():
            raise LeaseConflict('cannot establish liveness of a different host')
        if alive(record.get('pid', 0)) or any(alive(pid) for pid in record.get('children', [])):
            raise LeaseConflict('project owner or foreground child is still alive')
        # Claim recovery by an exclusive second guard; re-read the exact bytes
        # before unlinking so two recovering processes cannot remove a new lease.
        guard = path.with_suffix('.recovery')
        fd = os.open(guard, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        try:
            if read_json(path) != record:
                raise LeaseConflict('lease changed during recovery')
            path.unlink()
        finally:
            guard.unlink(missing_ok=True)
    recovered = []
    with ProjectLease(root):
        directory = resolve(root,'output/gates/state')
        for file in sorted(directory.glob('*.json')) if directory.exists() else []:
            file=resolve(root,file.relative_to(root).as_posix())
            state = read_json(file)
            if state.get('phase') in ('requested', 'running', 'production-running'):
                state.update(phase='interrupted', updatedAt=now())
                atomic_json(file, state)
                recovered.append(state.get('stage', file.stem))
    return {'schema': 'dsa.gate-recovery/1', 'recovered': recovered}
