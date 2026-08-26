import re
from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path

from .test_frontend import FIBONACCI, write_source


def test_codegen_is_deterministic_and_native_recursion_is_direct(
    tmp_path: Path,
) -> None:
    source = write_source(tmp_path, FIBONACCI)
    ir = analyze_path(source, "demo")
    first = generate_project(
        ir,
        "_crabwalk_demo_abc",
        cargo_package_identity="src/demo.py",
    )
    second = generate_project(
        ir,
        "_crabwalk_demo_abc",
        cargo_package_identity="src/demo.py",
    )

    assert first == second
    symbol = ir.functions[0].rust_symbol
    assert f"fn __cw_native_{symbol}(n: u64) -> u64" in first.rust_source
    assert f"__cw_native_{symbol}((n - 1u64))" in first.rust_source
    assert "#[pyfunction]" in first.rust_source
    assert '#[pymodule(name = "_crabwalk_demo_abc")]' in first.rust_source
    package_name = re.search(r'^name = "([^"]+)"$', first.cargo_toml, re.MULTILINE)
    assert package_name is not None
    assert re.fullmatch(r"crabwalk-generated-[0-9a-f]{24}", package_name.group(1))
    same_module = generate_project(
        ir,
        "_crabwalk_demo_def",
        cargo_package_identity="src/demo.py",
    )
    same_package_name = re.search(
        r'^name = "([^"]+)"$', same_module.cargo_toml, re.MULTILINE
    )
    assert same_package_name is not None
    assert same_package_name.group(1) == package_name.group(1)
    other = generate_project(
        ir,
        "_crabwalk_other_def",
        cargo_package_identity="other/demo.py",
    )
    other_package_name = re.search(
        r'^name = "([^"]+)"$', other.cargo_toml, re.MULTILINE
    )
    assert other_package_name is not None
    assert other_package_name.group(1) != package_name.group(1)
    assert 'features = ["extension-module"]' in first.cargo_toml
    assert 'pyo3-build-config = { version = "=0.29.2" }' in first.cargo_toml
    assert "// Crabwalk extension unit: _crabwalk_demo_abc" in first.build_rs
    assert 'println!("cargo:rerun-if-changed=build.rs");' in first.build_rs
    assert 'println!("cargo:rustc-link-arg=/Brepro");' in first.build_rs
    assert "add_extension_module_link_args();" in first.build_rs
    assert "create_exception!" in first.rust_source
    assert 'm.add("_CrabwalkNativePanicError"' in first.rust_source
    assert "CrabwalkPanicError:" not in first.rust_source
    assert first.source_map["entries"]


def test_python_boundary_result_is_unwrapped_outside_panic_closure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "python_result.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def validate(value: rust.u64) -> rust.Result[rust.u64, rust.String]:
    print(value)
    if value == 0:
        return rust.Err("zero")
    return rust.Ok(value)
""",
        encoding="utf-8",
    )
    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_python_result")
    symbol = ir.functions[0].rust_symbol

    caught = re.search(
        rf"let (?P<name>__cw_tmp_\d+_[0-9a-f]+) = "
        rf"__cw_catch_panic\(\|\| __cw_native_{symbol}\(value\)\)\?;",
        generated.rust_source,
    )
    assert caught is not None
    assert (
        f"__cw_catch_panic(|| __cw_native_{symbol}(value)?)"
        not in generated.rust_source
    )
    assert re.search(
        rf"let __cw_tmp_\d+_[0-9a-f]+ = {caught.group('name')}\?;",
        generated.rust_source,
    )
    assert (
        '__CwNativeRustResultError::new_err(("rust.String", error.to_string()))'
        in generated.rust_source
    )


def test_owned_wrapper_preflights_every_argument_before_any_take(
    tmp_path: Path,
) -> None:
    source = tmp_path / "atomic_owned.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def consume_two(
    first: rust.Owned[rust.Vec[rust.u64]],
    second: rust.Owned[rust.Vec[rust.u64]],
) -> rust.usize:
    return first.len() + second.len()
""",
        encoding="utf-8",
    )

    generated = generate_project(analyze_path(source), "_crabwalk_atomic_owned")
    rust_source = generated.rust_source

    first_preflight = rust_source.index("if first.value.is_none()")
    second_preflight = rust_source.index("if second.value.is_none()")
    first_take = rust_source.index("first.value.take()")
    second_take = rust_source.index("second.value.take()")
    assert first_preflight < second_preflight < first_take < second_take
