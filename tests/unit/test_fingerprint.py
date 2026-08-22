from __future__ import annotations

from pathlib import Path

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
