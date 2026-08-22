from __future__ import annotations

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


async def main() -> None:
    print(await rust.async_call(parallel_sum, 1_000_000))
    print(rayon_workers())


if __name__ == "__main__":
    asyncio.run(main())
