from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import CrabwalkCompilationError


INTEGRAL_OPERATOR_SOURCE = """\
from crabwalk import rust

@rust.fn
def breakpoint_before_enabled(mode: rust.u8) -> rust.bool:
    return mode & 1 != 0

@rust.fn
def bitwise_pipeline(value: rust.u8) -> rust.u8:
    value &= 15
    value |= 2
    value ^= 1
    value <<= 1
    value >>= 1
    return value
"""


def test_integral_bitwise_operators_lower_to_rust(tmp_path: Path) -> None:
    source = tmp_path / "integral_operators.py"
    source.write_text(INTEGRAL_OPERATOR_SOURCE, encoding="utf-8")

    generated = generate_project(
        analyze_path(source),
        "_crabwalk_integral_operators",
    )

    assert "mode & 1u8" in generated.rust_source
    assert "value = (value & 15u8)" in generated.rust_source
    assert "value = (value | 2u8)" in generated.rust_source
    assert "value = (value ^ 1u8)" in generated.rust_source
    assert "value = (value << 1u8)" in generated.rust_source
    assert "value = (value >> 1u8)" in generated.rust_source


def test_bitwise_operator_rejects_non_integral_values(tmp_path: Path) -> None:
    source = tmp_path / "invalid_bitwise.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def invalid(value: rust.f64) -> rust.f64:
    return value & 1.0
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB115"
    assert "integer" in diagnostic.message.lower()
