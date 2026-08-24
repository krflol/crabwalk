"""Typed non-Copy Rayon ETL: filter and normalize owned String rows."""

from __future__ import annotations

from time import perf_counter

from crabwalk import rust


rayon = rust.crate("rayon", version="1.12.0")


@rust.fn
def normalize_active(
    rows: rust.Owned[rust.Vec[rust.String]],
) -> rust.Vec[rust.String]:
    return (
        rows.par_iter()
        .filter(lambda row: row.contains("|active|"))
        .map(lambda row: row.to_lowercase())
        .collect_vec()
    )


source_rows = rust.Vec[rust.String](
    [
        "1|ALICE|active|CHICAGO",
        "2|BOB|inactive|MADISON",
        "3|CAROL|active|MILWAUKEE",
    ]
)
started = perf_counter()
normalized = normalize_active(source_rows)
elapsed_ms = (perf_counter() - started) * 1_000

assert normalized == [
    "1|alice|active|chicago",
    "3|carol|active|milwaukee",
]
assert source_rows.moved
print(normalized)
print(f"Rayon String ETL {elapsed_ms:.2f}ms | input moved={source_rows.moved}")
