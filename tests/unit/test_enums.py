from pathlib import Path

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import EnumConstructorIR, PatternMatchIR
from crabwalk.compiler.naming import owned_class_names


ENUM_SOURCE = """\
from crabwalk import rust

@rust.enum
class Status:
    Pending = rust.variant()
    Running = rust.variant(progress=rust.u8)
    Failed = rust.variant(rust.String)

@rust.enum
class Heterogeneous:
    Text = rust.variant(rust.String)
    Number = rust.variant(rust.u64)

@rust.fn
def score(status: rust.Ref[Status]) -> rust.u8:
    match status:
        case Status.Pending:
            return 0
        case Status.Running(progress=value):
            return value
        case Status.Failed(_):
            return 255

@rust.fn
def make_score(progress: rust.u8) -> rust.u8:
    status: Status = Status.Running(progress=progress)
    match status:
        case Status.Pending:
            return 0
        case Status.Running(progress=value):
            return value
        case Status.Failed(_):
            return 255
"""


def test_enum_variants_construction_and_match_lower_to_rust(tmp_path: Path) -> None:
    path = tmp_path / "status.py"
    path.write_text(ENUM_SOURCE, encoding="utf-8")

    ir = analyze_path(path, "status")

    assert len(ir.enums) == 2
    status = ir.enums[0]
    assert [variant.name for variant in status.variants] == [
        "Pending",
        "Running",
        "Failed",
    ]
    assert isinstance(ir.functions[0].body[0], PatternMatchIR)
    assert ir.functions[0].body[0].subject_borrowed
    assert isinstance(ir.functions[1].body[0].value, EnumConstructorIR)

    generated = generate_project(ir, "_crabwalk_enum_test")
    status_symbol = status.symbol
    heterogeneous_symbol = ir.enums[1].symbol
    _, owned_status = owned_class_names(status.type_ref)
    assert f"enum {status_symbol} {{" in generated.rust_source
    assert "Running {" in generated.rust_source
    assert "Failed(String)," in generated.rust_source
    score = ir.functions[0]
    assert f"fn __cw_native_{score.rust_symbol}(status: &{status_symbol}) -> u8" in (
        generated.rust_source
    )
    assert f"match <{status_symbol} as Clone>::clone(status)" in generated.rust_source
    assert f"{status_symbol}::Running {{ progress: value }} =>" in generated.rust_source
    assert f"struct {owned_status}" in generated.rust_source
    assert f"value: Option<{status_symbol}>" in generated.rust_source
    assert f"enum {heterogeneous_symbol} {{" in generated.rust_source
    assert "Text(String)," in generated.rust_source
    assert "Number(u64)," in generated.rust_source
    assert "use cw_runtime_pyo3::IntoPyObjectExt;" in generated.rust_source
    assert "PyResult<Option<Py<PyAny>>>" in generated.rust_source
