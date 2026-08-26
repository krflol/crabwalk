from __future__ import annotations

import json
import os
import subprocess
import sys
import venv
import zipfile
from pathlib import Path


def _write_package(root: Path) -> Path:
    package = root / "wheel_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        """\
from crabwalk import rust

from .math import double
from .model import Point
from .text import contains_number

__all__ = ["Point", "contains_number", "double"]
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
    (package / "model.py").write_text(
        """\
from crabwalk import rust

@rust.struct
class Point:
    x: rust.i64
    y: rust.i64
""",
        encoding="utf-8",
    )
    (package / "text.py").write_text(
        """\
from crabwalk import rust

regex = rust.crate("regex", version="1")

@rust.fn
def contains_number(value: rust.Str) -> rust.bool:
    return regex.Regex.new(r"\\d+").unwrap().is_match(value)
""",
        encoding="utf-8",
    )
    (package / "presentation.py").write_text(
        "LABEL = 'python-only package data'\n",
        encoding="utf-8",
    )
    return package


def _without_rust_toolchain(environment: dict[str, str]) -> dict[str, str]:
    result = environment.copy()
    kept: list[str] = []
    for value in result.get("PATH", "").split(os.pathsep):
        directory = Path(value)
        if any(
            (directory / executable).is_file()
            for executable in ("cargo", "cargo.exe", "rustc", "rustc.exe")
        ):
            continue
        kept.append(value)
    result["PATH"] = os.pathsep.join(kept)
    return result


def test_installed_wheel_uses_embedded_extension_without_rust(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    build_root = tmp_path / "build-input"
    package = _write_package(build_root)
    dist = tmp_path / "dist"
    build_environment = os.environ.copy()
    build_environment["PYTHONPATH"] = str(root / "src")
    built = subprocess.run(
        [
            sys.executable,
            "-u",
            "-m",
            "crabwalk.cli",
            "wheel",
            str(package),
            "--output-dir",
            str(dist),
            "--name",
            "wheel-demo",
            "--version",
            "1.0.0",
        ],
        cwd=root,
        env=build_environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    wheel = Path(built.stdout.strip())
    assert wheel.is_file()
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "wheel_pkg/_crabwalk_prebuilt.json" in names
        assert any(name.startswith("wheel_pkg/_crabwalk_native/") for name in names)
        assert not any("/.crabwalk/" in name for name in names)
        manifest = json.loads(archive.read("wheel_pkg/_crabwalk_prebuilt.json"))
        assert manifest["cargo_policy"] == {"locked": False, "offline": False}
        assert len(manifest["dependency_lock_hash"]) == 64

    runtime_dist = tmp_path / "runtime-dist"
    runtime_built = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(root),
            "--no-deps",
            "--wheel-dir",
            str(runtime_dist),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert runtime_built.returncode == 0, runtime_built.stderr
    runtime_wheels = list(runtime_dist.glob("crabwalk_lang-*.whl"))
    assert len(runtime_wheels) == 1
    runtime_wheel = runtime_wheels[0]
    with zipfile.ZipFile(runtime_wheel) as archive:
        assert "crabwalk/runtime.py" in archive.namelist()
        assert "crabwalk/build/cache.py" in archive.namelist()
        assert "crabwalk/compiler/frontend.py" in archive.namelist()
        assert not any(".crabwalk" in name for name in archive.namelist())

    consumer = tmp_path / "consumer"
    environment_directory = consumer / "venv"
    consumer.mkdir()
    venv.EnvBuilder(with_pip=True).create(environment_directory)
    executable = environment_directory / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    install_environment = os.environ.copy()
    install_environment.pop("PYTHONPATH", None)
    install_environment.pop("PIP_NO_DEPS", None)
    installed = subprocess.run(
        [
            str(executable),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(runtime_dist),
            "--find-links",
            str(dist),
            "wheel-demo==1.0.0",
        ],
        cwd=consumer,
        env=install_environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr

    run_environment = _without_rust_toolchain(os.environ.copy())
    run_environment.pop("PYTHONPATH", None)
    run_environment["CRABWALK_PROGRESS"] = "always"
    script = """\
import json
import pathlib
import shutil
from wheel_pkg import Point, contains_number, double

point = Point(x=3, y=4)
print(double(21))
print(point.to_python())
print(contains_number("room 7"), contains_number("none"))
print(shutil.which("cargo"), shutil.which("rustc"))
print(double.__crabwalk__["cache_hit"])
print(json.dumps(double.__crabwalk__["cargo_policy"], sort_keys=True))
print(double.__crabwalk__["dependency_lock_hash"])
print(double.__crabwalk__["artifact"])
print((pathlib.Path.cwd() / ".crabwalk").exists())
"""
    executed = subprocess.run(
        [str(executable), "-u", "-c", script],
        cwd=consumer,
        env=run_environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert executed.returncode == 0, executed.stderr
    assert executed.stderr.count("Analyzing Python source") == 1
    assert executed.stderr.count("Crabwalk ready: wheel_pkg") == 1
    output = executed.stdout.splitlines()
    assert output[:4] == [
        "42",
        "{'x': 3, 'y': 4}",
        "True False",
        "None None",
    ]
    assert output[4] == "True"
    assert json.loads(output[5]) == {
        "locked": False,
        "offline": False,
        "origin": "prebuilt",
    }
    assert output[6] == manifest["dependency_lock_hash"]
    artifact = Path(output[7])
    assert artifact.is_file()
    assert artifact.parent.name == "_crabwalk_native"
    assert output[8] == "False"
    assert not (artifact.parent.parent / ".crabwalk").exists()

    installed_package = artifact.parent.parent
    # Python-only source is excluded from the native compiler hash but remains
    # covered by the wheel-wide integrity identity.
    (installed_package / "presentation.py").write_text(
        (installed_package / "presentation.py").read_text(encoding="utf-8")
        + "\n# tampered\n",
        encoding="utf-8",
    )
    rejected = subprocess.run(
        [str(executable), "-u", "-c", "import wheel_pkg"],
        cwd=consumer,
        env=run_environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert rejected.returncode != 0
    assert "CRAB405 Embedded native artifact is invalid" in rejected.stderr
    assert not (consumer / ".crabwalk").exists()
