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
    assert "fn __cw_native_fibonacci(n: u64) -> u64" in first.rust_source
    assert "__cw_native_fibonacci((n - 1u64))" in first.rust_source
    assert "#[pyfunction]" in first.rust_source
    assert '#[pymodule(name = "_crabwalk_demo_abc")]' in first.rust_source
    assert first.source_map["entries"]
