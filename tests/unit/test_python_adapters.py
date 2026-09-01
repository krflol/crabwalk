from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.capabilities import ContractKind, capability_contract
from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import Effect
from crabwalk.diagnostics import CrabwalkCompilationError
from crabwalk.inspection import function_inspection


PYTHON_ADAPTER_SOURCE = """\
from crabwalk import rust

@rust.python_adapter(effects=[rust.Blocking])
def python_label(value: rust.u64) -> rust.String:
    return f"item-{value}"

@rust.python_adapter
def python_failure(value: rust.u64) -> rust.u64:
    raise ValueError(f"bad-{value}")

@rust.python_adapter
def python_wrong_type(value: rust.u64) -> rust.u64:
    return "not-an-int"

@rust.python_adapter(module="operator", name="neg")
def python_neg(value: rust.i64) -> rust.i64:
    pass

@rust.fn
def label(value: rust.u64) -> rust.String:
    return python_label(value)

@rust.fn
def fail(value: rust.u64) -> rust.u64:
    return python_failure(value)

@rust.fn
def wrong_type(value: rust.u64) -> rust.u64:
    return python_wrong_type(value)

@rust.fn
def negate(value: rust.i64) -> rust.i64:
    return python_neg(value)

@rust.struct
class SignedValue:
    value: rust.i64

@rust.method(SignedValue, name="negated")
def negated(value: rust.Ref[SignedValue]) -> rust.i64:
    return python_neg(value.value)

@rust.fn
def negate_via_method(value: rust.i64) -> rust.i64:
    wrapped: SignedValue = SignedValue(value=value)
    return wrapped.negated()
"""


def test_python_adapter_has_typed_codegen_effects_and_inspection(
    tmp_path: Path,
) -> None:
    source = tmp_path / "python_adapter.py"
    source.write_text(PYTHON_ADAPTER_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_python_adapter")
    label = next(value for value in ir.functions if value.name == "label")
    inspection = function_inspection(label)

    assert Effect.PYTHON_RUNTIME in label.effects
    assert Effect.BLOCKING in label.effects
    assert Effect.MAY_PANIC in label.effects
    assert "Python::attach(|py| -> PyResult<String>" in generated.rust_source
    assert 'PyModule::import(py, "python_adapter")' in generated.rust_source
    assert '.getattr("python_label")' in generated.rust_source
    assert 'PyModule::import(py, "operator")' in generated.rust_source
    assert '.getattr("neg")' in generated.rust_source
    assert inspection["gil"] == "held or reacquired for Python runtime operations"
    assert inspection["python_calls"][0]["name"] == "python_adapter.python_label"  # type: ignore[index]
    negate = next(value for value in ir.functions if value.name == "negate")
    negate_inspection = function_inspection(negate)
    assert negate_inspection["python_calls"][0]["name"] == "operator.neg"  # type: ignore[index]
    assert "fn negated(&self) -> PyResult<i64>" in generated.rust_source
    assert "wrapped.negated()?" in generated.rust_source


def test_python_adapter_error_hook_is_emitted_before_pyerr_propagation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "python_adapter_error_hook.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def record_error() -> None:
    pass

@rust.python_adapter(module="operator", name="neg", on_error=record_error)
def python_neg(value: rust.i64) -> rust.i64:
    pass

@rust.fn
def negate(value: rust.i64) -> rust.i64:
    return python_neg(value)
""",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_python_adapter_error_hook")
    negate = next(value for value in ir.functions if value.name == "negate")
    hook = next(value for value in ir.functions if value.name == "record_error")
    inspection = function_inspection(negate)

    assert ".inspect_err(|_|" in generated.rust_source
    assert f"__cw_native_{hook.rust_symbol}();" in generated.rust_source
    assert inspection["python_calls"][0]["error_hook"] == hook.rust_symbol  # type: ignore[index]


def test_python_adapter_error_hook_requires_native_unit_signature(
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid_python_adapter_error_hook.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def invalid_hook(value: rust.u64) -> None:
    pass

@rust.python_adapter(on_error=invalid_hook)
def python_value(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    assert captured.value.diagnostics[0].code == "CRAB232"
    assert "error hook" in captured.value.diagnostics[0].title.lower()


def test_python_adapter_error_hook_must_preserve_original_error(
    tmp_path: Path,
) -> None:
    source = tmp_path / "panicking_python_adapter_error_hook.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def invalid_hook() -> None:
    rust.panic("do not replace the Python error")

@rust.python_adapter(on_error=invalid_hook)
def python_value(value: rust.u64) -> rust.u64:
    return value

@rust.fn
def call_python(value: rust.u64) -> rust.u64:
    return python_value(value)
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        generate_project(
            analyze_path(source),
            "_crabwalk_panicking_python_adapter_error_hook",
        )

    assert captured.value.diagnostics[0].code == "CRAB238"
    assert "error hook" in captured.value.diagnostics[0].title.lower()


@capability_contract(
    "python-adapter.invalid-placement",
    native=False,
    kind=ContractKind.NEGATIVE,
)
def test_python_adapter_is_rejected_inside_native_iterator_closure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid_python_adapter.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.python_adapter
def python_value(value: rust.u64) -> rust.u64:
    return value

@rust.fn
def invalid(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.Vec[rust.u64]:
    return values.iter().map(lambda value: python_value(value)).collect_vec()
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        generate_project(analyze_path(source), "_crabwalk_invalid_python_adapter")

    assert captured.value.diagnostics[0].code == "CRAB207"
    assert "closure" in captured.value.diagnostics[0].title
