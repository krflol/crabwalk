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
    native, boundary = payload["functions"]  # type: ignore[misc]
    assert native["effects"] == ["NativeRust", "ConversionBoundary"]
    assert native["gil"] == "released during the native call"
    assert native["parameters"][0]["conversion"]["kind"] == "checked conversion"
    assert boundary["effects"] == [
        "NativeRust",
        "ConversionBoundary",
        "PythonRuntimeBoundary",
    ]
    assert boundary["python_calls"][0]["name"] == "print"
    assert boundary["native_calls"][0]["name"] == "rust.println"
    assert boundary["return_conversion"]["kind"] == "allocating conversion"

    assert _show(result, "native") == 0
    shown = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "// Effects: NativeRust, ConversionBoundary" in shown
    assert "// GIL: released during the native call" in shown
    assert "// Native implementation" in shown
    assert "// Python ABI wrapper" in shown
    assert "fn __cw_native_native" in shown
    assert "fn native" in shown
