from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract


@capability_contract("ownership.audited-gil-release")
def test_owned_blocking_adapter_releases_gil_natively(tmp_path: Path) -> None:
    native = tmp_path / "native"
    (native / "src").mkdir(parents=True)
    (native / "Cargo.toml").write_text(
        """\
[package]
name = "native-wait"
version = "0.1.0"
edition = "2024"

[lib]
path = "src/lib.rs"
""",
        encoding="utf-8",
    )
    (native / "src" / "lib.rs").write_text(
        """\
pub fn wait_len(values: Vec<u64>) -> usize {
    std::thread::sleep(std::time::Duration::from_millis(250));
    values.len()
}
""",
        encoding="utf-8",
    )
    source = tmp_path / "gil_release.py"
    source.write_text(
        """\
import threading
import time

from crabwalk import rust

native = rust.crate("native-wait", path="./native")

@rust.extern(
    native,
    path="wait_len",
    effects=[rust.OpaqueCrateCall, rust.Blocking, rust.MayPanic],
)
def wait_len(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    ...

@rust.fn(release_gil=True)
def run(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    return wait_len(values)

running = True
counter = 0

def worker():
    global counter
    while running:
        counter += 1

thread = threading.Thread(target=worker)
thread.start()
time.sleep(0.02)
before = counter
values = rust.Vec[rust.u64]([1, 2, 3])
print(run(values))
after = counter
running = False
thread.join()
print(run.__crabwalk__["gil_released"])
print(run.__crabwalk__["gil_policy"])
print(values.moved)
print(after - before > 100)
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
    assert result.stdout.splitlines() == [
        "3",
        "True",
        "explicit audited release",
        "True",
        "True",
    ]
