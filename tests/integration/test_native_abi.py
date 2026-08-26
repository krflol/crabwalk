from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_panics_are_contained_and_primitive_work_releases_python(
    tmp_path: Path,
) -> None:
    source = tmp_path / "abi_app.py"
    source.write_text(
        """\
import threading

from crabwalk import CrabwalkPanicError, rust

@rust.fn
def divide(value: rust.u64, divisor: rust.u64) -> rust.u64:
    return value / divisor

@rust.fn
def add_one(value: rust.u64) -> rust.u64:
    \"\"\"Add one natively.\"\"\"
    return value + 1

@rust.fn
def fibonacci(value: rust.u64) -> rust.u64:
    if value <= 1:
        return value
    return fibonacci(value - 1) + fibonacci(value - 2)

@rust.fn
def invert(value: rust.bool) -> rust.bool:
    return not value

@rust.fn
def signed_byte(value: rust.i8) -> rust.i8:
    return value

@rust.fn
def single_precision(value: rust.f32) -> rust.f32:
    return value

@rust.fn
def optional_byte(value: rust.Option[rust.u8]) -> rust.Option[rust.u8]:
    return value

for operation in (lambda: divide(1, 0), lambda: add_one((1 << 64) - 1)):
    try:
        operation()
    except CrabwalkPanicError as error:
        print(type(error).__name__, bool(str(error)))

print(divide(12, 3))
print(add_one.__doc__)
print(invert(True), signed_byte(-128), single_precision(2), optional_byte(None), optional_byte(7))
for function, value in (
    (invert, 1),
    (signed_byte, True),
    (signed_byte, -129),
    (single_precision, True),
    (single_precision, 3.5e38),
    (optional_byte, 256),
):
    try:
        function(value)
    except Exception as error:
        print(type(error).__name__, "argument 'value'" in str(error))

started = threading.Event()
stop = threading.Event()
counter = [0]
def python_worker():
    started.set()
    while not stop.is_set():
        counter[0] += 1

thread = threading.Thread(target=python_worker)
thread.start()
started.wait()
before = counter[0]
print(fibonacci(42))
after = counter[0]
stop.set()
thread.join()
print(after - before > 1000)
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")

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
        "CrabwalkPanicError True",
        "CrabwalkPanicError True",
        "4",
        "Add one natively.",
        "False -128 2.0 None 7",
        "TypeError True",
        "TypeError True",
        "OverflowError True",
        "TypeError True",
        "OverflowError True",
        "OverflowError True",
        "267914296",
        "True",
    ]
