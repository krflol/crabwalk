"""Structured one-crossing ETL: native domain rows in, grouped mapping out.

Run from the repository root with::

    python examples/showcase/structured_etl.py

The example is intentionally deterministic. It demonstrates boundary shape and
ownership, not a throughput claim.
"""

from crabwalk import rust


# Related Rust Book material:
# https://doc.rust-lang.org/book/ch05-01-defining-structs.html
# https://doc.rust-lang.org/book/ch08-03-hash-maps.html#updating-a-value-based-on-the-old-value
# https://doc.rust-lang.org/book/ch13-02-iterators.html#methods-that-produce-other-iterators
@rust.struct
class Sale:
    customer_id: rust.u64
    status: rust.String
    region: rust.String
    amount: rust.f64


@rust.fn
def active_totals(
    rows: rust.Owned[rust.Vec[Sale]],
) -> rust.HashMap[rust.String, rust.f64]:
    """Filter borrowed domain rows and aggregate their amounts by region."""

    totals: rust.HashMap[rust.String, rust.f64] = rust.HashMap()
    active = rows.iter_ref().filter(
        lambda row: row.status.to_lowercase().starts_with("active")
    )
    for row in active:
        totals.add(row.region.to_lowercase(), row.amount)
    return totals


source_rows = rust.Vec[Sale](
    [
        {
            "customer_id": 7,
            "status": "ACTIVE",
            "region": "Midwest",
            "amount": 12.5,
        },
        {
            "customer_id": 8,
            "status": "inactive",
            "region": "Midwest",
            "amount": 9.0,
        },
        {
            "customer_id": 9,
            "status": "active",
            "region": "Midwest",
            "amount": 3.5,
        },
        {
            "customer_id": 10,
            "status": "active",
            "region": "West",
            "amount": 7.25,
        },
    ]
)

result = active_totals(source_rows)
assert result == {"midwest": 16.0, "west": 7.25}
assert source_rows.moved is True

print(sorted(result.items()))
print(f"structured rows moved={source_rows.moved}")
