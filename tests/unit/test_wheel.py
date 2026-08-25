from __future__ import annotations

import csv
import hashlib
import io
import json
import tomllib
import zipfile
from pathlib import Path

import pytest

from crabwalk.compiler.frontend import analyze_project_path
from crabwalk.diagnostics import CrabwalkCompilationError
from crabwalk.runtime import (
    _cargo_policy_metadata,
    _dependency_lock_hash_metadata,
    _load_prebuilt_compilation,
)
from crabwalk.service import CompilationResult
from crabwalk import RUNTIME_ABI_VERSION, RUNTIME_DISTRIBUTION, __version__
from crabwalk._version import PREBUILT_MANIFEST_SCHEMA_VERSION
from crabwalk.wheel import _package_entries, build_wheel


class _FakeService:
    def __init__(self, result: CompilationResult) -> None:
        self.result = result
        self.calls: list[tuple[Path, dict[str, object]]] = []

    def compile_path(self, path: Path, **options: object) -> CompilationResult:
        self.calls.append((path, options))
        return self.result


def test_wheel_contains_sources_verified_native_artifact_and_valid_record(
    tmp_path: Path,
) -> None:
    package = tmp_path / "sample_pkg"
    package.mkdir()
    source = package / "__init__.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def double(value: rust.u64) -> rust.u64:
    return value * 2
