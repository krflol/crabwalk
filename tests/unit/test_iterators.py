from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import ForEachIR


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
