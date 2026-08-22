from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_fibonacci_compiles_runs_and_reuses_cache(tmp_path: Path) -> None:
    other = tmp_path / "native_other.py"
    other.write_text(
        """\
from crabwalk import CrabwalkRustError, rust

@rust.fn
def fibonacci(n: rust.u64) -> rust.u64:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
""",
        encoding="utf-8",
    )
    source = tmp_path / "native_app.py"
    source.write_text(
        """\
from crabwalk import rust
import importlib.util
import sys

@rust.fn
def fibonacci(n: rust.u64) -> rust.u64:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

events = []
def trace(frame, event, argument):
    if frame.f_code.co_filename == __file__ and frame.f_code.co_name == "fibonacci":
        events.append(event)
    return trace

sys.settrace(trace)
print(fibonacci(20))
sys.settrace(None)
print(type(fibonacci).__name__)
print(fibonacci.__crabwalk__["cache_hit"])
print(len(events))
for value in (-1, 1 << 64, "wrong"):
    try:
        fibonacci(value)
    except Exception as error:
        print(type(error).__name__)

other_path = __file__.replace("native_app.py", "native_other.py")
spec = importlib.util.spec_from_file_location("native_other", other_path)
other_module = importlib.util.module_from_spec(spec)
sys.modules["native_other"] = other_module
spec.loader.exec_module(other_module)
print(other_module.fibonacci(10))
print(
    fibonacci.__crabwalk__["extension_name"]
    != other_module.fibonacci.__crabwalk__["extension_name"]
)
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")

    first = subprocess.run(
        [sys.executable, str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    assert first.stdout.splitlines() == [
        "6765",
        "RustFunction",
        "False",
        "0",
        "OverflowError",
        "OverflowError",
        "TypeError",
        "55",
        "True",
    ]

    second = subprocess.run(
        [sys.executable, str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    assert second.stdout.splitlines() == [
        "6765",
        "RustFunction",
        "True",
        "0",
        "OverflowError",
        "OverflowError",
        "TypeError",
        "55",
        "True",
    ]

    unsupported = tmp_path / "unsupported.py"
    unsupported.write_text(
        """\
from crabwalk import rust

@rust.fn
def unsupported(n: rust.u64) -> rust.u64:
    values = [n]
    return n
""",
        encoding="utf-8",
    )
    rejected = subprocess.run(
        [sys.executable, str(unsupported)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert rejected.returncode != 0
    assert "CRAB102 Unsupported construct in @rust.fn" in rejected.stderr
    assert "unsupported.py:5:14" in rejected.stderr

    overflow = tmp_path / "overflow.py"
    overflow.write_text(
        """\
from crabwalk import rust

@rust.fn
def overflow(n: rust.u64) -> rust.u64:
    return 18446744073709551615 + 1
""",
        encoding="utf-8",
    )
    rustc_rejected = subprocess.run(
        [sys.executable, str(overflow)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert rustc_rejected.returncode != 0
    assert "CRAB301 Rust compilation failed" in rustc_rejected.stderr
    assert "overflow.py:5:5" in rustc_rejected.stderr
    assert "arithmetic operation will overflow" in rustc_rejected.stderr

    core = tmp_path / "core.py"
    core.write_text(
        """\
from crabwalk import CrabwalkRustError, rust

@rust.fn
def sum_to(n: rust.u64) -> rust.u64:
    total: rust.u64 = 0
    for value in range(n):
        total += value
    return total

@rust.fn
def count_to(n: rust.u64) -> rust.u64:
    value: rust.u64 = 0
    while value < n:
        value += 1
    return value

@rust.fn
def between(n: rust.u64, low: rust.u64, high: rust.u64) -> rust.bool:
    return n >= low and n <= high

@rust.fn
def negate(n: rust.i64) -> rust.i64:
    return -n

@rust.fn
def ratio(x: rust.f64, y: rust.f64) -> rust.f64:
    return x / y

@rust.fn
def greet(name: rust.Str) -> rust.String:
    rust.println(name)
    return rust.String(name)

@rust.fn
def vector_len(n: rust.u64) -> rust.usize:
    values: rust.Vec[rust.u64] = rust.Vec([n, 1])
    values.push(2)
    return values.len()

@rust.fn
def maybe(n: rust.u64) -> rust.Option[rust.u64]:
    if n == 0:
        return None
    return rust.Some(n)

@rust.fn
def validate(n: rust.u64) -> rust.Result[rust.u64, rust.String]:
    if n == 0:
        return rust.Err("zero")
    return rust.Ok(n)

@rust.fn
def python_hello(name: rust.Str) -> rust.String:
    print(name)
    return rust.String(name)

@rust.fn
def call_python_hello(name: rust.Str) -> rust.String:
    return python_hello(name)

print(sum_to(10))
print(count_to(7))
print(between(5, 1, 10))
print(negate(-7))
print(ratio(5.0, 2.0))
print(greet("Alice"))
print(vector_len(9))
print(maybe(0))
print(maybe(5))
print(validate(5))
try:
    validate(0)
except CrabwalkRustError as error:
    print(type(error).__name__, error.rust_type, error.rust_message)
print(call_python_hello("Python boundary"))
""",
        encoding="utf-8",
    )
    core_result = subprocess.run(
        [sys.executable, "-u", str(core)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert core_result.returncode == 0, core_result.stderr
    assert core_result.stdout.splitlines() == [
        "45",
        "7",
        "True",
        "7",
        "2.5",
        "Alice",
        "Alice",
        "3",
        "None",
        "5",
        "5",
        "CrabwalkRustError rust.String zero",
        "Python boundary",
        "Python boundary",
    ]
