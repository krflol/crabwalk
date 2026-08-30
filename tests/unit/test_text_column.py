from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.capabilities import (
    ContractKind,
    capability_contract,
)
from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.ir import Effect
from crabwalk.runtime import _validated_text_column_input


TEXT_COLUMN_SOURCE = """\
from crabwalk import rust

@rust.fn
def inspect_row(
    rows: rust.Ref[rust.TextColumn],
    index: rust.usize,
    marker: rust.Str,
) -> rust.Tuple[rust.String, rust.bool, rust.usize]:
    return rows.get(index), rows.contains_at(index, marker), rows.total_bytes()

@rust.fn
def move_column(
    rows: rust.Owned[rust.TextColumn],
) -> rust.Owned[rust.TextColumn]:
    return rows
"""


def test_text_column_generates_owned_utf8_storage(tmp_path: Path) -> None:
    source = tmp_path / "text_column.py"
    source.write_text(TEXT_COLUMN_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_text_column")
    inspect_row = ir.functions[0]

    assert inspect_row.parameters[0].type_ref.underlying.render() == "__CwTextColumn"
    assert Effect.MAY_PANIC in inspect_row.effects
    assert "struct __CwTextColumn { data: Vec<u8>, offsets: Vec<usize> }" in (
        generated.rust_source
    )
    assert "TextColumn offsets must start at zero" in generated.rust_source
    assert "TextColumn segments must contain valid UTF-8" in generated.rust_source
    assert "fn contains_at(&self, index: usize, marker: &str)" in (
        generated.rust_source
    )
    assert "m.add_class::<" in generated.rust_source


@capability_contract(
    "text-column.invalid-layout",
    native=False,
    kind=ContractKind.NEGATIVE,
)
def test_text_column_layout_is_validated_before_native_construction() -> None:
    data = "alphaé".encode()

    assert _validated_text_column_input(data, [0, 5, 7]) == (data, [0, 5, 7])
    assert _validated_text_column_input(memoryview(data), (0, 5, 7)) == (
        data,
        [0, 5, 7],
    )
    with pytest.raises(ValueError, match="start at zero"):
        _validated_text_column_input(data, [1, len(data)])
    with pytest.raises(ValueError, match="final offset"):
        _validated_text_column_input(data, [0, 5])
    with pytest.raises(ValueError, match="not monotonic"):
        _validated_text_column_input(data, [0, 7, 5, 7])
    with pytest.raises(UnicodeError, match="row 0"):
        _validated_text_column_input("é".encode(), [0, 1, 2])
    with pytest.raises(TypeError, match="expected int"):
        _validated_text_column_input(data, [0, True, len(data)])
