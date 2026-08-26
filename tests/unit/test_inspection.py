from __future__ import annotations

from pathlib import Path

from crabwalk.cli import _show
from crabwalk.inspection import compilation_inspection
from crabwalk.service import default_service


def test_inspection_reports_effects_calls_conversions_cache_and_gil(
    tmp_path: Path,
    capsys: object,
) -> None:
    source = tmp_path / "inspectable.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def native(value: rust.u64) -> rust.u64:
    return value + 1

@rust.fn
def boundary(name: rust.Str) -> rust.String:
    print(name)
    rust.println(name)
    return rust.String(name)
""",
        encoding="utf-8",
    )
    result = default_service.compile_path(source, mode="expand")

    payload = compilation_inspection(result)
    assert payload["cache"]["status"] == "miss"  # type: ignore[index]
    assert payload["build_command"][0:2] == ["cargo", "build"]  # type: ignore[index]
    assert payload["cargo_policy"] == {"locked": False, "offline": False}
    native, boundary = payload["functions"]  # type: ignore[misc]
    assert native["effects"] == [
        "NativeRust",
        "ConversionBoundary",
        "MayPanic",
    ]
    assert native["gil"] == "released during the native call"
    assert native["parameters"][0]["conversion"]["kind"] == "checked conversion"
    assert boundary["effects"] == [
        "NativeRust",
        "ConversionBoundary",
        "PythonRuntime",
    ]
    assert boundary["python_calls"][0]["name"] == "print"
    assert boundary["native_calls"][0]["name"] == "rust.println"
    assert boundary["return_conversion"]["kind"] == "allocating conversion"

    assert _show(result, "native") == 0
    shown = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "// Effects: NativeRust, ConversionBoundary, MayPanic" in shown
    assert "// GIL: released during the native call" in shown
    assert "// Native implementation" in shown
    assert "// Python ABI wrapper" in shown
    assert f"fn __cw_native_{result.ir.functions[0].rust_symbol}" in shown
    assert f"fn {result.ir.functions[0].rust_symbol}" in shown


def test_inspection_reports_zero_copy_buffer_lease(tmp_path: Path) -> None:
    source = tmp_path / "inspect_buffer.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def total(values: rust.Buffer[rust.f64]) -> rust.f64:
    return values.iter().sum()
""",
        encoding="utf-8",
    )

    payload = compilation_inspection(
        default_service.compile_path(source, mode="expand")
    )
    function = payload["functions"][0]  # type: ignore[index]
    conversion = function["parameters"][0]["conversion"]

    assert function["effects"] == [
        "NativeRust",
        "ConversionBoundary",
        "BorrowedBuffer",
    ]
    assert function["gil"] == "held for ABI conversion or borrowed input lifetime"
    assert conversion == {
        "kind": "call-scoped Python buffer borrow",
        "cost": "constant-time lease; no element copy",
        "detail": (
            "read-only, one-dimensional, C-contiguous native-endian f64 buffer; "
            "GIL held"
        ),
    }


def test_inspection_reports_recursive_composite_return_costs(tmp_path: Path) -> None:
    source = tmp_path / "inspect_composite.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def values() -> rust.Tuple[
    rust.Vec[rust.u64],
    rust.Vec[rust.String],
    rust.HashMap[rust.String, rust.Vec[rust.f64]],
]:
    numbers: rust.Vec[rust.u64] = rust.Vec([])
    labels: rust.Vec[rust.String] = rust.Vec([])
    grouped: rust.HashMap[rust.String, rust.Vec[rust.f64]] = rust.HashMap()
    return numbers, labels, grouped
""",
        encoding="utf-8",
    )

    payload = compilation_inspection(
        default_service.compile_path(source, mode="expand")
    )
    assert payload["schema_version"] == 3
    conversion = payload["functions"][0]["return_conversion"]  # type: ignore[index]

    assert conversion["kind"] == "composite conversion"
    assert conversion["cost"] == (
        "cardinality-dependent; sum of child conversion costs"
    )
    assert conversion["complexity"] == "composite"
    children = conversion["children"]
    assert [child["role"] for child in children] == ["0", "1", "2"]
    assert children[0]["cost"] == "linear in element count plus child conversion"
    assert children[0]["children"][0]["cost"] == "constant"
    assert children[1]["children"][0]["cost"] == "linear in UTF-8 length"
    assert children[2]["kind"] == "mapping conversion"
    assert children[2]["cost"] == ("linear in entry count plus key/value conversion")
    assert [child["role"] for child in children[2]["children"]] == [
        "key",
        "value",
    ]


def test_inspection_does_not_call_fixed_composites_scalars(tmp_path: Path) -> None:
    source = tmp_path / "inspect_tuple.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def pair() -> rust.Tuple[rust.u64, rust.bool]:
    return 1, True
""",
        encoding="utf-8",
    )

    payload = compilation_inspection(
        default_service.compile_path(source, mode="expand")
    )
    conversion = payload["functions"][0]["return_conversion"]  # type: ignore[index]

    assert conversion["kind"] == "composite conversion"
    assert conversion["cost"] == "constant in fixed tuple arity"
    assert conversion["complexity"] == "constant"
    assert "Python tuple" in conversion["detail"]
