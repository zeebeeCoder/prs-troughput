"""Tool-owned clone cache for hybrid local-git ledger extraction."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class CachedClone:
    """Metadata for one cached clone."""

    org: str
    repo: str
    path: Path
    bytes_used: int
    last_accessed: datetime | None


class CloneLockError(RuntimeError):
    """Raised when a clone lock cannot be acquired."""


class _CloneLock:
    """Small cross-process lock using O_EXCL lock-file creation."""

    def __init__(self, lock_path: Path, timeout: float = 30.0, poll_interval: float = 0.1):
        self.lock_path = lock_path
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._fd: int | None = None

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, f"pid={os.getpid()}\n".encode())
                return self
            except FileExistsError as exc:
                if time.monotonic() >= deadline:
                    raise CloneLockError(f"Timed out waiting for clone lock {self.lock_path}") from exc
                time.sleep(self.poll_interval)

    def __exit__(self, exc_type, exc, tb):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass


class CloneCache:
    """Owns clone/fetch/prune lifecycle under a cache root."""

    def __init__(self, cache_root: str | os.PathLike[str], *, lock_timeout: float = 30.0):
        self.cache_root = Path(cache_root).expanduser()
        self.lock_timeout = lock_timeout
        self.cloned_count = 0
        self.fetched_count = 0
        self._fetched_this_run: set[Path] = set()

    def clone_path(self, org: str, repo: str) -> Path:
        """Return the cache path for org/repo."""
        return self.cache_root / org / repo

    def ensure_clone(self, org: str, repo: str, *, remote_url: str | None = None) -> Path:
        """Clone a missing repo or fetch an existing cache-owned clone."""
        with self.locked_clone(org, repo, remote_url=remote_url) as path:
            return path

    @contextmanager
    def locked_clone(self, org: str, repo: str, *, remote_url: str | None = None) -> Iterator[Path]:
        """Yield an ensured clone while holding its cache lock.

        Keeping the lock through extraction prevents another process/thread from
        mutating the same clone while read-only git commands are walking refs and
        history.
        """
        path = self.clone_path(org, repo)
        remote_url = remote_url or f"https://github.com/{org}/{repo}.git"
        lock_path = path / ".pr-metrics.lock" if path.exists() else path.parent / f".{repo}.pr-metrics.lock"
        with _CloneLock(lock_path, timeout=self.lock_timeout):
            self._ensure_clone_locked(path, remote_url)
            self._touch_access(path)
            yield path

    def _ensure_clone_locked(self, path: Path, remote_url: str) -> None:
        """Clone/fetch path; caller must hold the clone lock."""
        if (path / ".git").exists():
            if path not in self._fetched_this_run:
                self._run(["git", "-C", str(path), "fetch", "--prune", "origin"])
                self.fetched_count += 1
                self._fetched_this_run.add(path)
            return

        if path.exists() and any(child.name != ".pr-metrics.lock" for child in path.iterdir()):
            raise RuntimeError(f"Cache path exists but is not a git clone: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._run(["git", "clone", "--no-checkout", remote_url, str(path)])
        self.cloned_count += 1
        self._fetched_this_run.add(path)

    def iter_cached_clones(self) -> list[CachedClone]:
        """Return cached clone metadata."""
        clones: list[CachedClone] = []
        if not self.cache_root.exists():
            return clones
        for org_dir in sorted(p for p in self.cache_root.iterdir() if p.is_dir()):
            for repo_dir in sorted(p for p in org_dir.iterdir() if p.is_dir()):
                if not (repo_dir / ".git").exists():
                    continue
                clones.append(CachedClone(
                    org=org_dir.name,
                    repo=repo_dir.name,
                    path=repo_dir,
                    bytes_used=self._du_bytes(repo_dir),
                    last_accessed=self._access_time(repo_dir),
                ))
        return clones

    def du(self) -> int:
        """Return total cache disk usage in bytes."""
        return sum(clone.bytes_used for clone in self.iter_cached_clones())

    def prune(self, older_than: timedelta, *, dry_run: bool = False) -> list[Path]:
        """Remove clones whose access marker is older than the cutoff.

        When dry_run is true, return matching clones without deleting them.
        """
        cutoff = datetime.now(timezone.utc) - older_than
        removed: list[Path] = []
        for clone in self.iter_cached_clones():
            accessed = clone.last_accessed or datetime.fromtimestamp(clone.path.stat().st_mtime, tz=timezone.utc)
            if accessed < cutoff:
                if not dry_run:
                    shutil.rmtree(clone.path)
                removed.append(clone.path)
        return removed

    def clear(self, org: str | None = None, repo: str | None = None) -> list[Path]:
        """Remove all cache entries, or those matching org/repo."""
        removed: list[Path] = []
        for clone in self.iter_cached_clones():
            if org and clone.org != org:
                continue
            if repo and clone.repo != repo:
                continue
            shutil.rmtree(clone.path)
            removed.append(clone.path)
        return removed

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)

    def _touch_access(self, path: Path) -> None:
        marker = path / ".pr-metrics.access"
        marker.write_text(datetime.now(timezone.utc).isoformat())

    def _access_time(self, path: Path) -> datetime | None:
        marker = path / ".pr-metrics.access"
        if not marker.exists():
            return None
        try:
            return datetime.fromisoformat(marker.read_text().strip())
        except ValueError:
            return datetime.fromtimestamp(marker.stat().st_mtime, tz=timezone.utc)

    def _du_bytes(self, path: Path) -> int:
        total = 0
        for root, _dirs, files in os.walk(path):
            for filename in files:
                file_path = Path(root) / filename
                try:
                    total += file_path.stat().st_size
                except OSError:
                    pass
        return total
