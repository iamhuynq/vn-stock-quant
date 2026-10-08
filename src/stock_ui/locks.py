"""The pipeline lock shared with scripts/daily.sh: a directory created atomically with mkdir.

Same rules as daily.sh: the lock holds `pid`; it is stale when that process is dead or the lock is
older than 3 hours. The UI runner also writes `owner` so the UI can say who holds it.
"""

import os
import secrets
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

PIPELINE_LOCK = ".daily.lock"
STALE_SECONDS = 3 * 3600
CREATING_SECONDS = 10       # a lock without a pid file this young is still being created


@dataclass(frozen=True)
class LockInfo:
    pid: int | None
    owner: str          # "ui:<run_id>" for UI tasks, else "daily.sh"
    age_seconds: float
    alive: bool

    @property
    def stale(self) -> bool:
        if self.pid is None and self.age_seconds < CREATING_SECONDS:
            return False
        return not self.alive or self.age_seconds >= STALE_SECONDS


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:                                   # reap it if it is our own exited child (else it stays a zombie)
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_path(data_dir: Path) -> Path:
    return data_dir / PIPELINE_LOCK


def lock_info(data_dir: Path, now: float | None = None) -> LockInfo | None:
    path = lock_path(data_dir)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    pid = _read_int(path / "pid")
    owner = _read_text(path / "owner") or "daily.sh"
    return LockInfo(pid, owner, (now or time.time()) - mtime, pid_alive(pid))


def acquire(data_dir: Path, owner: str) -> bool:
    """Take the lock for this process; take over a stale one. False if a live run holds it."""
    path = lock_path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError:
        info = lock_info(data_dir)
        if info is not None and not info.stale:
            return False
        graveyard = path.with_name(f"{path.name}.stale-{secrets.token_hex(4)}")
        try:
            path.rename(graveyard)            # atomic move; a microsecond race remains, as in daily.sh
        except FileNotFoundError:
            pass
        shutil.rmtree(graveyard, ignore_errors=True)
        try:
            path.mkdir()
        except FileExistsError:
            return False                      # another process took it first
    (path / "pid").write_text(str(os.getpid()))
    (path / "owner").write_text(owner)
    return True


def release(data_dir: Path) -> None:
    path = lock_path(data_dir)
    if _read_int(path / "pid") == os.getpid():
        shutil.rmtree(path, ignore_errors=True)


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except FileNotFoundError:
        return None
