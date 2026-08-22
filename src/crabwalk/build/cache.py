"""Filesystem cache primitives with scoped interprocess locking."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO


@dataclass(frozen=True, slots=True)
class ArtifactCacheInfo:
    status: str
    artifact: Path
    manifest: Path
    size: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class CachePruneResult:
    removed: tuple[Path, ...]
    bytes_reclaimed: int
    bytes_remaining: int
    entries_remaining: int
    dry_run: bool


class FileLock:
    def __init__(self, path: Path, timeout: float = 600.0):
        self.path = path
        self.timeout = timeout
        self._handle: BinaryIO | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + self.timeout
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in {13, 36}:
                        handle.close()
                        raise
                    if time.monotonic() >= deadline:
                        handle.close()
                        raise TimeoutError(
                            f"timed out waiting for Crabwalk lock {self.path}"
                        ) from error
                    time.sleep(0.05)
        else:
            fcntl: Any = __import__("fcntl")

            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN}:
                        handle.close()
                        raise
                    if time.monotonic() >= deadline:
                        handle.close()
                        raise TimeoutError(
                            f"timed out waiting for Crabwalk lock {self.path}"
                        ) from error
                    time.sleep(0.05)
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()

    def release(self) -> None:
        """Release an acquired lock; repeated calls are harmless."""

        handle = self._handle
        if handle is None:
            return
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl: Any = __import__("fcntl")

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
        self._handle = None


_PROCESS_LEASE_ID = f"{os.getpid()}-{time.time_ns()}"
_load_lease_guard = threading.Lock()
_load_leases: dict[tuple[str, str], tuple[Path, FileLock]] = {}


def retain_cache_load_lease(state_root: Path, fingerprint: str) -> None:
    """Keep one process-scoped reader lease for a mapped native artifact."""

    resolved_state = state_root.resolve()
    key = (str(resolved_state), fingerprint)
    with _load_lease_guard:
        if key in _load_leases:
            return
        lease_path = (
            resolved_state
            / "locks"
            / "load-leases"
            / fingerprint
            / f"{_PROCESS_LEASE_ID}.lock"
        )
        lease = FileLock(lease_path, timeout=0.0)
        lease.__enter__()
        _load_leases[key] = (lease_path, lease)


def _release_cache_load_lease(state_root: Path, fingerprint: str) -> None:
    key = (str(state_root.resolve()), fingerprint)
    with _load_lease_guard:
        retained = _load_leases.pop(key, None)
    if retained is None:
        return
    path, lease = retained
    lease.__exit__(None, None, None)
    path.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = value.encode("utf-8")
    try:
        if path.read_bytes() == encoded:
            return
    except OSError:
        pass
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def artifact_cache_info(
    state_root: Path,
    fingerprint: str,
    extension_name: str,
    extension_suffix: str,
) -> ArtifactCacheInfo:
    """Inspect one content-addressed entry without mutating it."""

    cache_dir = state_root / "cache" / "artifacts" / fingerprint
    artifact = cache_dir / f"{extension_name}{extension_suffix}"
    manifest_path = cache_dir / "artifact-manifest.json"
    manifest = read_json(manifest_path)
    artifact_exists = artifact.is_file()
    manifest_exists = manifest_path.is_file()
    size = artifact.stat().st_size if artifact_exists else 0
    if not artifact_exists and not manifest_exists:
        return ArtifactCacheInfo("miss", artifact, manifest_path, 0)
    if manifest is None:
        return ArtifactCacheInfo(
            "corrupt", artifact, manifest_path, size, "manifest is missing or invalid"
        )
    if not artifact_exists:
        return ArtifactCacheInfo(
            "corrupt", artifact, manifest_path, 0, "artifact is missing"
        )
    if (
        manifest.get("schema_version") != 1
        or manifest.get("fingerprint") != fingerprint
        or manifest.get("extension_name") != extension_name
        or manifest.get("artifact") != artifact.name
    ):
        return ArtifactCacheInfo(
            "corrupt", artifact, manifest_path, size, "manifest identity mismatch"
        )
    expected = manifest.get("artifact_sha256")
    if not isinstance(expected, str) or expected != sha256_file(artifact):
        return ArtifactCacheInfo(
            "corrupt", artifact, manifest_path, size, "artifact hash mismatch"
        )
    return ArtifactCacheInfo("hit", artifact, manifest_path, size)


def touch_cache_access(entry: Path) -> None:
    """Atomically record a verified cache use independently of artifact age."""

    write_text(entry / ".last-access", f"{time.time_ns()}\n")


def prune_artifact_cache(
    state_root: Path,
    *,
    max_bytes: int | None = 2 * 1024 * 1024 * 1024,
    max_age_seconds: float | None = 30 * 24 * 60 * 60,
    dry_run: bool = False,
) -> CachePruneResult:
    """Remove only validated, content-addressed artifact-entry directories."""

    state_root = state_root.resolve()
    with FileLock(state_root / "locks" / "cache-prune.lock"):
        return _prune_artifact_cache_locked(
            state_root,
            max_bytes=max_bytes,
            max_age_seconds=max_age_seconds,
            dry_run=dry_run,
        )


def _prune_artifact_cache_locked(
    state_root: Path,
    *,
    max_bytes: int | None,
    max_age_seconds: float | None,
    dry_run: bool,
) -> CachePruneResult:

    if max_bytes is not None and max_bytes < 0:
        raise ValueError("max_bytes must be non-negative or None")
    if max_age_seconds is not None and max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative or None")
    root = (state_root / "cache" / "artifacts").resolve()
    if not root.is_dir():
        return CachePruneResult((), 0, 0, 0, dry_run)

    entries: list[tuple[Path, int, float]] = []
    for candidate in root.iterdir():
        if not re.fullmatch(r"[0-9a-f]{64}", candidate.name):
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.parent != root or not resolved.is_dir():
            continue
        size, last_used = _entry_size_and_mtime(resolved)
        entries.append((resolved, size, last_used))

    now = time.time()
    selected: set[Path] = set()
    if max_age_seconds is not None:
        selected.update(
            path for path, _, used in entries if now - used > max_age_seconds
        )
    remaining_bytes = sum(size for path, size, _ in entries if path not in selected)
    if max_bytes is not None and remaining_bytes > max_bytes:
        for path, size, _ in sorted(entries, key=lambda value: value[2]):
            if path in selected:
                continue
            selected.add(path)
            remaining_bytes -= size
            if remaining_bytes <= max_bytes:
                break

    ordered = tuple(
        path
        for path, _, _ in sorted(entries, key=lambda value: value[2])
        if path in selected
    )
    selected_snapshots = {
        path: (size, last_used) for path, size, last_used in entries if path in selected
    }
    removed = ordered
    removed_sizes = {path: selected_snapshots[path][0] for path in removed}
    if not dry_run:
        actual: list[Path] = []
        removed_sizes = {}
        for path in ordered:
            try:
                with FileLock(
                    state_root / "locks" / f"{path.name}.lock",
                    timeout=0.0,
                ):
                    if cache_load_lease_active(state_root, path.name):
                        continue
                    current = _entry_size_and_mtime(path)
                    if current != selected_snapshots[path]:
                        # A verified hit or publication changed the entry after
                        # selection. Leave it for a future prune pass that can
                        # assess the new access time and size consistently.
                        continue
                    _remove_scoped_entry(root, path)
            except (FileNotFoundError, TimeoutError):
                continue
            actual.append(path)
            removed_sizes[path] = current[0]
        removed = tuple(actual)
    reclaimed = sum(removed_sizes[path] for path in removed)
    remaining_entries = len(entries) - len(removed)
    remaining_size = sum(size for _, size, _ in entries) - reclaimed
    return CachePruneResult(
        removed=removed,
        bytes_reclaimed=reclaimed,
        bytes_remaining=remaining_size,
        entries_remaining=remaining_entries,
        dry_run=dry_run,
    )


def _entry_size_and_mtime(path: Path) -> tuple[int, float]:
    size = 0
    content_mtime = 0.0
    for candidate in path.rglob("*"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        stat = candidate.stat()
        size += stat.st_size
        if candidate.name != ".last-access":
            content_mtime = max(content_mtime, stat.st_mtime)
    last_used = content_mtime
    access = path / ".last-access"
    if access.is_file():
        access_time = access.stat().st_mtime
        try:
            recorded_ns = int(access.read_text(encoding="utf-8").strip())
        except (OSError, UnicodeError, ValueError):
            pass
        else:
            access_time = max(access_time, recorded_ns / 1_000_000_000)
        last_used = max(last_used, access_time)
    elif last_used == 0.0:
        last_used = path.stat().st_mtime
    return size, last_used


def cache_load_lease_active(state_root: Path, fingerprint: str) -> bool:
    """Return whether another live process retains this mapped artifact."""

    lease_root = state_root / "locks" / "load-leases" / fingerprint
    if not lease_root.is_dir():
        return False
    stale: list[Path] = []
    for path in lease_root.glob("*.lock"):
        owner = _lease_owner_pid(path)
        if owner is not None and _process_is_alive(owner):
            return True
        try:
            with FileLock(path, timeout=0.0):
                pass
        except TimeoutError:
            return True
        stale.append(path)
    for path in stale:
        path.unlink(missing_ok=True)
    try:
        lease_root.rmdir()
    except OSError:
        pass
    return False


def _lease_owner_pid(path: Path) -> int | None:
    try:
        return int(path.stem.split("-", 1)[0])
    except ValueError:
        return None


def _process_is_alive(process_id: int) -> bool:
    if process_id == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            process_id,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove_scoped_entry(root: Path, path: Path) -> None:
    resolved = path.resolve(strict=True)
    if resolved.parent != root or not re.fullmatch(r"[0-9a-f]{64}", resolved.name):
        raise ValueError(f"refusing to remove unscoped cache path {path}")
    shutil.rmtree(resolved)
