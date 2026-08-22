from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
