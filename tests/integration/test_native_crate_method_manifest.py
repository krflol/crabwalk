from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_crate_method_manifest import CRATE_METHOD_SOURCE


@capability_contract("crate.builder-method-error")
def test_external_builder_method_closure_and_typed_error_run_natively(
    tmp_path: Path,
) -> None:
    native = tmp_path / "native"
    source_directory = native / "src"
    source_directory.mkdir(parents=True)
    (native / "Cargo.toml").write_text(
        """\
[package]
name = "builder-adapter"
version = "0.1.0"
edition = "2024"

[lib]
path = "src/lib.rs"
""",
        encoding="utf-8",
    )
    (source_directory / "lib.rs").write_text(
        """\
pub struct Builder(Vec<u64>);
pub struct Batch(Vec<u64>);

pub fn make_builder() -> Builder { Builder(Vec::new()) }
pub fn builder_push(builder: &mut Builder, value: u64) { builder.0.push(value); }
pub fn builder_finish(builder: Builder) -> Result<Batch, String> {
    if builder.0.first() == Some(&0) {
        Err(String::from("invalid zero batch"))
    } else {
        Ok(Batch(builder.0))
    }
}
pub fn batch_transform<F>(batch: &Batch, callback: F) -> Vec<u64>
where F: Fn(u64) -> u64 {
    batch.0.iter().copied().map(callback).collect()
}
""",
        encoding="utf-8",
    )
    source = tmp_path / "builder.py"
    source.write_text(
        CRATE_METHOD_SOURCE
        + """
print(build_and_transform(20))
try:
    build_and_transform(0)
except Exception as error:
    print(type(error).__name__)
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["CRABWALK_PROGRESS"] = "never"

    result = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["[40, 42]", "CrabwalkRustError"]
