"""Filesystem cache primitives with scoped interprocess locking."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any


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
        self._handle: object | None = None

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
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        handle = self._handle
        if handle is None:
            return
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
        self._handle = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def prune_artifact_cache(
    state_root: Path,
    *,
    max_bytes: int | None = 2 * 1024 * 1024 * 1024,
    max_age_seconds: float | None = 30 * 24 * 60 * 60,
    dry_run: bool = False,
) -> CachePruneResult:
    """Remove only validated, content-addressed artifact-entry directories."""

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
    reclaimed = sum(size for path, size, _ in entries if path in selected)
    if not dry_run:
        for path in ordered:
            _remove_scoped_entry(root, path)
    return CachePruneResult(
        removed=ordered,
        bytes_reclaimed=reclaimed,
        bytes_remaining=sum(size for path, size, _ in entries if path not in selected),
        entries_remaining=sum(path not in selected for path, _, _ in entries),
        dry_run=dry_run,
    )


def _entry_size_and_mtime(path: Path) -> tuple[int, float]:
    size = 0
    last_used = 0.0
    for candidate in path.rglob("*"):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        stat = candidate.stat()
        size += stat.st_size
        last_used = max(last_used, stat.st_mtime)
    if last_used == 0.0:
        last_used = path.stat().st_mtime
    return size, last_used


def _remove_scoped_entry(root: Path, path: Path) -> None:
    resolved = path.resolve(strict=True)
    if resolved.parent != root or not re.fullmatch(r"[0-9a-f]{64}", resolved.name):
        raise ValueError(f"refusing to remove unscoped cache path {path}")
    shutil.rmtree(resolved)
