from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


SAFETY_SOURCE = """\
from __future__ import annotations

import threading
import builtins

from crabwalk import CrabwalkPanicError, CrabwalkRustError, rust


@rust.fn
def c_absolute(value: rust.i32) -> rust.i32:
    return rust.c_abs(value)


@rust.fn
def atomic_increment() -> rust.u64:
    return rust.unsafe_static_increment(1)


@rust.fn
def native_atomic_pair() -> rust.u64:
    first: rust.ThreadHandle[rust.u64] = rust.spawn(lambda: atomic_increment())
    second: rust.ThreadHandle[rust.u64] = rust.spawn(lambda: atomic_increment())
    return first.join() + second.join()


@rust.fn
def worker_failure() -> rust.Result[rust.u64, rust.String]:
    pool: rust.ThreadPool = rust.ThreadPool(1)
    pool.execute(lambda: rust.panic("worker failed"))
    rust.try_(pool.finish())
    return rust.Ok(1)


@rust.fn
def outer_failure() -> rust.u64:
    pool: rust.ThreadPool = rust.ThreadPool(1)
    return rust.panic("outer failed")


@rust.fn
def worker_and_outer_failure() -> rust.u64:
    pool: rust.ThreadPool = rust.ThreadPool(1)
    pool.execute(lambda: rust.panic("worker failed during outer unwind"))
    return rust.panic("outer failed with live worker")


@rust.fn
def python_result(value: rust.u64) -> rust.Result[rust.u64, rust.String]:
    print(value)
    if value == 0:
        return rust.Err("zero")
    if value == 9:
        return rust.panic("python result panic")
    return rust.Ok(value)


print("native-atomic", native_atomic_pair() == 3)

results: list[int] = []
threads = [threading.Thread(target=lambda: results.append(atomic_increment())) for _ in range(32)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print("atomic", sorted(results) == list(range(3, 35)))

try:
    c_absolute(-2147483648)
except CrabwalkPanicError as error:
    print("c-abs", "i32::MIN" in str(error))

try:
    worker_failure()
except CrabwalkRustError as error:
    print("worker", "worker failed" in str(error))

try:
    outer_failure()
except CrabwalkPanicError as error:
    print("outer", "outer failed" in str(error))

try:
    worker_and_outer_failure()
except CrabwalkPanicError as error:
    print("combined", "outer failed with live worker" in str(error))

print("python-result-ok", python_result(7) == 7)
try:
    python_result(0)
except CrabwalkRustError as error:
    print("python-result-err", error.rust_type, error.rust_message)
try:
    python_result(9)
except CrabwalkPanicError as error:
    print(
        "python-result-panic",
        "python result panic" in str(error),
        error.panic_message == "python result panic",
        bool(error.call_site),
    )

real_print = builtins.print
def prefixed_user_failure(value):
    raise RuntimeError("CrabwalkPanicError: raised by user Python")
builtins.print = prefixed_user_failure
try:
    python_result(7)
except RuntimeError as error:
    user_failure = (
        type(error) is RuntimeError
        and "raised by user Python" in str(error)
        and not isinstance(error, CrabwalkPanicError)
    )
finally:
    builtins.print = real_print
print("python-prefix-is-not-native", user_failure)
"""


def test_unsafe_and_double_panic_edges_survive_in_subprocess(tmp_path: Path) -> None:
    source = tmp_path / "safety_boundaries.py"
    source.write_text(SAFETY_SOURCE, encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["CRABWALK_PROGRESS"] = "never"
    # Cargo profile environment variables normally override Cargo.toml. Crabwalk
    # must force unwind so its panic-to-Python boundary remains valid.
    environment["CARGO_PROFILE_RELEASE_PANIC"] = "abort"

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
        "native-atomic True",
        "atomic True",
        "c-abs True",
        "worker True",
        "outer True",
        "combined True",
        "7",
        "python-result-ok True",
        "0",
        "python-result-err rust.String zero",
        "9",
        "python-result-panic True True True",
        "python-prefix-is-not-native True",
    ]
