from __future__ import annotations

from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path


STRUCTURED_BOUNDARY_SOURCE = """\
from crabwalk import rust

@rust.struct
class Row:
    customer_id: rust.u64
    status: rust.String
    amount: rust.f64

@rust.struct
class Address:
    city: rust.String

@rust.struct
class Customer:
    customer_id: rust.u64
    address: Address

@rust.enum
class Delivery:
    Home = rust.variant(address=Address)
    Pickup = rust.variant(location=rust.String)

@rust.enum
class Payload:
    AddressValue = rust.variant(Address)
    Label = rust.variant(rust.String)

@rust.fn
def active_customer_ids(
    rows: rust.Owned[rust.Vec[Row]],
) -> rust.Vec[rust.u64]:
    return (
        rows.iter_ref()
        .filter(lambda row: row.status.contains("active"))
        .map(lambda row: row.customer_id)
        .collect_vec()
    )

@rust.fn
def pair_total(
    values: rust.Ref[rust.Vec[rust.Tuple[rust.u64, rust.u64]]],
) -> rust.u64:
    return values.iter().map(lambda pair: pair[0] + pair[1]).sum()

@rust.fn
def present_count(
    values: rust.Ref[rust.Vec[rust.Option[rust.u64]]],
) -> rust.usize:
    return values.iter_ref().filter(lambda value: value.is_some()).count()

@rust.fn
def nested_first_len(
    values: rust.Ref[rust.Vec[rust.Vec[rust.u8]]],
) -> rust.usize:
    return values[0].len()

@rust.fn
def make_row(
    customer_id: rust.u64,
    status: rust.String,
    amount: rust.f64,
) -> rust.Owned[Row]:
    return Row(customer_id=customer_id, status=status, amount=amount)

@rust.fn
def make_labels() -> rust.Owned[rust.Vec[rust.String]]:
    labels: rust.Vec[rust.String] = rust.Vec(["alpha", "beta"])
    return labels

@rust.fn
def make_customer(customer_id: rust.u64, city: rust.String) -> rust.Owned[Customer]:
    address: Address = Address(city=city)
    return Customer(customer_id=customer_id, address=address)

@rust.fn
def make_delivery(city: rust.String) -> rust.Owned[Delivery]:
    address: Address = Address(city=city)
    return Delivery.Home(address=address)
"""


def test_recursive_owned_vectors_and_owned_returns_have_generated_codecs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "structured_boundaries.py"
    source.write_text(STRUCTURED_BOUNDARY_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_structured_boundaries")
    row = next(value for value in ir.structs if value.name == "Row")
    delivery = next(value for value in ir.enums if value.name == "Delivery")

    assert ir.functions[0].parameters[0].type_ref.underlying.render() == (
        f"Vec<{row.symbol}>"
    )
    assert row.symbol_id is not None
    assert all(field.binding is not None for field in row.fields)
    assert delivery.symbol_id is not None
    assert all(variant.binding is not None for variant in delivery.variants)
    assert all(
        field.binding is not None
        for variant in delivery.variants
        for field in variant.fields
    )
    assert "Vec<(u64, u64)>" in generated.rust_source
    assert "Vec<Option<u64>>" in generated.rust_source
    assert "Vec<Vec<u8>>" in generated.rust_source
    assert "Vec<PyRef<'_," in generated.rust_source
    assert "__cw_values.push(__cw_value.clone())" in generated.rust_source
    assert "value: std::option::Option::Some(__cw_result)" in generated.rust_source
    assert "PyRef<'_, __CwOwned_" in generated.rust_source
    assert "fn address(&self, py: Python<'_>)" in generated.rust_source
    assert "fn Home(address: PyRef<'_," in generated.rust_source
    assert ".into_any()" in generated.rust_source
