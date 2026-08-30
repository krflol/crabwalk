from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.codegen import function_releases_gil, generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import CrabwalkCompilationError


SHARED_SOURCE = """\
from crabwalk import rust

rayon = rust.crate("rayon", version="1")

@rust.struct
class SharedRow:
    value: rust.u64

@rust.fn
def shared_total(rows: rust.Shared[rust.Vec[SharedRow]]) -> rust.u64:
    return rows.par_iter().map(lambda row: row.value).sum()

@rust.fn
def shared_panic(rows: rust.Shared[rust.Vec[SharedRow]]) -> rust.u64:
    rust.panic("shared panic")
    return 0
"""


def test_shared_handle_uses_arc_and_gil_detach(tmp_path: Path) -> None:
    source = tmp_path / "shared.py"
    source.write_text(SHARED_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_shared")
    shared_total = next(value for value in ir.functions if value.name == "shared_total")

    assert shared_total.parameters[0].type_ref.render().startswith("std::sync::Arc<")
    assert function_releases_gil(shared_total)
    assert '#[pyclass(frozen, name = "_CrabwalkShared_' in generated.rust_source
    assert "value: std::sync::Arc<Vec<" in generated.rust_source
    assert ".value.clone();" in generated.rust_source
    assert ".detach(move ||" in generated.rust_source


@pytest.mark.parametrize(
    "annotation",
    (
        "rust.Shared[rust.Rc[rust.u64]]",
        "rust.Shared[rust.RefCell[rust.u64]]",
        "rust.Shared[rust.Mut[rust.Vec[rust.u64]]]",
    ),
)
def test_non_shareable_payloads_are_rejected_before_rustc(
    tmp_path: Path,
    annotation: str,
) -> None:
    source = tmp_path / "invalid_shared.py"
    source.write_text(
        f"""\
from crabwalk import rust

@rust.fn
def invalid(value: {annotation}) -> rust.u64:
    return 0
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    assert captured.value.diagnostics[0].code in {"CRAB142", "CRAB231"}


def test_shared_payload_cannot_be_mutated(tmp_path: Path) -> None:
    source = tmp_path / "mutate_shared.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def invalid(values: rust.Shared[rust.Vec[rust.u64]]) -> None:
    values.push(1)
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    assert captured.value.diagnostics[0].code == "CRAB208"
