from pathlib import Path

import pytest

from crabwalk.compiler.frontend import analyze_path, analyze_project_path
from crabwalk.compiler.ir import BinaryIR, CallIR, IfIR, ReturnIR
from crabwalk.diagnostics import CrabwalkCompilationError


FIBONACCI = """\
from crabwalk import rust

@rust.fn
def fibonacci(n: rust.u64) -> rust.u64:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
"""


def write_source(tmp_path: Path, value: str) -> Path:
    path = tmp_path / "app.py"
    path.write_text(value, encoding="utf-8")
    return path


def test_lowers_fibonacci_to_source_spanned_ir(tmp_path: Path) -> None:
    ir = analyze_path(write_source(tmp_path, FIBONACCI), "demo")

    assert ir.module_name == "demo"
    assert len(ir.functions) == 1
    function = ir.functions[0]
    assert function.name == "fibonacci"
    assert function.parameters[0].name == "n"
    assert isinstance(function.body[0], IfIR)
    assert isinstance(function.body[1], ReturnIR)
    expression = function.body[1].value
    assert isinstance(expression, BinaryIR)
    assert isinstance(expression.left, CallIR)
    assert expression.left.target == function.rust_symbol
    assert function.span.line == 4


def test_rejects_unsupported_construct_at_python_source(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        """\
from crabwalk import rust

@rust.fn
def bad(n: rust.u64) -> rust.u64:
    values = [n]
    return n
""",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(path)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB102"
    assert diagnostic.span is not None
    assert diagnostic.span.line == 5
    assert "List" in diagnostic.message


def test_floor_division_diagnostic_points_to_expression_and_names_remedy(
    tmp_path: Path,
) -> None:
    path = write_source(
        tmp_path,
        """\
from crabwalk import rust

@rust.fn
def segments(duration: rust.u64, size: rust.u64) -> rust.u64:
    return (duration + size - 1) // size
""",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(path)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB102"
    assert diagnostic.span is not None
    assert diagnostic.span.line == 5
    assert diagnostic.span.column > 1
    assert "FloorDiv" in diagnostic.message
    assert diagnostic.help is not None
    assert "Use '/' for Rust typed division" in diagnostic.help
    assert "return (duration + size - 1) // size" in diagnostic.render()


def test_requires_return_on_all_paths(tmp_path: Path) -> None:
    path = write_source(
        tmp_path,
        """\
from crabwalk import rust

@rust.fn
def bad(n: rust.u64) -> rust.u64:
    if n <= 1:
        return n
""",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(path)

    assert captured.value.diagnostics[0].code == "CRAB109"


def test_project_analysis_cache_tracks_new_package_sources(tmp_path: Path) -> None:
    package = tmp_path / "demo"
    package.mkdir()
    entry = package / "__init__.py"
    entry.write_text(
        """\
from crabwalk import rust

@rust.fn
def first() -> rust.u64:
    return 1
""",
        encoding="utf-8",
    )
    first = analyze_project_path(entry, "demo")

    (package / "extra.py").write_text(
        """\
from crabwalk import rust

@rust.fn
def second() -> rust.u64:
    return 2
""",
        encoding="utf-8",
    )
    second = analyze_project_path(entry, "demo")

    assert first.source_hash != second.source_hash
    assert {function.name for function in second.functions} == {"first", "second"}
