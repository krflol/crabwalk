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
