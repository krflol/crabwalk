"""Run a GIL-detached Rust/Rayon kernel from an async FastAPI route."""

import asyncio
from time import perf_counter

from fastapi import FastAPI, Query

from crabwalk import rust

rayon = rust.crate("rayon", version="1.12.0")
app = FastAPI(title="Crabwalk + FastAPI")


@rust.fn
def parallel_sum(n: rust.u64) -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([])
    for value in range(n):
        values.push(value)
    return values.par_iter().copied().sum()


@app.get("/benchmark")
async def benchmark(n: int = Query(5_000_000, ge=0, le=20_000_000)):
    # async_call schedules eligible native work away from the event-loop thread.
    started = perf_counter()
    native_total = await rust.async_call(parallel_sum, n)
    native_ms = (perf_counter() - started) * 1_000

    # The reference loop also runs off the event loop so the comparison does not
    # intentionally make the FastAPI application unresponsive.
    started = perf_counter()
    python_total = await asyncio.to_thread(lambda: sum(range(n)))
    python_ms = (perf_counter() - started) * 1_000

    assert native_total == python_total
    return {
        "sum": native_total,
        "rust_ms": round(native_ms, 2),
        "python_ms": round(python_ms, 2),
        "speedup": round(python_ms / native_ms, 1),
        "gil_released": parallel_sum.__crabwalk__["gil_released"],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
