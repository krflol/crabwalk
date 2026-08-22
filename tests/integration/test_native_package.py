from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _create_package(root: Path) -> Path:
    package = root / "native_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        """\
from crabwalk import rust

regex = rust.crate("regex", version="1")

from .math import double
""",
        encoding="utf-8",
    )
    (package / "math.py").write_text(
        """\
from crabwalk import rust

@rust.fn
def double(value: rust.u64) -> rust.u64:
    return value * 2
""",
        encoding="utf-8",
    )
    (package / "facade.py").write_text(
        """\
from crabwalk import rust

from . import double

@rust.fn
def plus_one(value: rust.u64) -> rust.u64:
    return double(value) + 1
""",
        encoding="utf-8",
    )
    (package / "text.py").write_text(
        """\
from crabwalk import rust

from . import regex
from . import facade

@rust.fn
def contains_number(value: rust.Str) -> rust.bool:
    return regex.Regex.new(r"\\d+").unwrap().is_match(value)

@rust.fn
def through_module(value: rust.u64) -> rust.u64:
    return facade.plus_one(value)
""",
        encoding="utf-8",
    )
    (package / "app.py").write_text(
        """\
from .facade import plus_one
from .math import double
from .text import contains_number, through_module

print(double(21))
print(plus_one(10))
print(contains_number("room 7"))
print(contains_number("none"))
print(through_module(8))
print(double.__crabwalk__["extension_name"] == plus_one.__crabwalk__["extension_name"])
print(plus_one.__crabwalk__["extension_name"] == contains_number.__crabwalk__["extension_name"])
print(contains_number.__crabwalk__["cache_hit"])
""",
        encoding="utf-8",
    )
    return package


def test_regular_python_package_compiles_as_one_native_extension(
    tmp_path: Path,
) -> None:
    _create_package(tmp_path)
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root / "src"), str(tmp_path)))

    command = [sys.executable, "-u", "-m", "native_pkg.app"]
    first = subprocess.run(
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    assert first.stdout.splitlines() == [
        "42",
        "21",
        "True",
        "False",
        "17",
        "True",
        "True",
        "False",
    ]

    second = subprocess.run(
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    assert second.stdout.splitlines()[-1] == "True"


def test_bad_crate_api_maps_rustc_error_to_python_call(tmp_path: Path) -> None:
    source = tmp_path / "crate_api_error.py"
    source.write_text(
        """\
from crabwalk import rust

regex = rust.crate("regex", version="1")

@rust.fn
def contains_number(value: rust.Str) -> rust.bool:
    return regex.Regex.new(r"\\d+").unwrap().missing_method(value)
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert result.returncode != 0
    assert "CRAB301 Rust compilation failed" in result.stderr
    assert "missing_method" in result.stderr
    assert "crate_api_error.py:7" in result.stderr


def test_bad_path_dependency_maps_resolution_error_to_crate_declaration(
    tmp_path: Path,
) -> None:
    source = tmp_path / "path_resolution_error.py"
    source.write_text(
        """\
from crabwalk import rust

missing = rust.crate("crabwalk-missing-fixture", path="./does-not-exist")

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    result = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert result.returncode != 0
    assert "CRAB302 Cargo dependency resolution failed" in result.stderr
    assert "path_resolution_error.py:3:1" in result.stderr
    assert "does-not-exist" in result.stderr
