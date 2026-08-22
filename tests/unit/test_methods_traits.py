from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path


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
    assert "trait Draw {" in generated.rust_source
    assert "impl Draw for Button {" in generated.rust_source
    assert "impl Draw for SelectBox {" in generated.rust_source
    assert "fn increment(&mut self, amount: u64) -> ()" in generated.rust_source
    assert "counter.value = (counter.value + amount);" in generated.rust_source
    assert "Box::new(Button {" in generated.rust_source
    assert "as Box<dyn Draw>" in generated.rust_source
    assert "for component in components.iter()" in generated.rust_source
    assert "total = (total + component.draw());" in generated.rust_source
