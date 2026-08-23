from __future__ import annotations

import os
import time
from pathlib import Path

import crabwalk.build.cache as cache_module
from crabwalk.build.cache import (
    FileLock,
    cache_load_lease_active,
    prune_artifact_cache,
    retain_cache_load_lease,
    touch_cache_access,
    write_text,
)


def _entry(root: Path, character: str, size: int, age: float) -> Path:
    entry = root / "cache" / "artifacts" / (character * 64)
    entry.mkdir(parents=True)
    artifact = entry / "artifact.bin"
    artifact.write_bytes(b"x" * size)
    timestamp = time.time() - age
    os.utime(artifact, (timestamp, timestamp))
    return entry


def test_cache_pruning_is_bounded_scoped_and_supports_dry_run(tmp_path: Path) -> None:
    state = tmp_path / ".crabwalk"
    oldest = _entry(state, "a", 10, 300)
    middle = _entry(state, "b", 10, 200)
    newest = _entry(state, "c", 10, 100)
    unknown = state / "cache" / "artifacts" / "keep-me"
    unknown.mkdir()
    (unknown / "value").write_bytes(b"untouched")

    preview = prune_artifact_cache(
        state,
        max_bytes=15,
        max_age_seconds=None,
        dry_run=True,
    )
    assert preview.removed == (oldest, middle)
    assert preview.bytes_reclaimed == 20
    assert all(path.is_dir() for path in (oldest, middle, newest, unknown))

    removed = prune_artifact_cache(
        state,
        max_bytes=15,
        max_age_seconds=None,
    )
    assert removed.removed == (oldest, middle)
    assert not oldest.exists()
    assert not middle.exists()
    assert newest.is_dir()
    assert unknown.is_dir()


def test_pruning_skips_a_busy_fingerprint_and_uses_last_access(tmp_path: Path) -> None:
    state = tmp_path / ".crabwalk"
    busy = _entry(state, "d", 10, 500)
    recently_used = _entry(state, "e", 10, 400)
    touch_cache_access(recently_used)

    with FileLock(state / "locks" / f"{'d' * 64}.lock"):
        outcome = prune_artifact_cache(
            state,
            max_bytes=0,
            max_age_seconds=None,
        )

    assert outcome.removed == (recently_used,)
    assert busy.is_dir()
    assert not recently_used.exists()

    after_release = prune_artifact_cache(
        state,
        max_bytes=0,
        max_age_seconds=None,
    )
    assert after_release.removed == (busy,)


def test_pruning_does_not_inventory_a_busy_fingerprint(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    state = tmp_path / ".crabwalk"
    busy = _entry(state, "7", 10, 500)
    original = cache_module._entry_size_and_mtime

    def reject_busy_metadata_read(path: Path) -> tuple[int, float]:
        if path == busy:
            raise AssertionError("busy cache metadata was read without its lock")
        return original(path)

    monkeypatch.setattr(  # type: ignore[attr-defined]
        cache_module,
        "_entry_size_and_mtime",
        reject_busy_metadata_read,
    )

    with FileLock(state / "locks" / f"{'7' * 64}.lock"):
        outcome = prune_artifact_cache(
            state,
            max_bytes=0,
            max_age_seconds=None,
        )

    assert outcome.removed == ()
    assert outcome.entries_remaining == 1
    assert outcome.bytes_remaining is None
    assert outcome.bytes_remaining_known == 0
    assert outcome.busy_entries == 1
    assert outcome.limit_satisfied is None
    assert busy.is_dir()


def test_pruning_revalidates_selection_after_taking_entry_lock(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    state = tmp_path / ".crabwalk"
    candidate = _entry(state, "f", 10, 500)
    original = cache_module._entry_size_and_mtime
    calls = 0

    def changed_after_selection(path: Path) -> tuple[int, float]:
        nonlocal calls
        calls += 1
        size, last_used = original(path)
        if path == candidate and calls > 1:
            return size, last_used + 1.0
        return size, last_used

    monkeypatch.setattr(  # type: ignore[attr-defined]
        cache_module,
        "_entry_size_and_mtime",
        changed_after_selection,
    )

    outcome = prune_artifact_cache(
        state,
        max_bytes=0,
        max_age_seconds=None,
    )

    assert outcome.removed == ()
    assert candidate.is_dir()


def test_pruning_skips_an_entry_when_the_os_denies_deletion(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    state = tmp_path / ".crabwalk"
    candidate = _entry(state, "8", 10, 500)

    def deny_mapped_artifact_deletion(path: Path) -> None:
        assert path == candidate
        raise PermissionError("native artifact is still mapped")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        cache_module.shutil,
        "rmtree",
        deny_mapped_artifact_deletion,
    )

    outcome = prune_artifact_cache(
        state,
        max_bytes=0,
        max_age_seconds=None,
    )

    assert outcome.removed == ()
    assert outcome.bytes_reclaimed == 0
    assert outcome.bytes_remaining == 10
    assert outcome.bytes_remaining_known == 10
    assert outcome.busy_entries == 0
    assert outcome.limit_satisfied is False
    assert outcome.entries_remaining == 1
    assert candidate.is_dir()


def test_pruning_skips_a_process_load_lease(tmp_path: Path) -> None:
    state = tmp_path / ".crabwalk"
    fingerprint = "1" * 64
    candidate = _entry(state, "1", 10, 500)
    retain_cache_load_lease(state, fingerprint)
    try:
        leased = prune_artifact_cache(
            state,
            max_bytes=0,
            max_age_seconds=None,
        )
        assert leased.removed == ()
        assert candidate.is_dir()
    finally:
        cache_module._release_cache_load_lease(state, fingerprint)

    released = prune_artifact_cache(
        state,
        max_bytes=0,
        max_age_seconds=None,
    )
    assert released.removed == (candidate,)


def test_unlocked_lease_with_a_live_reused_pid_is_stale(tmp_path: Path) -> None:
    state = tmp_path / ".crabwalk"
    fingerprint = "2" * 64
    lease = state / "locks" / "load-leases" / fingerprint / f"{os.getpid()}-stale.lock"
    lease.parent.mkdir(parents=True)
    lease.write_bytes(b"\0")

    assert cache_load_lease_active(state, fingerprint) is False
    assert not lease.exists()


def test_atomic_text_write_preserves_unchanged_input_mtime(tmp_path: Path) -> None:
    path = tmp_path / "generated.rs"
    write_text(path, "fn main() {}\n")
    old = time.time() - 100
    os.utime(path, (old, old))
    before = path.stat().st_mtime_ns

    write_text(path, "fn main() {}\n")

    assert path.stat().st_mtime_ns == before


def test_cache_age_uses_newest_content_or_access_timestamp(tmp_path: Path) -> None:
    entry = _entry(tmp_path / ".crabwalk", "9", 10, 500)
    touch_cache_access(entry)
    access = entry / ".last-access"
    old = time.time() - 400
    access.write_text(f"{int(old * 1_000_000_000)}\n", encoding="utf-8")
    os.utime(access, (old, old))

    artifact = entry / "artifact.bin"
    artifact.write_bytes(b"repaired")
    _, last_used = cache_module._entry_size_and_mtime(entry)

    assert last_used >= artifact.stat().st_mtime
