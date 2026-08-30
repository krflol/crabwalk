from __future__ import annotations

import importlib.resources
import subprocess
import sys
from pathlib import Path


def test_pep561_marker_is_packaged() -> None:
    marker = importlib.resources.files("crabwalk").joinpath("py.typed")

    assert marker.is_file()


def test_public_package_passes_mypy_consumer_smoke(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        """\
from crabwalk import __version__, compile_source, rust

version: str = __version__
assert callable(compile_source)
assert rust.u64.name == "u64"
""",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(consumer)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
