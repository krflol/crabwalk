from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import CrabwalkCompilationError


METHOD_TRAIT_SOURCE = """\
from crabwalk import rust

Draw = rust.trait("Draw", draw=rust.u64)

@rust.struct
class Button:
    width: rust.u64
    height: rust.u64

@rust.struct
class SelectBox:
    width: rust.u64
    option_count: rust.u64

@rust.impl(Draw, Button, name="draw")
def draw_button(button: rust.Ref[Button]) -> rust.u64:
    return button.width * button.height

@rust.impl(Draw, SelectBox, name="draw")
def draw_select_box(select_box: rust.Ref[SelectBox]) -> rust.u64:
    return select_box.width + select_box.option_count

@rust.struct
class Counter:
    value: rust.u64

@rust.method(Counter, name="increment")
def increment_counter(counter: rust.Mut[Counter], amount: rust.u64) -> None:
    counter.value = counter.value + amount

@rust.method(Counter, name="read")
def read_counter(counter: rust.Ref[Counter]) -> rust.u64:
    return counter.value

@rust.fn
def method_and_trait_demo() -> rust.u64:
    counter: Counter = Counter(value=1)
    counter.increment(4)
    components: rust.Vec[rust.Box[rust.Dyn[Draw]]] = rust.Vec([
        rust.dyn_box(Draw, Button(width=2, height=3)),
        rust.dyn_box(Draw, SelectBox(width=10, option_count=10)),
    ])
    total: rust.u64 = counter.read()
    for component in components.iter_ref():
        total += component.draw()
    return total
"""


def test_inherent_methods_and_trait_objects_lower_to_rust(tmp_path: Path) -> None:
    source = tmp_path / "methods_traits.py"
    source.write_text(METHOD_TRAIT_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_methods_traits")

    assert len(ir.traits) == 1
    assert ir.traits[0].methods[0].name == "draw"
    trait_symbol = ir.traits[0].symbol
    button_symbol = next(value.symbol for value in ir.structs if value.name == "Button")
    select_symbol = next(
        value.symbol for value in ir.structs if value.name == "SelectBox"
    )
    assert f"trait {trait_symbol} {{" in generated.rust_source
    assert f"impl {trait_symbol} for {button_symbol} {{" in generated.rust_source
    assert f"impl {trait_symbol} for {select_symbol} {{" in generated.rust_source
    assert "fn increment(&mut self, amount: u64) -> ()" in generated.rust_source
    assert "counter.value = (counter.value + amount);" in generated.rust_source
    assert f"Box::new({button_symbol} {{" in generated.rust_source
    assert f"as Box<dyn {trait_symbol}>" in generated.rust_source
    assert "for component in components.iter()" in generated.rust_source
    assert "total = (total + component.draw());" in generated.rust_source


@pytest.mark.parametrize(
    ("trait_methods", "implementation", "message"),
    [
        (
            "draw=rust.u64, label=rust.String",
            """\
@rust.impl(Draw, Button, name="draw")
def draw(button: rust.Ref[Button]) -> rust.u64:
    return button.width
""",
            "Incomplete trait implementation",
        ),
        (
            "draw=rust.u64",
            """\
@rust.impl(Draw, Button, name="label")
def label(button: rust.Ref[Button]) -> rust.u64:
    return button.width
""",
            "Unknown trait implementation method",
        ),
        (
            "draw=rust.String",
            """\
@rust.impl(Draw, Button, name="draw")
def draw(button: rust.Ref[Button]) -> rust.u64:
    return button.width
""",
            "Trait implementation return type mismatch",
        ),
        (
            "draw=rust.u64",
            """\
@rust.impl(Draw, Button, name="draw")
def first_draw(button: rust.Ref[Button]) -> rust.u64:
    return button.width

@rust.impl(Draw, Button, name="draw")
def second_draw(button: rust.Ref[Button]) -> rust.u64:
    return button.width
""",
            "Duplicate trait implementation method",
        ),
    ],
)
def test_trait_contract_is_validated_before_codegen(
    tmp_path: Path,
    trait_methods: str,
    implementation: str,
    message: str,
) -> None:
    source = tmp_path / "invalid_trait.py"
    source.write_text(
        f"""\
from crabwalk import rust

Draw = rust.trait("Draw", {trait_methods})

@rust.struct
class Button:
    width: rust.u64

{implementation}
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        generate_project(analyze_path(source), "_crabwalk_invalid_trait")

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB211"
    assert diagnostic.title == message
    assert diagnostic.span is not None


@pytest.mark.parametrize(
    "body",
    [
        "values.push(1)",
        "values.pop()",
    ],
)
def test_shared_vec_receiver_cannot_call_mutating_method(
    tmp_path: Path,
    body: str,
) -> None:
    source = tmp_path / "shared_vec.py"
    source.write_text(
        f"""\
from crabwalk import rust

@rust.fn
def invalid(values: rust.Ref[rust.Vec[rust.u64]]) -> None:
    {body}
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB208"
    assert diagnostic.span is not None


def test_shared_domain_receiver_cannot_call_mutable_inherent_method(
    tmp_path: Path,
) -> None:
    source = tmp_path / "shared_domain.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Counter:
    value: rust.u64

@rust.method(Counter, name="increment")
def increment(counter: rust.Mut[Counter]) -> None:
    counter.value = counter.value + 1

@rust.fn
def invalid(counter: rust.Ref[Counter]) -> None:
    counter.increment()
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    assert captured.value.diagnostics[0].code == "CRAB208"


def test_nested_owned_field_mutation_marks_the_root_binding_mutable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "nested_place.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Bucket:
    items: rust.Vec[rust.u64]

@rust.fn
def append(values: rust.Mut[rust.Vec[rust.u64]], value: rust.u64) -> None:
    values.push(value)

@rust.fn
def append_local() -> rust.usize:
    bucket: Bucket = Bucket(items=rust.Vec([1]))
    bucket.items.push(2)
    append(bucket.items, 3)
    return bucket.items.len()
""",
        encoding="utf-8",
    )

    generated = generate_project(analyze_path(source), "_crabwalk_nested_place")

    assert "let mut bucket: " in generated.rust_source
    assert "bucket.items.push(2u64)" in generated.rust_source
    assert "(&mut bucket.items, 3u64)" in generated.rust_source


def test_shared_root_rejects_nested_field_mutation_but_allows_interior_mutability(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "nested_shared.py"
    invalid.write_text(
        """\
from crabwalk import rust

@rust.struct
class Bucket:
    items: rust.Vec[rust.u64]

@rust.fn
def invalid(bucket: rust.Ref[Bucket]) -> None:
    bucket.items.push(1)
""",
        encoding="utf-8",
    )
    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(invalid)
    assert captured.value.diagnostics[0].code == "CRAB208"

    valid = tmp_path / "interior.py"
    valid.write_text(
        """\
from crabwalk import rust

@rust.async_fn
async def replace(cell: rust.Ref[rust.RefCell[rust.u64]], value: rust.u64) -> rust.u64:
    return cell.replace(value)
""",
        encoding="utf-8",
    )
    generated = generate_project(analyze_path(valid), "_crabwalk_interior")
    assert "cell.replace(value)" in generated.rust_source
