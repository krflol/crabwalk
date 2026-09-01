from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.codegen import function_releases_gil, generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import Effect
from crabwalk.diagnostics import CrabwalkCompilationError
from crabwalk.inspection import function_inspection


def test_empty_fn_call_keeps_automatic_gil_policy(tmp_path: Path) -> None:
    source = tmp_path / "automatic_release.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn()
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )

    function = analyze_path(source).functions[0]
    assert function.release_gil is False
    assert function_releases_gil(function)


def test_fn_rejects_dynamic_release_policy_options(tmp_path: Path) -> None:
    source = tmp_path / "dynamic_release.py"
    source.write_text(
        """\
from crabwalk import rust

OPTIONS = {"release_gil": True}

@rust.fn(**OPTIONS)
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    assert captured.value.diagnostics[0].code == "CRAB236"


def test_explicit_audited_release_moves_owned_value_before_detach(
    tmp_path: Path,
) -> None:
    source = tmp_path / "audited_release.py"
    source.write_text(
        """\
from crabwalk import rust

native = rust.crate("native-wait", path="./native")

@rust.extern(
    native,
    path="wait_len",
    effects=[rust.OpaqueCrateCall, rust.Blocking, rust.MayPanic],
)
def wait_len(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    ...

@rust.fn(release_gil=True)
def run(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    return wait_len(values)
""",
        encoding="utf-8",
    )

    ir = analyze_path(source)
    function = ir.functions[0]
    generated = generate_project(ir, "_crabwalk_audited_release")
    inspection = function_inspection(function)

    assert function.release_gil is True
    assert function_releases_gil(function)
    assert Effect.OPAQUE_CRATE_CALL in function.effects
    assert Effect.BLOCKING in function.effects
    assert inspection["gil_policy"] == "explicit audited release"
    guard_drop = generated.rust_source.index("drop(values);")
    detach = generated.rust_source.index(".detach(move ||")
    assert guard_drop < detach


@pytest.mark.parametrize(
    ("parameter", "body"),
    (
        ("values: rust.Buffer[rust.u8]", "return values.len()"),
        (
            "values: rust.Ref[rust.Vec[rust.u64]]",
            "return values.len()",
        ),
    ),
)
def test_explicit_release_rejects_call_scoped_python_borrows(
    tmp_path: Path,
    parameter: str,
    body: str,
) -> None:
    source = tmp_path / "invalid_release.py"
    source.write_text(
        f"""\
from crabwalk import rust

@rust.fn(release_gil=True)
def invalid({parameter}) -> rust.usize:
    {body}
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        generate_project(analyze_path(source), "_crabwalk_invalid_release")

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB236"
    assert "Python borrow" in diagnostic.title


def test_explicit_release_rejects_python_runtime_effect(tmp_path: Path) -> None:
    source = tmp_path / "python_release.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.python_adapter(module="operator", name="neg")
def negate(value: rust.i64) -> rust.i64:
    pass

@rust.fn(release_gil=True)
def invalid(value: rust.i64) -> rust.i64:
    return negate(value)
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        generate_project(analyze_path(source), "_crabwalk_python_release")

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB236"
    assert "reaches Python" in diagnostic.title
