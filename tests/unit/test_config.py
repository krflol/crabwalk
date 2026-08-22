from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.diagnostics import CrabwalkCompilationError
from crabwalk.service import default_service


def _project(tmp_path: Path, policy: str = "allow") -> tuple[Path, Path]:
    package = tmp_path / "src" / "configured_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        """\
from crabwalk import rust

@rust.fn
def hello(value: rust.u64) -> rust.u64:
    print(value)
    return value
""",
        encoding="utf-8",
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f"""\
[tool.crabwalk]
packages = ["src/configured_pkg"]
python-boundaries = "{policy}"
""",
        encoding="utf-8",
    )
    return pyproject, package


def test_configured_project_resolves_one_package_and_fingerprints_config(
    tmp_path: Path,
) -> None:
    pyproject, package = _project(tmp_path)
    first = default_service.compile_path(tmp_path, mode="expand")
    assert first.ir.module_name == "configured_pkg"
    assert first.project_root == tmp_path
    assert Path(first.ir.source_path) == package / "__init__.py"
    assert first.build_inputs is not None
    assert first.build_inputs["project_config_hash"] is not None

    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + "\n# fingerprint change\n",
        encoding="utf-8",
    )
    second = default_service.compile_path(tmp_path, mode="expand")
    assert first.fingerprint != second.fingerprint


def test_config_can_deny_python_runtime_boundaries(tmp_path: Path) -> None:
    _, package = _project(tmp_path, "deny")
    with pytest.raises(CrabwalkCompilationError) as captured:
        default_service.compile_path(package, mode="expand")
    assert captured.value.diagnostics[0].code == "CRAB203"


def test_config_rejects_source_outside_declared_packages(tmp_path: Path) -> None:
    _project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text(
        """\
from crabwalk import rust

@rust.fn
def value() -> rust.u64:
    return 1
""",
        encoding="utf-8",
    )
    with pytest.raises(CrabwalkCompilationError) as captured:
        default_service.compile_path(outside, mode="expand")
    assert captured.value.diagnostics[0].code == "CRAB012"