""",
        encoding="utf-8",
    )
    ignored = package / ".crabwalk"
    ignored.mkdir()
    (ignored / "private.bin").write_bytes(b"not wheel content")
    (package / "undeclared.html").write_text("not package data", encoding="utf-8")

    artifact = tmp_path / "_crabwalk_sample_deadbeef.pyd"
    artifact.write_bytes(b"native-extension-placeholder")
    ir = analyze_project_path(package, "sample_pkg")
    compilation = CompilationResult(
        ir=ir,
        fingerprint="deadbeef" * 8,
        extension_name="_crabwalk_sample_deadbeef",
        project_root=tmp_path,
        generated_dir=tmp_path / "generated",
        artifact=artifact,
        cache_hit=False,
        module=None,
        command=("cargo", "build"),
        build_inputs={
            "cargo_policy": {"locked": False, "offline": False},
            "dependency_lock_hash": "c" * 64,
        },
    )
    service = _FakeService(compilation)

    result = build_wheel(
        package,
        tmp_path / "dist",
        distribution_name="sample-project",
        version="1.2.3",
        service=service,  # type: ignore[arg-type]
    )

    assert service.calls == [
        (
            package,
            {
                "module_name": "sample_pkg",
                "mode": "build",
                "load": False,
                "locked": False,
                "offline": False,
            },
        )
    ]
    with zipfile.ZipFile(result.path) as archive:
        names = set(archive.namelist())
        assert "sample_pkg/__init__.py" in names
        assert "sample_pkg/_crabwalk_prebuilt.json" in names
        native_name = "sample_pkg/_crabwalk_native/_crabwalk_sample_deadbeef.pyd"
        assert native_name in names
        assert not any(".crabwalk" in name for name in names)
        assert "sample_pkg/undeclared.html" not in names

        manifest = json.loads(archive.read("sample_pkg/_crabwalk_prebuilt.json"))
        assert manifest["source_hash"] == ir.source_hash
        assert manifest["compiler_input_hash"] == ir.compiler_input_hash
        assert manifest["wheel_source_integrity_hash"] == ir.wheel_source_integrity_hash
        assert manifest["artifact"] == native_name.removeprefix("sample_pkg/")
        assert manifest["extension_name"] == compilation.extension_name
        assert manifest["runtime_abi_version"] == RUNTIME_ABI_VERSION
        assert manifest["crabwalk_version"] == __version__
        assert manifest["schema_version"] == PREBUILT_MANIFEST_SCHEMA_VERSION
        assert manifest["cargo_policy"] == {"locked": False, "offline": False}
        assert manifest["dependency_lock_hash"] == "c" * 64

        metadata = archive.read("sample_project-1.2.3.dist-info/METADATA").decode(
            "utf-8"
        )
        assert f"Requires-Dist: {RUNTIME_DISTRIBUTION}=={__version__}\n" in metadata

        record_name = "sample_project-1.2.3.dist-info/RECORD"
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode())))
        recorded = {row[0] for row in rows}
        assert recorded == names
        assert next(row for row in rows if row[0] == record_name)[1:] == ["", ""]


def test_project_and_generated_wheel_share_the_runtime_distribution_name() -> None:
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["name"] == RUNTIME_DISTRIBUTION


def test_wheel_rejects_non_importable_package_name(tmp_path: Path) -> None:
    package = tmp_path / "not-importable"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    try:
        build_wheel(package, tmp_path / "dist")
    except CrabwalkCompilationError as error:
        assert error.diagnostics[0].code == "CRAB505"
    else:
        raise AssertionError("invalid package name was accepted")


def test_package_data_is_allowlisted_and_sensitive_files_are_refused(
    tmp_path: Path,
) -> None:
    package = tmp_path / "data_pkg"
    (package / "templates").mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    template = package / "templates" / "page.html"
    template.write_text("<h1>Hello</h1>", encoding="utf-8")

    default_entries = _package_entries(package)
    assert "data_pkg/__init__.py" in default_entries
    assert "data_pkg/templates/page.html" not in default_entries

    included = _package_entries(package, ("templates/*.html",))
    assert included["data_pkg/templates/page.html"] == b"<h1>Hello</h1>"

    (package / ".env").write_text("TOKEN=do-not-package", encoding="utf-8")
    with pytest.raises(CrabwalkCompilationError) as captured:
        _package_entries(package, ("*",))
    assert captured.value.diagnostics[0].code == "CRAB507"


def test_prebuilt_manifest_rejects_runtime_abi_before_native_loading(
    tmp_path: Path,
) -> None:
    package = tmp_path / "abi_pkg"
    package.mkdir()
    source = package / "__init__.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def value() -> rust.u64:
    return 1
""",
        encoding="utf-8",
    )
    ir = analyze_project_path(package, "abi_pkg")
    (package / "_crabwalk_prebuilt.json").write_text(
        json.dumps(
            {
                "schema_version": PREBUILT_MANIFEST_SCHEMA_VERSION,
                "crabwalk_version": __version__,
                "runtime_abi_version": RUNTIME_ABI_VERSION + 1,
                "module_name": "abi_pkg",
                "compiler_input_hash": ir.compiler_input_hash,
                "wheel_source_integrity_hash": ir.wheel_source_integrity_hash,
                "fingerprint": "a" * 64,
                "extension_name": "_crabwalk_abi",
                "artifact": "_crabwalk_native/missing.pyd",
                "artifact_sha256": "b" * 64,
                "cargo_policy": {"locked": True, "offline": False},
                "dependency_lock_hash": "c" * 64,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        _load_prebuilt_compilation(source, "abi_pkg")

    assert captured.value.diagnostics[0].code == "CRAB405"
    assert "runtime ABI" in captured.value.diagnostics[0].message


def test_prebuilt_manifest_restores_locked_cargo_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "locked_pkg"
    native = package / "_crabwalk_native"
    native.mkdir(parents=True)
    source = package / "__init__.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def value() -> rust.u64:
    return 1
""",
        encoding="utf-8",
    )
    artifact = native / "locked.pyd"
    artifact.write_bytes(b"verified-native-placeholder")
    ir = analyze_project_path(package, "locked_pkg")
    lock_hash = "d" * 64
    (package / "_crabwalk_prebuilt.json").write_text(
        json.dumps(
            {
                "schema_version": PREBUILT_MANIFEST_SCHEMA_VERSION,
                "crabwalk_version": __version__,
                "runtime_abi_version": RUNTIME_ABI_VERSION,
                "module_name": "locked_pkg",
                "compiler_input_hash": ir.compiler_input_hash,
                "wheel_source_integrity_hash": ir.wheel_source_integrity_hash,
                "fingerprint": "a" * 64,
                "extension_name": "_crabwalk_locked",
                "artifact": "_crabwalk_native/locked.pyd",
                "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                "cargo_policy": {"locked": True, "offline": False},
                "dependency_lock_hash": lock_hash,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("crabwalk.runtime.load_extension", lambda *_args: object())

    result = _load_prebuilt_compilation(source, "locked_pkg")

    assert result is not None
    assert result.build_inputs == {
        "cargo_policy": {"locked": True, "offline": False},
        "dependency_lock_hash": lock_hash,
    }
    assert _cargo_policy_metadata(result) == {
        "locked": True,
        "offline": False,
        "origin": "prebuilt",
    }
    assert _dependency_lock_hash_metadata(result) == lock_hash
