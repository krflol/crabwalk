from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path


ADVANCED_SOURCE = """\
from crabwalk import rust

Pilot = rust.trait("Pilot", fly=rust.u64)
Wizard = rust.trait("Wizard", fly=rust.u64)

@rust.struct
class Human:
    marker: rust.u64

@rust.impl(Pilot, Human, name="fly")
def pilot_fly(human: rust.Ref[Human]) -> rust.u64:
    return 1

@rust.impl(Wizard, Human, name="fly")
def wizard_fly(human: rust.Ref[Human]) -> rust.u64:
    return 2

@rust.method(Human, name="fly")
def human_fly(human: rust.Ref[Human]) -> rust.u64:
    return 3

@rust.struct
class Point:
    x: rust.i64
    y: rust.i64

@rust.operator(Point, name="add")
def add_points(left: rust.Owned[Point], right: Point) -> Point:
    return Point(x=left.x + right.x, y=left.y + right.y)

@rust.struct
class Millimeters:
    value: rust.u64

@rust.struct
class Meters:
    value: rust.u64

@rust.operator(Millimeters, name="add")
def add_lengths(
    left: rust.Owned[Millimeters], right: Meters
) -> Millimeters:
    return Millimeters(value=left.value + right.value * 1000)

@rust.fn
def add_one(value: rust.u64) -> rust.u64:
    return value + 1

@rust.fn
def trait_disambiguation_demo() -> rust.u64:
    person: Human = Human(marker=0)
    return (
        rust.trait_call(Pilot, person, "fly") * 100
        + rust.trait_call(Wizard, person, "fly") * 10
        + person.fly()
    )

@rust.fn
def operator_demo() -> rust.i64:
    left: Point = Point(x=1, y=2)
    right: Point = Point(x=3, y=4)
    combined: Point = left + right
    return combined.x * 10 + combined.y

@rust.fn
def default_generic_operator_demo() -> rust.u64:
    millimeters: Millimeters = Millimeters(value=500)
    meters: Meters = Meters(value=2)
    combined: Millimeters = millimeters + meters
    return combined.value

@rust.fn
def unsafe_demo() -> rust.u64:
    value: rust.u64 = 5
    before: rust.u64 = rust.unsafe_read(value)
    rust.unsafe_write(value, 9)
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3, 4])
    split_total: rust.u64 = values.split_at_mut_sum(2)
    aliased: rust.u64 = rust.type_alias_identity(value)
    static_value: rust.u64 = rust.unsafe_static_increment(2)
    return before + value + split_total + aliased + static_value

@rust.fn
def c_absolute(value: rust.i32) -> rust.i32:
    return rust.c_abs(value)

@rust.fn
def function_pointer_demo(value: rust.u64) -> rust.u64:
    return rust.call_twice(add_one, value)

@rust.fn
def returned_closure_demo(value: rust.u64) -> rust.u64:
    return rust.boxed_closure_call(value, 3)

@rust.fn
def heterogeneous_closure_demo(value: rust.u64) -> rust.u64:
    return rust.closure_vector_total(value)

@rust.fn
def associated_item_demo() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3])
    return values.iter().map(lambda value: value + 1).sum()

@rust.fn
def never_coercion_demo() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3])
    total: rust.u64 = 0
    for value in values.iter():
        match value:
            case 2:
                continue
            case _:
                total += value
    return total
"""


def test_advanced_features_lower_to_auditable_rust(tmp_path: Path) -> None:
    source = tmp_path / "advanced.py"
    source.write_text(ADVANCED_SOURCE, encoding="utf-8")

    generated = generate_project(analyze_path(source), "_crabwalk_advanced")
    rust_source = generated.rust_source

    assert "impl std::ops::Add<Point> for Point" in rust_source
    assert "impl std::ops::Add<Meters> for Millimeters" in rust_source
    assert "<Human as Pilot>::fly(&person)" in rust_source
    assert "<Human as Wizard>::fly(&person)" in rust_source
    assert "&raw const value" in rust_source
    assert "&raw mut value" in rust_source
    assert "std::slice::from_raw_parts_mut" in rust_source
    assert 'unsafe extern "C" { fn abs(input: i32) -> i32; }' in rust_source
    assert "static mut __CW_COUNTER: u64" in rust_source
    assert "type __CwAlias = u64" in rust_source
    assert "let __cw_operation: fn(u64) -> u64" in rust_source
    assert "Box<dyn Fn(u64) -> u64>" in rust_source
    assert "Vec<Box<dyn Fn(u64) -> u64>>" in rust_source
    assert "continue;" in rust_source
