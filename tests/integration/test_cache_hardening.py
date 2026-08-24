from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from crabwalk.build.cache import prune_artifact_cache
from crabwalk.compiler.capabilities import capability_contract


SOURCE = """\
from crabwalk import rust

@rust.fn
def square(value: rust.u64) -> rust.u64:
    return value * value

print(square(12))
print(square.__crabwalk__["cache_hit"])
print(square.__crabwalk__["artifact"])
"""


def _environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    return environment


def _run(
    source: Path, root: Path, timeout: int = 600
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=root,
        env=_environment(root),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@capability_contract("cache.corruption-repair")
def test_corrupt_artifact_is_rebuilt_before_loading(tmp_path: Path) -> None:
    source = tmp_path / "corruption_app.py"
    source.write_text(SOURCE, encoding="utf-8")
    root = Path(__file__).resolve().parents[2]

    first = _run(source, root)
    assert first.returncode == 0, first.stderr
    first_lines = first.stdout.splitlines()
    assert first_lines[:2] == ["144", "False"]
    artifact = Path(first_lines[2])
    original_size = artifact.stat().st_size

    artifact.write_bytes(b"deliberately corrupt")

    recovered = _run(source, root)
    assert recovered.returncode == 0, recovered.stderr
    assert recovered.stdout.splitlines()[:2] == ["144", "False"]
    assert artifact.stat().st_size == original_size

    cached = _run(source, root, timeout=180)
    assert cached.returncode == 0, cached.stderr
    assert cached.stdout.splitlines()[:2] == ["144", "True"]


@capability_contract("cache.concurrent-publication")
def test_simultaneous_processes_publish_one_valid_artifact(tmp_path: Path) -> None:
    source = tmp_path / "race_app.py"
    source.write_text(SOURCE, encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, "-u", str(source)]
    environment = _environment(root)

    processes = [
        subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    results = [process.communicate(timeout=600) for process in processes]

    for process, (stdout, stderr) in zip(processes, results):
        assert process.returncode == 0, stderr
        assert stdout.splitlines()[0] == "144"
    cache_states = sorted(stdout.splitlines()[1] for stdout, _ in results)
    assert cache_states == ["False", "True"]
    artifacts = {stdout.splitlines()[2] for stdout, _ in results}
    assert len(artifacts) == 1
    assert Path(next(iter(artifacts))).is_file()


def test_interrupted_manifest_publication_cannot_create_a_false_hit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "interrupted_app.py"
    source.write_text(SOURCE, encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    first = _run(source, root)
    assert first.returncode == 0, first.stderr
    artifact = Path(first.stdout.splitlines()[2])
    manifest = artifact.parent / "artifact-manifest.json"
    assert manifest.is_file()

    manifest.unlink()
    orphan = artifact.parent / f".{artifact.name}.interrupted.tmp"
    orphan.write_bytes(b"incomplete staged artifact")

    rebuilt = _run(source, root)
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert rebuilt.stdout.splitlines()[:2] == ["144", "False"]
    assert manifest.is_file()

    cached = _run(source, root, timeout=180)
    assert cached.returncode == 0, cached.stderr
    assert cached.stdout.splitlines()[:2] == ["144", "True"]


def test_same_process_reload_rebuilds_when_a_path_dependency_asset_changes(
    tmp_path: Path,
) -> None:
    dependency = tmp_path / "native_value"
    (dependency / "src").mkdir(parents=True)
    (dependency / "Cargo.toml").write_text(
        """\
[package]
name = "native-value"
version = "0.1.0"
edition = "2024"

[lib]
path = "src/lib.rs"
""",
        encoding="utf-8",
    )
    (dependency / "src" / "lib.rs").write_text(
        """\
const VALUE: &str = include_str!("../value.txt");

pub fn value() -> u64 {
    VALUE.trim().parse().unwrap()
}
""",
        encoding="utf-8",
    )
    asset = dependency / "value.txt"
    asset.write_text("1\n", encoding="utf-8")
    module = tmp_path / "dependency_app.py"
    module.write_text(
        """\
from crabwalk import rust

native_value = rust.crate("native-value", path="./native_value")

@rust.fn
def current() -> rust.u64:
    return native_value.value()
""",
        encoding="utf-8",
    )
    driver = tmp_path / "dependency_driver.py"
    driver.write_text(
        """\
import importlib
from pathlib import Path

import dependency_app

print(dependency_app.current())
first = dependency_app.current.__crabwalk__["fingerprint"]
Path(__file__).with_name("native_value").joinpath("value.txt").write_text(
    "2\\n", encoding="utf-8"
)
importlib.invalidate_caches()
dependency_app = importlib.reload(dependency_app)
print(dependency_app.current())
print(first != dependency_app.current.__crabwalk__["fingerprint"])
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = _environment(root)
    environment["PYTHONPATH"] = os.pathsep.join(
        (environment["PYTHONPATH"], str(tmp_path))
    )
    environment["CRABWALK_PROGRESS"] = "never"

    result = subprocess.run(
        [sys.executable, "-u", str(driver)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["1", "2", "True"]


@capability_contract("cache.prune-load-lease")
def test_pruning_cannot_remove_an_artifact_during_build_or_mapped_lifetime(
    tmp_path: Path,
) -> None:
    source = tmp_path / "leased_app.py"
    ready = tmp_path / "leased_app.ready"
    source.write_text(
        """\
from pathlib import Path
import time

from crabwalk import rust

@rust.fn
def square(value: rust.u64) -> rust.u64:
    return value * value

Path(__file__).with_suffix(".ready").write_text(
    square.__crabwalk__["artifact"], encoding="utf-8"
)
time.sleep(0.5)
print(square(12))
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = _environment(root)
    environment["CRABWALK_PROGRESS"] = "never"
    process = subprocess.Popen(
        [sys.executable, "-u", str(source)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    state = tmp_path / ".crabwalk"
    deadline = time.monotonic() + 600
    while not ready.is_file() and process.poll() is None:
        prune_artifact_cache(state, max_bytes=0, max_age_seconds=None)
        if time.monotonic() >= deadline:
            process.kill()
            raise TimeoutError("native build did not publish its load-ready marker")
        time.sleep(0.02)

    if not ready.is_file():
        stdout, stderr = process.communicate(timeout=30)
        raise AssertionError(stderr or stdout or "native loader exited before ready")

    artifact = Path(ready.read_text(encoding="utf-8"))
    for _ in range(20):
        outcome = prune_artifact_cache(
            state,
            max_bytes=0,
            max_age_seconds=None,
        )
        assert outcome.removed == ()
        assert artifact.is_file()

    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 0, stderr
    assert stdout.splitlines() == ["144"]

    released = prune_artifact_cache(
        state,
        max_bytes=0,
        max_age_seconds=None,
    )
    assert released.removed == (artifact.parent,)


def test_crate_cache_validation_does_not_replace_a_mapped_identical_binary(
    tmp_path: Path,
) -> None:
    dependency = tmp_path / "native_value"
    (dependency / "src").mkdir(parents=True)
    (dependency / "Cargo.toml").write_text(
        """\
[package]
name = "native-value"
version = "0.1.0"
edition = "2024"

[lib]
path = "src/lib.rs"
""",
        encoding="utf-8",
    )
    (dependency / "src" / "lib.rs").write_text(
        "pub fn value() -> u64 { 7 }\n",
        encoding="utf-8",
    )
    module = tmp_path / "mapped_dependency.py"
    module.write_text(
        """\
from crabwalk import rust

native_value = rust.crate("native-value", path="./native_value")

@rust.fn
def current() -> rust.u64:
    return native_value.value()
""",
        encoding="utf-8",
    )
    first_driver = tmp_path / "first_driver.py"
    first_driver.write_text(
        """\
from pathlib import Path
import time

import mapped_dependency

Path(__file__).with_suffix(".ready").write_text("ready", encoding="utf-8")
release = Path(__file__).with_suffix(".release")
deadline = time.monotonic() + 600
while not release.is_file():
    if time.monotonic() >= deadline:
        raise TimeoutError("mapped dependency release signal was not written")
    time.sleep(0.02)
print(mapped_dependency.current())
""",
        encoding="utf-8",
    )
    second_driver = tmp_path / "second_driver.py"
    second_driver.write_text(
        "import mapped_dependency\nprint(mapped_dependency.current())\n",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = _environment(root)
    environment["PYTHONPATH"] = os.pathsep.join(
        (environment["PYTHONPATH"], str(tmp_path))
    )
    environment["CRABWALK_PROGRESS"] = "never"
    first = subprocess.Popen(
        [sys.executable, "-u", str(first_driver)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    ready = first_driver.with_suffix(".ready")
    deadline = time.monotonic() + 600
    while not ready.is_file() and first.poll() is None:
        if time.monotonic() >= deadline:
            first.kill()
            raise TimeoutError("first crate-backed loader did not become ready")
        time.sleep(0.02)

    if not ready.is_file():
        stdout, stderr = first.communicate(timeout=30)
        raise AssertionError(stderr or stdout or "first crate-backed loader failed")

    second = subprocess.run(
        [sys.executable, "-u", str(second_driver)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    first_driver.with_suffix(".release").write_text("release", encoding="utf-8")
    first_stdout, first_stderr = first.communicate(timeout=30)

    assert second.returncode == 0, second.stderr
    assert second.stdout.splitlines() == ["7"]
    assert first.returncode == 0, first_stderr
    assert first_stdout.splitlines() == ["7"]
