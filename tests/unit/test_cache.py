from __future__ import annotations

import os
import time
from pathlib import Path

from crabwalk.build.cache import prune_artifact_cache


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
