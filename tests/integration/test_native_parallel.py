from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_rayon_and_explicit_python_async_boundary(tmp_path: Path) -> None:
    source = tmp_path / "parallel_app.py"
    source.write_text(
        """\
import asyncio

from crabwalk import rust

rayon = rust.crate("rayon", version="1")

@rust.fn
def parallel_sum(stop: rust.u64) -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([])
    for value in range(stop):
        values.push(value)
    return values.par_iter().copied().sum()

@rust.fn
def rayon_workers() -> rust.usize:
    return rayon.current_num_threads()

@rust.fn
def python_boundary(value: rust.u64) -> rust.u64:
    print(value)
    return value

async def main():
    ticks = 0
    running = True
    async def ticker():
        nonlocal ticks
        while running:
            ticks += 1
            await asyncio.sleep(0.001)

    ticker_task = asyncio.create_task(ticker())
    result = await rust.async_call(parallel_sum, 1_000_000)
    running = False
    await ticker_task
    print(result)
    print(rayon_workers())
    print(ticks > 0)
    print(parallel_sum.__crabwalk__["async_eligible"])
    print(python_boundary.__crabwalk__["async_eligible"])
    try:
        await rust.async_call(python_boundary, 7)
    except TypeError as error:
        print("Python runtime boundaries" in str(error))

asyncio.run(main())
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["RAYON_NUM_THREADS"] = "4"

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
        "499999500000",
        "4",
        "True",
        "True",
        "False",
        "True",
    ]
