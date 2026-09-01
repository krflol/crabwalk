from __future__ import annotations

import re
from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import PatternMatchIR


COLLECTION_ALGEBRA_SOURCE = """\
from crabwalk import rust

@rust.fn
def checked(value: rust.u64) -> rust.Result[rust.u64, rust.String]:
    if value == 0:
        return rust.Err("zero")
    return rust.Ok(value)

@rust.fn
def classify(value: rust.u64) -> rust.u64:
    result: rust.Result[rust.u64, rust.String] = checked(value)
    match result:
        case rust.Ok(number):
            return number
        case rust.Err(message):
            return 0

@rust.fn
def increment_checked(value: rust.u64) -> rust.u64:
    return checked(value).map(lambda number: number + 1).unwrap_or(0)

@rust.fn
def clone_string(value: rust.String) -> rust.String:
    return value.clone()

@rust.fn
def mutate_option_payload() -> rust.usize:
    values: rust.Option[rust.Vec[rust.i64]] = rust.Some(rust.Vec([1]))
    values.as_mut().unwrap().push(2)
    return values.as_ref().unwrap().len()

@rust.fn
def error_length(error: rust.String) -> rust.i64:
    return rust.checked_cast(error.len(), rust.i64).expect("error length overflow")

@rust.fn
def map_checked_cast_error(
    value: rust.i64,
) -> rust.Result[rust.u64, rust.i64]:
    converted: rust.Result[rust.u64, rust.String] = rust.checked_cast(value, rust.u64)
    return converted.map_err(error_length)

@rust.fn
def word_counts() -> rust.HashMap[rust.String, rust.u64]:
    counts: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    counts.add("rust", 2)
    counts.add("python", 1)
    return counts

@rust.fn
def amount_totals() -> rust.HashMap[rust.String, rust.f64]:
    totals: rust.HashMap[rust.String, rust.f64] = rust.HashMap()
    totals.add("active", 12.5)
    return totals

@rust.fn
def count_keys() -> rust.Vec[rust.String]:
    counts: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    counts.add("Rust", 2)
    counts.add("Python", 1)
    return counts.keys().cloned().map(lambda key: key.to_lowercase()).collect_vec()

@rust.fn
def rebuilt_counts() -> rust.HashMap[rust.String, rust.u64]:
    counts: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    counts.add("rust", 2)
    counts.add("python", 1)
    return counts.into_iter().collect_map()

@rust.fn
def normalize_fields(row: rust.Str) -> rust.Vec[rust.String]:
    return (
        row.trim()
        .split("|")
        .filter(lambda field: not field.is_empty())
        .map(lambda field: field.to_lowercase())
        .collect_vec()
    )

@rust.fn
def parse_amount(text: rust.Str) -> rust.Result[rust.f64, rust.String]:
    cleaned: rust.Str = text.trim()
    parsed: rust.Result[rust.f64, rust.String] = cleaned.parse()
    return parsed

@rust.fn
def join_fields() -> rust.String:
    fields: rust.Vec[rust.String] = rust.Vec(["alpha", "beta"])
    return ",".join(fields)

@rust.fn
def tuple_keyed() -> rust.HashMap[
    rust.Tuple[rust.String, rust.Option[rust.Vec[rust.u8]]],
    rust.u64,
]:
    result: rust.HashMap[
        rust.Tuple[rust.String, rust.Option[rust.Vec[rust.u8]]],
        rust.u64,
    ] = rust.HashMap()
    result.insert(("key", rust.Some(rust.Vec([1, 2]))), 3)
    return result

@rust.fn
def map_loop_total() -> rust.usize:
    values: rust.HashMap[rust.String, rust.usize] = rust.HashMap()
    values.insert("active", 2)
    total: rust.usize = 0
    for key in values.keys():
        total += key.len()
    for value in values.values().copied():
        total += value
    return total

@rust.fn
def split_map_keys() -> rust.Vec[rust.String]:
    values: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    values.insert("active", 2)
    values.insert("inactive", 1)
    borrowed = values.keys()
    owned = borrowed.cloned()
    return owned.collect_vec()

@rust.fn
def borrowed_string_key_lookup() -> rust.Tuple[rust.bool, rust.bool, rust.u64]:
    keys: rust.Vec[rust.String] = rust.Vec(["active", "missing"])
    values: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    values.insert("active", 7)
    return (
        values.contains_key(keys[0].as_str()),
        values.contains_key("active"),
        values.get_or(keys[1].as_str(), 11),
    )

@rust.fn
def consume_owned_strings(
    values: rust.Owned[rust.Vec[rust.String]],
) -> rust.Vec[rust.String]:
    return values.into_iter().map(
        lambda value: value.to_lowercase()
    ).collect_vec()

@rust.fn
def reserve_values() -> rust.usize:
    values: rust.Vec[rust.u64] = rust.Vec([])
    values.reserve(4)
    values.push(1)
    return values.len()
"""


def test_collection_and_error_algebra_lower_as_typed_compositions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "collection_algebra.py"
    source.write_text(COLLECTION_ALGEBRA_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_collection_algebra")

    assert isinstance(ir.functions[1].body[1], PatternMatchIR)
    assert "std::result::Result::Ok(number)" in generated.rust_source
    assert "std::result::Result::Err(message)" in generated.rust_source
    assert ".keys().cloned().map(" in generated.rust_source
    assert ".collect::<std::collections::HashMap<_, _>>()" in generated.rust_source
    assert '.trim().split("|").filter(' in generated.rust_source
    assert re.search(
        r"\.parse::<f64>\(\)\.map_err\("
        r"\|(?P<error>__cw_tmp_\d+_[0-9a-f]+)\| (?P=error)\.to_string\(\)\)",
        generated.rust_source,
    )
    assert '.join(String::from(",").as_str())' in generated.rust_source
    assert ".or_insert(0u64) += 2u64" in generated.rust_source
    assert ".or_insert(0.0f64) += 12.5f64" in generated.rust_source
    assert ".contains_key(keys[0usize].as_str())" in generated.rust_source
    assert '.contains_key(&String::from("active"))' in generated.rust_source
    assert (
        ".get(keys[1usize].as_str()).cloned().unwrap_or(11u64)" in generated.rust_source
    )
    assert ".into_iter().map(" in generated.rust_source
    assert ".reserve(4usize)" in generated.rust_source
    assert "return value.clone();" in generated.rust_source
    assert "values.as_mut().unwrap().push(2i64)" in generated.rust_source
    assert re.search(
        r"converted\.map_err\(\|(?P<item>cw_b_[^|]+)\| "
        r"__cw_native_[^(]+\((?P=item)\)\)",
        generated.rust_source,
    )
