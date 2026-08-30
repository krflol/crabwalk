from __future__ import annotations

import email.policy
import tarfile
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace

import pytest

from crabwalk import build_backend
from crabwalk._version import RUNTIME_DISTRIBUTION_REQUIREMENT
from crabwalk.compiler.capabilities import capability_contract
from crabwalk.project_metadata import read_application_metadata


def _application(root: Path) -> Path:
    package = root / "src" / "metadata_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        """\
from crabwalk import rust

@rust.fn
def double(value: rust.u64) -> rust.u64:
    return value * 2
""",
        encoding="utf-8",
    )
    (package / "cli.py").write_text(
        "def main() -> None:\n    print('metadata-app')\n",
        encoding="utf-8",
    )
    (package / "templates").mkdir()
    (package / "templates" / "message.txt").write_text("hello\n", encoding="utf-8")
    (root / "README.md").write_text("# Metadata app\n", encoding="utf-8")
    (root / "LICENSE").write_text("test license\n", encoding="utf-8")
    project = root / "pyproject.toml"
    project.write_text(
        """\
[build-system]
requires = ["crabwalk-lang>=1.1,<1.2"]
build-backend = "crabwalk.build_backend"

[project]
name = "metadata-app"
version = "2.3.4"
description = "Metadata-preserving native application"
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
license-files = ["LICENSE"]
dependencies = ["requests>=2"]
keywords = ["native", "rust"]
classifiers = ["Programming Language :: Python :: 3"]
authors = [{name = "Ada", email = "ada@example.test"}]

[project.optional-dependencies]
plot = ["matplotlib>=3; python_version >= '3.11'"]

[project.scripts]
metadata-app = "metadata_app.cli:main"

[project.entry-points."metadata.plugins"]
default = "metadata_app:double"

[project.urls]
Documentation = "https://example.test/docs"

[tool.crabwalk]
packages = ["src/metadata_app"]
wheel-include = ["templates/*.txt"]
""",
        encoding="utf-8",
    )
    return project


def test_application_metadata_merges_runtime_and_project_contract(
    tmp_path: Path,
) -> None:
    project = _application(tmp_path)

    metadata = read_application_metadata(project)
    message = BytesParser(policy=email.policy.compat32).parsebytes(
        metadata.core_metadata(RUNTIME_DISTRIBUTION_REQUIREMENT)
    )

    assert message["Name"] == "metadata-app"
    assert message["Version"] == "2.3.4"
    assert message["Description-Content-Type"] == "text/markdown"
    assert message.get_all("Requires-Dist") == [
        "requests>=2",
        RUNTIME_DISTRIBUTION_REQUIREMENT,
        "matplotlib>=3; (python_version >= '3.11') and extra == \"plot\"",
    ]
    assert message.get_all("Provides-Extra") == ["plot"]
    assert message.get_payload().strip() == "# Metadata app"
    assert metadata.entry_points_text() == (
        b"[console_scripts]\nmetadata-app = metadata_app.cli:main\n\n"
        b"[metadata.plugins]\ndefault = metadata_app:double\n"
    )
    assert metadata.license_files[0][0] == "LICENSE"
    assert metadata.license_files[0][1].replace(b"\r\n", b"\n") == b"test license\n"


def test_backend_prepares_metadata_and_forwards_native_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _application(tmp_path)
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def fake_build(package: Path, output: str, **options: object) -> object:
        captured.update(package=package, output=output, **options)
        wheel = Path(output) / "metadata_app-2.3.4-cp311-cp311-test.whl"
        return SimpleNamespace(path=wheel)

    monkeypatch.setattr(build_backend, "build_crabwalk_wheel", fake_build)
    metadata_name = build_backend.prepare_metadata_for_build_wheel(
        str(tmp_path / "prepared")
    )
    wheel_name = build_backend.build_wheel(
        str(tmp_path / "dist"),
        {"crabwalk-locked": "true", "crabwalk-offline": "false"},
    )

    assert metadata_name == "metadata_app-2.3.4.dist-info"
    prepared = tmp_path / "prepared" / metadata_name
    assert (prepared / "METADATA").is_file()
    assert (prepared / "entry_points.txt").is_file()
    assert (prepared / "licenses" / "LICENSE").is_file()
    assert wheel_name == "metadata_app-2.3.4-cp311-cp311-test.whl"
    assert captured["package"] == tmp_path / "src" / "metadata_app"
    assert captured["project"] == tmp_path / "pyproject.toml"
    assert captured["locked"] is True
    assert captured["offline"] is False


@capability_contract("packaging.metadata-sdist", native=False)
def test_backend_sdist_is_deterministic_and_contains_native_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _application(tmp_path)
    monkeypatch.chdir(tmp_path)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first_name = build_backend.build_sdist(str(first_dir))
    second_name = build_backend.build_sdist(str(second_dir))

    first = first_dir / first_name
    second = second_dir / second_name
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first, "r:gz") as archive:
        names = set(archive.getnames())
    prefix = "metadata-app-2.3.4"
    assert f"{prefix}/pyproject.toml" in names
    assert f"{prefix}/PKG-INFO" in names
    assert f"{prefix}/README.md" in names
    assert f"{prefix}/LICENSE" in names
    assert f"{prefix}/src/metadata_app/__init__.py" in names
    assert f"{prefix}/src/metadata_app/templates/message.txt" in names
