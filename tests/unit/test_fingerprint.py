from __future__ import annotations

from pathlib import Path
import subprocess

from crabwalk.build.fingerprint import build_fingerprint
from crabwalk.compiler.frontend import analyze_path


def test_build_environment_and_cargo_config_are_hashed_without_leaking_values(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    source = tmp_path / "fingerprint.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    ir = analyze_path(source)
    monkeypatch.delenv("RUSTFLAGS", raising=False)  # type: ignore[attr-defined]
    baseline, _ = build_fingerprint(ir)

    secret_value = "--cfg private_build_value"
    monkeypatch.setenv("RUSTFLAGS", secret_value)  # type: ignore[attr-defined]
    with_flags, inputs = build_fingerprint(ir)
    assert with_flags != baseline
    recorded = inputs["build_environment"]["RUSTFLAGS"]  # type: ignore[index]
    assert recorded["set"] is True
    assert secret_value not in str(recorded)

    cargo = tmp_path / ".cargo"
    cargo.mkdir()
    config = cargo / "config.toml"
    config.write_text('[build]\nrustflags = ["--cfg", "one"]\n', encoding="utf-8")
    first_config, _ = build_fingerprint(ir)
    config.write_text('[build]\nrustflags = ["--cfg", "two"]\n', encoding="utf-8")
    second_config, _ = build_fingerprint(ir)
    assert first_config != second_config


def test_path_dependency_assets_and_project_toolchain_are_fingerprint_inputs(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    dependency = tmp_path / "native"
    (dependency / "src").mkdir(parents=True)
    (dependency / "Cargo.toml").write_text(
        '[package]\nname = "native-input"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (dependency / "src" / "lib.rs").write_text(
        'pub const DATA: &[u8] = include_bytes!("../model.bin");\n',
        encoding="utf-8",
    )
    asset = dependency / "model.bin"
    asset.write_bytes(b"first")
    source = tmp_path / "path_inputs.py"
    source.write_text(
        """\
from crabwalk import rust
native = rust.crate("native-input", path="./native")

@rust.fn
def value() -> rust.u64:
    return native.value()
""",
        encoding="utf-8",
    )
    ir = analyze_path(source)
    calls: list[Path] = []

    def tool_version(
        command: list[str],
        *,
        cwd: Path,
        **_kwargs: object,
    ) -> str:
        calls.append(cwd)
        return f"{command[0]} test toolchain"

    monkeypatch.setattr(subprocess, "check_output", tool_version)  # type: ignore[attr-defined]
    (tmp_path / "rust-toolchain.toml").write_text(
        '[toolchain]\nchannel = "stable"\n', encoding="utf-8"
    )
    first, first_inputs = build_fingerprint(ir, project_root=tmp_path)
    asset.write_bytes(b"second")
    second, _ = build_fingerprint(ir, project_root=tmp_path)

    assert len(calls) == 2
    (tmp_path / "rust-toolchain.toml").write_text(
        '[toolchain]\nchannel = "nightly"\n', encoding="utf-8"
    )
    third, _ = build_fingerprint(ir, project_root=tmp_path)

    assert first != second
    assert second != third
    assert len(calls) == 4
    assert calls and all(path == tmp_path for path in calls)
    assert first_inputs["toolchain_files"]


def test_declared_extra_files_and_environment_are_hashed_without_values(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    source = tmp_path / "extra_inputs.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    asset = tmp_path / "schema.proto"
    asset.write_text("first", encoding="utf-8")
    ir = analyze_path(source)
    monkeypatch.setenv("APP_NATIVE_MODE", "one")  # type: ignore[attr-defined]
    first, inputs = build_fingerprint(
        ir,
        project_root=tmp_path,
        extra_files=(asset,),
        extra_env=("APP_NATIVE_MODE",),
    )
    asset.write_text("second", encoding="utf-8")
    monkeypatch.setenv("APP_NATIVE_MODE", "two")  # type: ignore[attr-defined]
    second, _ = build_fingerprint(
        ir,
        project_root=tmp_path,
        extra_files=(asset,),
        extra_env=("APP_NATIVE_MODE",),
    )

    assert first != second
    recorded = inputs["build_environment"]["APP_NATIVE_MODE"]  # type: ignore[index]
    assert "one" not in str(recorded)
