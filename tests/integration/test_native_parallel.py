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

@rust.struct
class Row:
    customer_id: rust.u64
    status: rust.String

@rust.fn
def parallel_sum(stop: rust.u64) -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([])
    for value in range(stop):
        values.push(value)
    return values.par_iter().copied().sum()

@rust.fn
def normalize_active(
    rows: rust.Ref[rust.Vec[rust.String]],
) -> rust.Vec[rust.String]:
    return rows.par_iter().filter(
        lambda row: row.contains("|active|")
    ).map(
        lambda row: row.to_lowercase()
    ).collect_vec()

@rust.fn
def parallel_reduce_total(
    values: rust.Ref[rust.Vec[rust.u64]],
) -> rust.Option[rust.u64]:
    return values.par_iter().copied().reduce(lambda left, right: left + right)

@rust.fn
def parallel_active_customer_ids(
    rows: rust.Ref[rust.Vec[Row]],
) -> rust.Vec[rust.u64]:
    return rows.par_iter().filter(
        lambda row: row.status.starts_with("active")
    ).map(
        lambda row: row.customer_id
    ).collect_vec()

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
    rows = rust.Vec[rust.String]([
        "1|ALICE|active|",
        "2|BOB|INACTIVE|",
        "3|CAROL|active|",
    ])
    print(normalize_active(rows))
    print(rows.to_python())
    numbers = rust.Vec[rust.u64]([1, 2, 3, 4])
    print(parallel_reduce_total(numbers))
    domain_rows = rust.Vec[Row]([
        {"customer_id": 7, "status": "active"},
        {"customer_id": 8, "status": "inactive"},
        {"customer_id": 9, "status": "active"},
    ])
    print(parallel_active_customer_ids(domain_rows))

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
        "['1|alice|active|', '3|carol|active|']",
        "['1|ALICE|active|', '2|BOB|INACTIVE|', '3|CAROL|active|']",
        "10",
        "[7, 9]",
    ]
