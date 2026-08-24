from __future__ import annotations

import re
from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.capabilities import capability_contract
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import (
    ForEachIR,
    LetIR,
    PatternCaptureIR,
    PatternConstructorIR,
    PatternLiteralIR,
    PatternMatchIR,
    PatternTupleIR,
)
from crabwalk.compiler.types import (
    IteratorIndexing,
    IteratorItemMode,
    IteratorType,
)
from crabwalk.diagnostics import CrabwalkCompilationError


def test_anonymous_iterator_and_future_locals_use_rust_inference(
    tmp_path: Path,
) -> None:
    source = tmp_path / "anonymous_locals.py"
    source.write_text(
        """\
from crabwalk import rust

rayon = rust.crate("rayon", version="1")

@rust.fn
def normalize(rows: rust.Ref[rust.Vec[rust.String]]) -> rust.Vec[rust.String]:
    active = rows.par_iter().filter(lambda row: row.contains("|active|"))
    normalized = active.map(lambda row: row.to_lowercase())
    return normalized.collect_vec()

@rust.async_fn
async def async_double(value: rust.u64) -> rust.u64:
    return value * 2

@rust.async_fn
async def pipeline(value: rust.u64) -> rust.u64:
    pending = async_double(value)
    return await pending
""",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_anonymous_locals")
    normalize = next(value for value in ir.functions if value.name == "normalize")
    pipeline = next(value for value in ir.functions if value.name == "pipeline")

    assert isinstance(normalize.body[0], LetIR)
    assert normalize.body[0].rust_annotation is None
    assert isinstance(normalize.body[1], LetIR)
    assert normalize.body[1].rust_annotation is None
    assert isinstance(pipeline.body[0], LetIR)
    assert pipeline.body[0].rust_annotation is None
    assert "ParallelIterator<Item" not in generated.rust_source
    assert "Future<u64>" not in generated.rust_source
    assert "let active = rows.par_iter().filter(" in generated.rust_source
    assert "let normalized = active.map(" in generated.rust_source


@capability_contract("iterator.borrowed-for-loop")
def test_for_loop_retains_shared_item_semantics(tmp_path: Path) -> None:
    source = tmp_path / "borrowed_for.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def normalize(rows: rust.Ref[rust.Vec[rust.String]]) -> rust.Vec[rust.String]:
    output: rust.Vec[rust.String] = rust.Vec([])
    for row in rows.iter_ref():
        output.push(row.to_lowercase())
    return output

@rust.fn
def key_size() -> rust.usize:
    values: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    values.insert("active", 1)
    total: rust.usize = 0
    for key in values.keys():
        total += key.len()
    return total
""",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_borrowed_for")
    string_loop = ir.functions[0].body[1]
    key_loop = ir.functions[1].body[3]

    assert isinstance(string_loop, ForEachIR)
    assert string_loop.item_mode == IteratorItemMode.SHARED_REF
    assert string_loop.item_type.ownership == "Ref"
    assert isinstance(key_loop, ForEachIR)
    assert key_loop.item_mode == IteratorItemMode.SHARED_REF
    assert key_loop.item_type.ownership == "Ref"
    assert ".iter()" in generated.rust_source
    assert ".keys()" in generated.rust_source


def test_parallel_iterator_tracks_indexing_and_explicit_find_semantics(
    tmp_path: Path,
) -> None:
    source = tmp_path / "parallel_indexed.py"
    source.write_text(
        """\
from crabwalk import rust

rayon = rust.crate("rayon", version="1")

@rust.fn
def indexed(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.Vec[rust.Tuple[rust.usize, rust.u64]]:
    return values.par_iter().copied().enumerate().collect_vec()

@rust.fn
def first(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.Option[rust.u64]:
    return values.par_iter().copied().find_first(lambda value: value > 2)

@rust.fn
def last(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.Option[rust.u64]:
    return values.par_iter().copied().find_last(lambda value: value > 2)

@rust.fn
def any_match(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.Option[rust.u64]:
    return values.par_iter().copied().find_any(lambda value: value > 2)
""",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_parallel_indexed")
    collected = ir.functions[0].body[0].value
    assert isinstance(collected.receiver.type_ref, IteratorType)
    assert collected.receiver.type_ref.indexing == IteratorIndexing.INDEXED
    assert ".find_first(" in generated.rust_source
    assert ".find_last(" in generated.rust_source
    assert ".find_any(" in generated.rust_source


@pytest.mark.parametrize(
    ("tail", "detail"),
    (
        (
            ".filter(lambda value: value > 1).enumerate().collect_vec()",
            "enumerate",
        ),
        (
            ".filter(lambda value: value > 1).zip(other.par_iter().copied()).collect_vec()",
            "zip",
        ),
        (
            ".find(lambda value: value > 1)",
            "find",
        ),
    ),
)
@capability_contract("rayon.unindexed-order-rejected")
def test_unindexed_parallel_adapters_are_rejected_before_rustc(
    tmp_path: Path,
    tail: str,
    detail: str,
) -> None:
    source = tmp_path / f"unindexed_{detail}.py"
    source.write_text(
        f"""\
from crabwalk import rust

rayon = rust.crate("rayon", version="1")

@rust.fn
def invalid(
    values: rust.Ref[rust.Vec[rust.u64]],
    other: rust.Ref[rust.Vec[rust.u64]],
) -> rust.Vec[rust.Tuple[rust.usize, rust.u64]]:
    return values.par_iter().copied(){tail}
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB225"
    assert detail in diagnostic.title.lower()


def test_borrowed_for_item_cannot_be_consumed_as_an_owned_value(
    tmp_path: Path,
) -> None:
    source = tmp_path / "borrowed_move.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def invalid(rows: rust.Ref[rust.Vec[rust.String]]) -> rust.Vec[rust.String]:
    output: rust.Vec[rust.String] = rust.Vec([])
    for row in rows.iter_ref():
        output.push(row)
    return output
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)
    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB115"
    assert "rust.Ref[rust.String]" in diagnostic.message


@capability_contract("compiler.pattern-identity")
def test_patterns_are_structured_and_capture_renaming_cannot_touch_literals_or_fields(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pattern_hygiene.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Point:
    x: rust.u64

@rust.fn
def tuple_case(x: rust.u64, marker: rust.char) -> rust.u64:
    pair: rust.Tuple[rust.u64, rust.char] = (x, marker)
    match pair:
        case (x, "x"):
            return x
        case _:
            return 0

@rust.fn
def record_case(x: rust.u64) -> rust.u64:
    point: Point = Point(x=x)
    match point:
        case Point(x=x):
            return x
""",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_pattern_hygiene")
    tuple_match = ir.functions[0].body[1]
    record_match = ir.functions[1].body[1]

    assert isinstance(tuple_match, PatternMatchIR)
    tuple_pattern = tuple_match.arms[0].pattern
    assert isinstance(tuple_pattern, PatternTupleIR)
    assert isinstance(tuple_pattern.items[0], PatternCaptureIR)
    assert isinstance(tuple_pattern.items[1], PatternLiteralIR)
    assert isinstance(record_match, PatternMatchIR)
    record_pattern = record_match.arms[0].pattern
    assert isinstance(record_pattern, PatternConstructorIR)
    assert record_pattern.fields[0].rust_name == "x"
    assert isinstance(record_pattern.fields[0].pattern, PatternCaptureIR)
    assert "'x'" in generated.rust_source
    assert re.search(r"\{ x: cw_b_[^, }]+ \}", generated.rust_source)


def test_hashmap_return_keys_must_have_hashable_python_representations(
    tmp_path: Path,
) -> None:
    accepted = tmp_path / "accepted_keys.py"
    accepted.write_text(
        """\
from crabwalk import rust

@rust.fn
def values() -> rust.HashMap[
    rust.Tuple[rust.String, rust.Option[rust.Vec[rust.u8]]],
    rust.u64,
]:
    result: rust.HashMap[
        rust.Tuple[rust.String, rust.Option[rust.Vec[rust.u8]]],
        rust.u64,
    ] = rust.HashMap()
    result.insert(("key", rust.Some(rust.Vec([1, 2]))), 3)
    return result
""",
        encoding="utf-8",
    )
    assert analyze_path(accepted).functions[0].return_type.rust_name == "HashMap"

    rejected = tmp_path / "rejected_keys.py"
    rejected.write_text(
        """\
from crabwalk import rust

@rust.fn
def values() -> rust.HashMap[rust.Vec[rust.u64], rust.u64]:
    result: rust.HashMap[rust.Vec[rust.u64], rust.u64] = rust.HashMap()
    result.insert(rust.Vec([1, 2]), 3)
    return result
""",
        encoding="utf-8",
    )
    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(rejected)
    assert captured.value.diagnostics[0].code == "CRAB202"
