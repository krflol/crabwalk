from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_project_path
from crabwalk.compiler.ir import BinaryIR, CallIR, ReturnIR


def _write_package(root: Path) -> tuple[Path, Path, Path]:
    package = root / "demo_pkg"
    package.mkdir()
    init = package / "__init__.py"
    init.write_text(
        """\
from crabwalk import rust

regex = rust.crate("regex", version="1")

from .math import double
""",
        encoding="utf-8",
    )
    math = package / "math.py"
    math.write_text(
        """\
from crabwalk import rust

@rust.fn
def double(value: rust.u64) -> rust.u64:
    return value * 2
""",
        encoding="utf-8",
    )
    facade = package / "facade.py"
    facade.write_text(
        """\
from crabwalk import rust

from . import double

@rust.fn
def plus_one(value: rust.u64) -> rust.u64:
    return double(value) + 1
""",
        encoding="utf-8",
    )
    text = package / "text.py"
    text.write_text(
        """\
from crabwalk import rust

from . import regex
from . import facade

@rust.fn
def contains_number(value: rust.Str) -> rust.bool:
    return regex.Regex.new(r"\\d+").unwrap().is_match(value)

@rust.fn
def through_module(value: rust.u64) -> rust.u64:
    return facade.plus_one(value)
""",
        encoding="utf-8",
    )
    return math, facade, text


def test_package_graph_resolves_imports_reexports_and_module_calls(
    tmp_path: Path,
) -> None:
    math, _, text = _write_package(tmp_path)

    from_math = analyze_project_path(math, "demo_pkg.math")
    from_text = analyze_project_path(text, "demo_pkg.text")

    assert from_math == from_text
    assert from_math.module_name == "demo_pkg"
    assert len(from_math.source_paths) == 4
    assert [function.qualified_name for function in from_math.functions] == [
        "demo_pkg.facade.plus_one",
        "demo_pkg.math.double",
        "demo_pkg.text.contains_number",
        "demo_pkg.text.through_module",
    ]
    assert len(from_math.crates) == 1
    assert from_math.crates[0].package == "regex"

    plus_one = from_math.functions[0]
    returned = plus_one.body[0]
    assert isinstance(returned, ReturnIR)
    assert isinstance(returned.value, BinaryIR)
    assert isinstance(returned.value.left, CallIR)
    double_symbol = next(
        function.rust_symbol
        for function in from_math.functions
        if function.qualified_name == "demo_pkg.math.double"
    )
    assert returned.value.left.target == double_symbol

    through_module = from_math.functions[-1]
    returned = through_module.body[0]
    assert isinstance(returned, ReturnIR)
    assert isinstance(returned.value, CallIR)
    plus_one_symbol = next(
        function.rust_symbol
        for function in from_math.functions
        if function.qualified_name == "demo_pkg.facade.plus_one"
    )
    assert returned.value.target == plus_one_symbol

    generated = generate_project(from_math, "_crabwalk_demo_pkg_test")
    assert f"fn __cw_native_{double_symbol}" in generated.rust_source
    assert f"__cw_native_{double_symbol}(value)" in generated.rust_source
    assert 'regex = { version = "1" }' in generated.cargo_toml


def test_package_graph_resolves_reachable_declaration_cycles_to_a_fixed_point(
    tmp_path: Path,
) -> None:
    package = tmp_path / "cycle_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("from .a import first\n", encoding="utf-8")
    (package / "a.py").write_text(
        """\
from crabwalk import rust
from .b import second

@rust.fn
def first(value: rust.u64) -> rust.u64:
    return second(value)
""",
        encoding="utf-8",
    )
    (package / "b.py").write_text(
        """\
from crabwalk import rust
from .a import first

@rust.fn
def second(value: rust.u64) -> rust.u64:
    return first(value)
""",
        encoding="utf-8",
    )

    ir = analyze_project_path(package)

    assert {function.qualified_name for function in ir.functions} == {
        "cycle_pkg.a.first",
        "cycle_pkg.b.second",
    }


def test_package_graph_applies_public_name_star_imports(
    tmp_path: Path,
) -> None:
    package = tmp_path / "star_pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from .values import *\n"
        "from crabwalk import rust\n\n"
        "@rust.fn\n"
        "def root_value() -> rust.u64:\n"
        "    return value()\n",
        encoding="utf-8",
    )
    (package / "values.py").write_text(
        """\
from crabwalk import rust

@rust.fn
def value() -> rust.u64:
    return 1
""",
        encoding="utf-8",
    )

    ir = analyze_project_path(package)

    assert {function.qualified_name for function in ir.functions} == {
        "star_pkg.root_value",
        "star_pkg.values.value",
    }


def test_parent_initializer_cycle_uses_static_declaration_resolution(
    tmp_path: Path,
) -> None:
    package = tmp_path / "initializer_cycle"
    child = package / "a"
    child.mkdir(parents=True)
    (package / "__init__.py").write_text("from . import x\n", encoding="utf-8")
    (package / "x.py").write_text(
        "from crabwalk import rust\n"
        "from .a import b\n\n"
        "@rust.fn\n"
        "def some_symbol(value: rust.u64) -> rust.u64:\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    (child / "__init__.py").write_text(
        "from ..x import some_symbol\n",
        encoding="utf-8",
    )
    (child / "b.py").write_text("", encoding="utf-8")

    ir = analyze_project_path(package)

    assert [function.qualified_name for function in ir.functions] == [
        "initializer_cycle.x.some_symbol"
    ]


def test_unreachable_python_only_cycle_and_syntax_error_do_not_block_native_graph(
    tmp_path: Path,
) -> None:
    package = tmp_path / "reachable_pkg"
    package.mkdir()
    entry = package / "__init__.py"
    entry.write_text(
        """\
from crabwalk import rust

@rust.fn
def native_value() -> rust.u64:
    return 7
""",
        encoding="utf-8",
    )
    (package / "cycle_a.py").write_text(
        "from .cycle_b import value\n",
        encoding="utf-8",
    )
    (package / "cycle_b.py").write_text(
        "from .cycle_a import value\n",
        encoding="utf-8",
    )
    (package / "dormant_bad.py").write_text(
        "def invalid(:\n",
        encoding="utf-8",
    )

    ir = analyze_project_path(entry, "reachable_pkg")

    assert [function.name for function in ir.functions] == ["native_value"]
    assert ir.source_paths == (str(entry),)


def test_unreachable_edit_changes_wheel_integrity_but_not_compiler_input(
    tmp_path: Path,
) -> None:
    package = tmp_path / "identity_pkg"
    package.mkdir()
    entry = package / "__init__.py"
    entry.write_text(
        """\
from crabwalk import rust

@rust.fn
def native_value() -> rust.u64:
    return 7
""",
        encoding="utf-8",
    )
    unrelated = package / "presentation.py"
    unrelated.write_text("LABEL = 'first'\n", encoding="utf-8")

    first = analyze_project_path(entry, "identity_pkg")
    unrelated.write_text("LABEL = 'second'\n", encoding="utf-8")
    second = analyze_project_path(entry, "identity_pkg")

    assert first.compiler_input_hash == second.compiler_input_hash
    assert first.wheel_source_integrity_hash != second.wheel_source_integrity_hash
