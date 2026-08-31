from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_typed_crate_adapters import ADAPTER_SOURCE


@capability_contract(
    "crate.typed-value",
    "crate.typed-callback",
    "crate.buffer-adapter",
)
def test_typed_path_crate_value_and_callback_run_natively(tmp_path: Path) -> None:
    native = tmp_path / "native"
    source_directory = native / "src"
    source_directory.mkdir(parents=True)
    (native / "Cargo.toml").write_text(
        """\
[package]
name = "native-adapter"
version = "0.1.0"
edition = "2024"

[lib]
path = "src/lib.rs"
""",
        encoding="utf-8",
    )
    (source_directory / "lib.rs").write_text(
        """\
pub mod model {
    pub struct Counter(pub u64);

    pub fn make_counter(value: u64) -> Counter {
        Counter(value)
    }

    pub fn counter_value(counter: &Counter) -> u64 {
        counter.0
    }
}

pub fn apply_twice<F>(value: u64, callback: F) -> u64
where
    F: Fn(u64) -> u64,
{
    callback(callback(value))
}

pub fn byte_sum(values: &[u8]) -> u64 {
    values.iter().map(|value| u64::from(*value)).sum()
}
""",
        encoding="utf-8",
    )
    source = tmp_path / "adapter.py"
    source.write_text(
        ADAPTER_SOURCE
        + """\
@rust.extern(native, path="byte_sum", effects=[rust.Pure])
def byte_sum(values: rust.Buffer[rust.u8]) -> rust.u64:
    ...

@rust.fn
def adapted_buffer(values: rust.Buffer[rust.u8]) -> rust.u64:
    return byte_sum(values)

print(adapted(40))
print(adapted.__crabwalk__["gil_released"])
print(adapted_buffer(b"ABC"))
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
    assert result.stdout.splitlines() == ["42", "True", "198"]
