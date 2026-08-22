"""Compare one warm Rust/Rayon kernel with an explicit Python loop."""

from time import perf_counter

from crabwalk import rust

# Crabwalk turns this declaration into a generated Cargo dependency.
rayon = rust.crate("rayon", version="1.12.0")


@rust.fn
def parallel_sum(n: rust.u64) -> rust.Tuple[rust.u64, rust.usize]:
    # These are concrete Vec<u64> values in the generated Rust function.
    values: rust.Vec[rust.u64] = rust.Vec([])
    for value in range(n):
        values.push(value)

    # par_iter() is a real Rayon parallel reduction, not a Python iterator.
    return values.par_iter().copied().sum(), rayon.current_num_threads()


if __name__ == "__main__":
    item_count = 5_000_000

    started = perf_counter()
    native_total, workers = parallel_sum(item_count)
    native_seconds = perf_counter() - started

    started = perf_counter()
    python_total = 0
    for item in range(item_count):
        python_total += item
    python_seconds = perf_counter() - started

    expected = item_count * (item_count - 1) // 2
    assert native_total == python_total == expected
    print(
        f"Rust/Rayon {native_seconds:.3f}s ({workers} threads) | "
        f"Python {python_seconds:.3f}s | "
        f"{python_seconds / native_seconds:.1f}x"
    )
