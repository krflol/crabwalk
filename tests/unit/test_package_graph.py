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
    assert from_math.crates[0].binding == "regex"

    plus_one = from_math.functions[0]
    returned = plus_one.body[0]
    assert isinstance(returned, ReturnIR)
    assert isinstance(returned.value, BinaryIR)
    assert isinstance(returned.value.left, CallIR)
    assert returned.value.left.target == "cw_demo_pkg__math__double"

    through_module = from_math.functions[-1]
    returned = through_module.body[0]
    assert isinstance(returned, ReturnIR)
    assert isinstance(returned.value, CallIR)
    assert returned.value.target == "cw_demo_pkg__facade__plus_one"

    generated = generate_project(from_math, "_crabwalk_demo_pkg_test")
    assert "fn __cw_native_cw_demo_pkg__math__double" in generated.rust_source
    assert "__cw_native_cw_demo_pkg__math__double(value)" in generated.rust_source
    assert 'regex = { version = "1" }' in generated.cargo_toml
