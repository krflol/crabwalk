"""Record cold build, cached import, call, conversion, and native-work timings."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

FIXTURE = """\
import json
import time

from crabwalk import rust

started = time.perf_counter()

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value

@rust.fn
def sum_to(stop: rust.u64) -> rust.u64:
    total: rust.u64 = 0
    for value in range(stop):
        total += value
    return total

@rust.fn
def vector_len(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()

decorated = time.perf_counter()
iterations = 20_000
call_started = time.perf_counter()
for value in range(iterations):
    identity(value)
call_finished = time.perf_counter()

work_size = 2_000_000
native_started = time.perf_counter()
native_result = sum_to(work_size)
native_finished = time.perf_counter()
python_started = time.perf_counter()
python_result = sum(range(work_size))
python_finished = time.perf_counter()

vector_started = time.perf_counter()
values = rust.from_python(list(range(100_000)), rust.Vec[rust.u64])
vector_finished = time.perf_counter()
roundtrip_started = time.perf_counter()
roundtrip = rust.to_python(values)
roundtrip_finished = time.perf_counter()

assert native_result == python_result
assert roundtrip[-1] == 99_999
print(json.dumps({
    "decorator_seconds": decorated - started,
    "call_nanoseconds": (call_finished - call_started) * 1e9 / iterations,
    "native_work_seconds": native_finished - native_started,
    "python_work_seconds": python_finished - python_started,
    "vec_from_python_seconds": vector_finished - vector_started,
    "vec_to_python_seconds": roundtrip_finished - roundtrip_started,
    "cache_hit": identity.__crabwalk__["cache_hit"],
}))
"""


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository / "src")
    with tempfile.TemporaryDirectory(prefix="crabwalk-benchmark-") as value:
        root = Path(value)
        source = root / "benchmark_fixture.py"
        source.write_text(FIXTURE, encoding="utf-8")
        cold = _run(source, root, environment)
        cached = _run(source, root, environment)
    report = {
        "schema_version": 1,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "cold_process_seconds": cold[0],
        "cached_process_seconds": cached[0],
        "cold": cold[1],
        "cached": cached[1],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _run(
    source: Path,
    cwd: Path,
    environment: dict[str, str],
) -> tuple[float, dict[str, object]]:
    started = time.perf_counter()
    process = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if process.returncode != 0:
        raise RuntimeError(process.stderr or process.stdout)
    payload = json.loads(process.stdout.splitlines()[-1])
    if not isinstance(payload, dict):
        raise TypeError("benchmark fixture did not return a JSON object")
    return elapsed, payload


if __name__ == "__main__":
    raise SystemExit(main())
