from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_methods_traits import EXTERNAL_TRAIT_SOURCE, METHOD_TRAIT_SOURCE


@capability_contract("traits.dynamic-dispatch")
def test_inherent_methods_and_dynamic_dispatch_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "methods_traits.py"
    source.write_text(
        METHOD_TRAIT_SOURCE + "\nprint(method_and_trait_demo())\n",
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
    assert result.stdout.splitlines() == ["31"]


@capability_contract("traits.external-implementation")
def test_external_trait_implementation_runs_natively(tmp_path: Path) -> None:
    native = tmp_path / "native"
    (native / "src").mkdir(parents=True)
    (native / "Cargo.toml").write_text(
        """\
[package]
name = "native-trait"
version = "0.1.0"
edition = "2024"

[lib]
path = "src/lib.rs"
""",
        encoding="utf-8",
    )
    (native / "src" / "lib.rs").write_text(
        """\
pub trait Tick {
    fn tick(&mut self, amount: u64) -> u64;
}
""",
        encoding="utf-8",
    )
    source = tmp_path / "external_trait.py"
    source.write_text(
        EXTERNAL_TRAIT_SOURCE + "\nprint(external_trait_demo())\n",
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
    assert result.stdout.strip() == "42"
