from __future__ import annotations

from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from crabwalk.compiler.frontend import analyze_path


RICH_TRAIT_SOURCE = """from crabwalk import rust

T = rust.typevar("T")

Adjust = rust.trait(
    "Adjust",
    bump=rust.trait_method(rust.u64, rust.u64, receiver="mut"),
    finish=rust.trait_method(rust.u64, receiver="owned"),
)

Echo = rust.trait(
    "Echo",
    echo=rust.trait_method(
        T,
        T,
        type_parameters=[T],
        bounds={T: [rust.Copy]},
    ),
)

Factory = rust.trait(
    "Factory",
    produce=rust.trait_method(rust.associated_type("Output")),
)

@rust.struct
class Counter:
    value: rust.u64

@rust.impl(Adjust, Counter, name="bump")
def bump_counter(counter: rust.Mut[Counter], amount: rust.u64) -> rust.u64:
    counter.value = counter.value + amount
    return counter.value

@rust.impl(Adjust, Counter, name="finish")
def finish_counter(counter: rust.Owned[Counter]) -> rust.u64:
    return counter.value

@rust.impl(Echo, Counter, name="echo", type_parameters=[T], bounds={T: [rust.Copy]})
def echo_counter(counter: rust.Ref[Counter], value: T) -> T:
    return value

@rust.impl(Factory, Counter, name="produce")
def produce_counter(counter: rust.Ref[Counter]) -> rust.u64:
    return counter.value

@rust.operator(Counter, name="subtract")
def subtract_counter(counter: rust.Owned[Counter], amount: rust.u64) -> Counter:
    return Counter(counter.value - amount)

@rust.fn
def richer_trait_demo() -> rust.u64:
    counter: Counter = Counter(10)
    bumped: rust.u64 = rust.trait_call(Adjust, counter, "bump", 7)
    smaller: Counter = counter - 2
    echoed: rust.u64 = rust.trait_call(Echo, smaller, "echo", 20)
    produced: rust.u64 = rust.trait_call(Factory, smaller, "produce")
    return (
        bumped * 100
        + rust.trait_call(Adjust, smaller, "finish")
        + echoed
        + produced
    )
"""


@capability_contract("traits.arguments-receivers-associated", native=False)
def test_trait_arguments_receiver_modes_and_non_add_operator_lower(
    tmp_path: Path,
) -> None:
    source = tmp_path / "richer_traits.py"
    source.write_text(RICH_TRAIT_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    trait = next(value for value in ir.traits if value.name == "Adjust")
    bump, finish = trait.methods

    assert bump.receiver_ownership == "Mut"
    assert tuple(value.rust_name for value in bump.parameter_types) == ("u64",)
    assert finish.receiver_ownership == "Owned"
    echo = next(value for value in ir.traits if value.name == "Echo").methods[0]
    assert echo.type_parameters[0].bounds == ("Copy",)
    associated = next(value for value in ir.traits if value.name == "Factory").methods[
        0
    ]
    assert associated.return_type.rust_name == "Associated"
    assert (
        next(
            function for function in ir.functions if function.name == "subtract_counter"
        ).operator_kind
        == "subtract"
    )
