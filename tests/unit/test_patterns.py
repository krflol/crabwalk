from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import ForEachIR, PatternMatchIR


PATTERN_SOURCE = """\
from crabwalk import rust

@rust.struct
class Point:
    x: rust.u64
    y: rust.u64

@rust.enum
class Shape:
    Origin = rust.variant()
    At = rust.variant(Point)

@rust.fn
def literal_or_range(value: rust.u64) -> rust.u64:
    match value:
        case 1 | 2:
            return 10
        case rust.Range(3, 7) as matched:
            return matched
        case _:
            return 0

@rust.fn
def guarded_option(value: rust.Option[rust.u64], threshold: rust.u64) -> rust.u64:
    match value:
        case rust.Some(number) if number > threshold:
            return number
        case rust.Some(_):
            return threshold
        case None:
            return 0

@rust.fn
def point_total(x: rust.u64, y: rust.u64) -> rust.u64:
    point: Point = Point(x=x, y=y)
    match point:
        case Point(x=0, y=y_value):
            return y_value
        case Point(x=x_value, y=0):
            return x_value
        case Point(x=x_value, y=y_value) if x_value == y_value:
            return x_value * 2
        case Point(x=x_value, y=y_value):
            return x_value + y_value

@rust.fn
def nested_shape_total(x: rust.u64, y: rust.u64) -> rust.u64:
    shape: Shape = Shape.At(Point(x=x, y=y))
    match shape:
        case Shape.Origin:
            return 0
        case Shape.At(Point(x=0, y=y_value)):
            return y_value
        case Shape.At(Point(x=x_value, y=y_value)):
            return x_value + y_value

@rust.fn
def tuple_rest(first: rust.u64, last: rust.u64) -> rust.u64:
    values: rust.Tuple[rust.u64, rust.u64, rust.u64, rust.u64] = (
        first,
        20,
        30,
        last,
    )
    match values:
        case (head, *_, tail):
            return head + tail

@rust.fn
def tuple_loop_total() -> rust.u64:
    pairs: rust.Vec[rust.Tuple[rust.u64, rust.u64]] = rust.Vec(
        [(1, 2), (3, 4)]
    )
    total: rust.u64 = 0
    for index, value in pairs.iter():
        total += index + value
    return total
"""


def test_general_rust_patterns_and_tuple_loop_targets_lower(tmp_path: Path) -> None:
    source = tmp_path / "patterns.py"
    source.write_text(PATTERN_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_patterns")

    assert isinstance(ir.functions[0].body[0], PatternMatchIR)
    assert isinstance(ir.functions[-1].body[2], ForEachIR)
    assert "1 | 2 =>" in generated.rust_source
    assert "matched @ (3..=7) =>" in generated.rust_source
    assert "Some(number) if (number > threshold) =>" in generated.rust_source
    point = next(value.symbol for value in ir.structs if value.name == "Point")
    shape = next(value.symbol for value in ir.enums if value.name == "Shape")
    assert f"{point} {{ x: 0, y: y_value }} =>" in generated.rust_source
    assert f"{shape}::At({point} {{ x: 0, y: y_value }}) =>" in generated.rust_source
    assert "(head, .., tail) =>" in generated.rust_source
    assert "for (index, value) in pairs.iter().copied()" in generated.rust_source
