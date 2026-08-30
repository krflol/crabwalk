from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.capabilities import ContractKind, capability_contract
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import CrabwalkCompilationError
from crabwalk.inspection import function_inspection


CALL_ERGONOMICS_SOURCE = """\
from crabwalk import rust

@rust.fn
def adjusted(value: rust.u64, increment: rust.u64 = 2) -> rust.u64:
    return value + increment

@rust.fn
def internal_keyword() -> rust.u64:
    return adjusted(increment=4, value=3)

@rust.fn
def internal_default() -> rust.u64:
    return adjusted(5)
"""


def test_exported_defaults_and_internal_keywords_are_lowered(tmp_path: Path) -> None:
    source = tmp_path / "call_ergonomics.py"
    source.write_text(CALL_ERGONOMICS_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    adjusted = ir.functions[0]
    inspection = function_inspection(adjusted)

    assert adjusted.parameters[0].has_default is False
    assert adjusted.parameters[1].has_default is True
    assert adjusted.parameters[1].default_value == 2
    assert inspection["parameters"][1]["default"] == 2  # type: ignore[index]
    assert inspection["parameters"][1]["has_default"] is True  # type: ignore[index]


@capability_contract(
    "calls.invalid-default",
    native=False,
    kind=ContractKind.NEGATIVE,
)
def test_invalid_default_is_source_spanned(tmp_path: Path) -> None:
    source = tmp_path / "bad_default.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def invalid(value: rust.u8 = 300) -> rust.u8:
    return value
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    assert captured.value.diagnostics[0].code == "CRAB106"
    assert captured.value.diagnostics[0].title == "Invalid function default"
