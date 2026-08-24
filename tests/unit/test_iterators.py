from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import ForEachIR, MethodCallIR, ReturnIR
from crabwalk.compiler.types import (
    IteratorExecution,
    IteratorItemMode,
    IteratorType,
)


SEARCH_SOURCE = """\
from crabwalk import rust

@rust.fn
def search(query: rust.Str, contents: rust.Str) -> rust.Vec[rust.String]:
    matches: rust.Vec[rust.String] = rust.Vec([])
    for line in contents.lines():
        if line.contains(query):
            matches.push(rust.String(line))
    return matches

@rust.fn
def search_case_insensitive(query: rust.Str, contents: rust.Str) -> rust.Vec[rust.String]:
    lowered_query: rust.String = query.to_lowercase()
    matches: rust.Vec[rust.String] = rust.Vec([])
    for line in contents.lines():
        lowered_line: rust.String = line.to_lowercase()
        if lowered_line.contains(lowered_query.as_str()):
            matches.push(rust.String(line))
    return matches
"""


NON_COPY_ITERATOR_SOURCE = """\
from crabwalk import rust

@rust.fn
def normalize_active(
    rows: rust.Ref[rust.Vec[rust.String]],
) -> rust.Vec[rust.String]:
    return (
        rows.iter_ref()
        .filter(lambda row: row.contains("|active|"))
        .map(lambda row: row.to_lowercase())
        .collect_vec()
    )

@rust.fn
def clone_active(
    rows: rust.Ref[rust.Vec[rust.String]],
) -> rust.Vec[rust.String]:
    return (
        rows.iter_ref()
        .filter(lambda row: row.contains("|active|"))
        .cloned()
        .collect_vec()
    )

@rust.fn
def has_active(rows: rust.Ref[rust.Vec[rust.String]]) -> rust.bool:
    return rows.iter_ref().any(lambda row: row.contains("|active|"))

@rust.fn
def fold_total(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.u64:
    return values.iter().fold(0, lambda total, value: total + value)

@rust.fn
def reduce_total(
    values: rust.Ref[rust.Vec[rust.u64]],
) -> rust.Option[rust.u64]:
    return values.iter().reduce(lambda left, right: left + right)
"""


def test_string_lines_lower_to_rust_for_iterator_and_vec_return(tmp_path: Path) -> None:
    source = tmp_path / "search.py"
    source.write_text(SEARCH_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_search")

    assert isinstance(ir.functions[0].body[1], ForEachIR)
    assert "for line in contents.lines()" in generated.rust_source
    assert "let mut matches: Vec<String> = vec![];" in generated.rust_source
    assert "line.contains(query)" in generated.rust_source
    assert "line.to_lowercase()" in generated.rust_source
    assert "lowered_query.as_str()" in generated.rust_source
    assert (
        f"fn {ir.functions[0].rust_symbol}(query: &str, contents: &str) -> PyResult<Vec<String>>"
        in (generated.rust_source)
    )


def test_non_copy_iterator_pipeline_is_typed_by_execution_and_item_mode(
    tmp_path: Path,
) -> None:
    source = tmp_path / "non_copy_iterators.py"
    source.write_text(NON_COPY_ITERATOR_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_non_copy_iterators")
    returned = ir.functions[0].body[0]
    assert isinstance(returned, ReturnIR)
    collected = returned.value
    assert isinstance(collected, MethodCallIR)
    filtered = collected.receiver.receiver
    assert isinstance(filtered, MethodCallIR)
    assert isinstance(filtered.type_ref, IteratorType)
    assert filtered.type_ref.execution == IteratorExecution.SEQUENTIAL
    assert filtered.type_ref.item_mode == IteratorItemMode.SHARED_REF
    assert ".iter().filter(" in generated.rust_source
    assert ".map(|row| row.to_lowercase()).collect::<Vec<_>>()" in (
        generated.rust_source
    )
    assert ".cloned().collect::<Vec<_>>()" in generated.rust_source
    assert '.any(|row| row.contains("|active|"))' in generated.rust_source
    assert ".fold(0u64, |total, value| (total + value))" in generated.rust_source
    assert ".reduce(|left, right| (left + right))" in generated.rust_source
