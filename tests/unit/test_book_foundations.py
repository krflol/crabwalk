from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import LetIR


BOOK_FOUNDATIONS = """\
from crabwalk import rust

@rust.fn
def binding_rules() -> rust.u32:
    THREE_HOURS_IN_SECONDS: rust.u32 = rust.const(60 * 60 * 3)
    value: rust.u32 = 5
    value: rust.u32 = rust.shadow(value + 1)
    return THREE_HOURS_IN_SECONDS + value

@rust.fn
def tuple_and_array() -> rust.u64:
    inventory: rust.Tuple[rust.u64, rust.u64, rust.u64] = (500, 6, 1)
    price, quantity, category = inventory
    values: rust.Array[rust.u64, 5] = [1, 2, 3, 4, 5]
    repeated: rust.Array[rust.u64, 5] = rust.repeat(3, 5)
    return price + quantity + category + values[4] + repeated[2]

@rust.fn
def echo_character(value: rust.char) -> rust.char:
    marker: rust.char = '🦀'
    if value == marker:
        return marker
    return value

@rust.fn
def map_total() -> rust.u64:
    scores: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    scores.insert("Blue", 10)
    scores.add("Blue", 5)
    return scores.get_or("Blue", 0)
"""


def test_book_foundation_types_and_bindings_lower_to_real_rust(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book_foundations.py"
    source.write_text(BOOK_FOUNDATIONS, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_book_foundations")

    assert ir.schema_version == 21
    first_value = ir.functions[0].body[1]
    shadowed_value = ir.functions[0].body[2]
    assert isinstance(first_value, LetIR)
    assert isinstance(shadowed_value, LetIR)
    assert first_value.rust_name != shadowed_value.rust_name
    assert "const THREE_HOURS_IN_SECONDS: u32" in generated.rust_source
    assert f"let {first_value.rust_name}: u32 = 5u32;" in generated.rust_source
    assert (
        f"let {shadowed_value.rust_name}: u32 = "
        f"({first_value.rust_name} + 1u32);" in generated.rust_source
    )
    assert "(u64, u64, u64)" in generated.rust_source
    assert "let (price, quantity, category)" in generated.rust_source
    assert "[u64; 5]" in generated.rust_source
    assert "[3u64; 5]" in generated.rust_source
    assert "values[4usize]" in generated.rust_source
    assert "std::collections::HashMap<String, u64>" in generated.rust_source
    assert "std::collections::HashMap::new()" in generated.rust_source
    assert '.entry(String::from("Blue")).or_insert(0u64)' in generated.rust_source
    assert "'🦀'" in generated.rust_source
