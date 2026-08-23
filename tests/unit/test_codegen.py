from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path

from .test_frontend import FIBONACCI, write_source


def test_codegen_is_deterministic_and_native_recursion_is_direct(
    tmp_path: Path,
) -> None:
    ir = analyze_path(write_source(tmp_path, FIBONACCI), "demo")
    first = generate_project(ir, "_crabwalk_demo_abc")
    second = generate_project(ir, "_crabwalk_demo_abc")

    assert first == second
    symbol = ir.functions[0].rust_symbol
    assert f"fn __cw_native_{symbol}(n: u64) -> u64" in first.rust_source
    assert f"__cw_native_{symbol}((n - 1u64))" in first.rust_source
    assert "#[pyfunction]" in first.rust_source
    assert '#[pymodule(name = "_crabwalk_demo_abc")]' in first.rust_source
    assert 'features = ["extension-module"]' in first.cargo_toml
    assert 'pyo3-build-config = { version = "=0.29.2" }' in first.cargo_toml
    assert "// Crabwalk extension unit: _crabwalk_demo_abc" in first.build_rs
    assert 'println!("cargo:rerun-if-changed=build.rs");' in first.build_rs
    assert 'println!("cargo:rustc-link-arg=/Brepro");' in first.build_rs
    assert "add_extension_module_link_args();" in first.build_rs
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

    assert (
        f"let __cw_result = __cw_catch_panic(|| __cw_native_{symbol}(value))?;"
        in generated.rust_source
    )
    assert (
        f"__cw_catch_panic(|| __cw_native_{symbol}(value)?)"
        not in generated.rust_source
    )
    assert "let __cw_result = __cw_result?;" in generated.rust_source
