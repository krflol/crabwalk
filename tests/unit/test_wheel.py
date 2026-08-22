from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from crabwalk.compiler.frontend import analyze_project_path
from crabwalk.diagnostics import CrabwalkCompilationError
from crabwalk.runtime import _load_prebuilt_compilation
from crabwalk.service import CompilationResult
from crabwalk import RUNTIME_ABI_VERSION, __version__
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
        assert manifest["artifact"] == native_name.removeprefix("sample_pkg/")
        assert manifest["extension_name"] == compilation.extension_name
        assert manifest["runtime_abi_version"] == RUNTIME_ABI_VERSION
        assert manifest["crabwalk_version"] == __version__

        record_name = "sample_project-1.2.3.dist-info/RECORD"
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode())))
        recorded = {row[0] for row in rows}
        assert recorded == names
        assert next(row for row in rows if row[0] == record_name)[1:] == ["", ""]


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
                "schema_version": 2,
                "crabwalk_version": __version__,
                "runtime_abi_version": RUNTIME_ABI_VERSION + 1,
                "module_name": "abi_pkg",
                "source_hash": ir.source_hash,
                "fingerprint": "a" * 64,
                "extension_name": "_crabwalk_abi",
                "artifact": "_crabwalk_native/missing.pyd",
                "artifact_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        _load_prebuilt_compilation(source, "abi_pkg")

    assert captured.value.diagnostics[0].code == "CRAB405"
    assert "runtime ABI" in captured.value.diagnostics[0].message
