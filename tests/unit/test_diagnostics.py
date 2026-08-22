from pathlib import Path

import pytest

from crabwalk.build.cargo import CargoBuildFailure
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import (
    CrabwalkCompilationError,
    Diagnostic,
    SourceSpan,
    sanitize_external_text,
)
from crabwalk.service import _cargo_diagnostics


def test_diagnostic_renders_original_source(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("value = unsupported()\n", encoding="utf-8")
    diagnostic = Diagnostic(
        "CRAB102",
        "Unsupported construct",
        "This expression cannot be lowered.",
        SourceSpan(str(path), 1, 9, 1, 22),
        "Move it outside @rust.fn.",
    )

    rendered = diagnostic.render()
    assert "app.py:1:9" in rendered
    assert "value = unsupported()" in rendered
    assert "^" in rendered
    assert "help: Move it outside @rust.fn." in rendered


def test_unicode_before_error_uses_character_not_utf8_byte_column(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unicode_error.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def bad(value: rust.u64) -> rust.u64:
    café = [value]
    return value
""",
        encoding="utf-8",
    )
    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)
    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.span is not None
    assert diagnostic.span.line == 5
    assert diagnostic.span.column == 12
    caret = diagnostic.render().splitlines()[4]
    assert caret.index("^") == len("   | ") + 11


def test_external_diagnostics_strip_terminal_controls_and_credentials(
    monkeypatch: object,
) -> None:
    monkeypatch.setenv("PRIVATE_API_TOKEN", "top-secret-value")  # type: ignore[attr-defined]
    cleaned = sanitize_external_text(
        "\x1b[31mfailed\x1b[0m "
        "https://person:password@example.test/path?token=query-secret "
        "top-secret-value\x00"
    )
    assert "\x1b" not in cleaned
    assert "password" not in cleaned
    assert "query-secret" not in cleaned
    assert "top-secret-value" not in cleaned
    assert "<redacted>" in cleaned


def test_crlf_source_preserves_original_line_and_column(tmp_path: Path) -> None:
    source = tmp_path / "crlf_error.py"
    source.write_bytes(
        b"from crabwalk import rust\r\n\r\n"
        b"@rust.fn\r\ndef bad(value: rust.u64) -> rust.u64:\r\n"
        b"    values = [value]\r\n    return value\r\n"
    )
    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)
    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.span is not None
    assert (diagnostic.span.line, diagnostic.span.column) == (5, 14)
    assert "values = [value]" in diagnostic.render()


def test_unmapped_generated_helper_error_falls_back_to_primary_python_span(
    tmp_path: Path,
) -> None:
    source = tmp_path / "helper_error.py"
    source.write_text(
        "from crabwalk import rust\n\n"
        "@rust.fn\n"
        "def identity(value: rust.u64) -> rust.u64:\n"
        "    return value\n",
        encoding="utf-8",
    )
    ir = analyze_path(source)
    failure = CargoBuildFailure(
        ("cargo", "check"),
        (
            {
                "reason": "compiler-message",
                "message": {
                    "level": "error",
                    "message": "generated helper failed",
                    "code": {"code": "E9999"},
                    "spans": [
                        {
                            "line_start": 10_000,
                            "is_primary": True,
                        }
                    ],
                    "rendered": "error[E9999]: generated helper failed",
                },
            },
        ),
        "",
        "",
        101,
    )

    diagnostic = _cargo_diagnostics(failure, {"entries": []}, ir).diagnostics[0]

    assert diagnostic.span == ir.functions[0].span
    assert diagnostic.rustc_code == "E9999"
    assert diagnostic.code == "CRAB301"
