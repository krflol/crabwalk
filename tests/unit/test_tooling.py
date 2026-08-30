from __future__ import annotations

import io
import json
from pathlib import Path

from crabwalk.cli import build_parser, main
from crabwalk.compiler.capabilities import capability_contract
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import Diagnostic, SourceSpan
from crabwalk.lsp import _lsp_diagnostic, serve
from crabwalk.service import CompilationResult
from crabwalk.tooling import (
    DIAGNOSTIC_SCHEMA_VERSION,
    diagnostic_document,
    explain_diagnostic,
    export_generated_project,
)


@capability_contract("tooling.diagnostics-explain-lsp", native=False)
def test_machine_diagnostics_explain_and_lsp_contract(tmp_path: Path) -> None:
    span = SourceSpan(str(tmp_path / "kernel.py"), 2, 3, 2, 8)
    diagnostic = Diagnostic("CRAB102", "Unsupported construct", "bad call", span)
    payload = diagnostic_document((diagnostic,), operation="check")
    assert payload["schema_version"] == DIAGNOSTIC_SCHEMA_VERSION
    diagnostics = payload["diagnostics"]
    assert isinstance(diagnostics, list)
    assert diagnostics[0]["code"] == "CRAB102"
    assert explain_diagnostic("crab102") is not None
    lsp = _lsp_diagnostic(diagnostic)
    assert lsp["range"] == {
        "start": {"line": 1, "character": 2},
        "end": {"line": 1, "character": 7},
    }


def test_lsp_stdio_initialization_and_shutdown_are_framed() -> None:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "shutdown"},
        {"jsonrpc": "2.0", "method": "exit"},
    ]
    incoming = io.BytesIO()
    for request in requests:
        payload = json.dumps(request).encode()
        incoming.write(f"Content-Length: {len(payload)}\r\n\r\n".encode())
        incoming.write(payload)
    incoming.seek(0)
    outgoing = io.BytesIO()

    assert serve(incoming, outgoing) == 0
    assert outgoing.getvalue().count(b"Content-Length:") == 2
    assert b'"textDocumentSync":1' in outgoing.getvalue()


@capability_contract("tooling.export-rust", native=False)
def test_export_rust_copies_exact_generated_project(tmp_path: Path) -> None:
    source = tmp_path / "kernel.py"
    source.write_text(
        "from crabwalk import rust\n\n"
        "@rust.fn\n"
        "def value() -> rust.u64:\n"
        "    return 1\n",
        encoding="utf-8",
    )
    generated = tmp_path / "generated"
    files = {
        "Cargo.toml": "[package]\nname='example'\n",
        "Cargo.lock": "version = 4\n",
        "build.rs": "fn main() {}\n",
        "crabwalk-ir.json": "{}\n",
        "crabwalk-source-map.json": "{}\n",
        "crabwalk-build-inputs.json": "{}\n",
        "src/lib.rs": "pub fn value() -> u64 { 1 }\n",
    }
    for relative, content in files.items():
        path = generated / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    result = CompilationResult(
        ir=analyze_path(source),
        fingerprint="a" * 64,
        extension_name="_example",
        project_root=tmp_path,
        generated_dir=generated,
        artifact=None,
        cache_hit=False,
        module=None,
        command=None,
    )

    destination = export_generated_project(result, tmp_path / "export")

    assert (destination / "src" / "lib.rs").read_text(encoding="utf-8") == files[
        "src/lib.rs"
    ]
    manifest = json.loads((destination / "crabwalk-export.json").read_text())
    assert manifest["fingerprint"] == "a" * 64


@capability_contract("tooling.watch", native=False)
def test_check_watch_and_json_diagnostic_cli_contract(
    tmp_path: Path,
    capsys,
) -> None:
    arguments = build_parser().parse_args(
        ["check", str(tmp_path / "kernel.py"), "--watch", "--watch-interval", "0.1"]
    )
    assert arguments.watch is True
    assert arguments.watch_interval == 0.1

    invalid = tmp_path / "invalid.py"
    invalid.write_text("def broken(:\n", encoding="utf-8")
    assert main(["check", str(invalid), "--diagnostic-format", "json"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["schema_version"] == DIAGNOSTIC_SCHEMA_VERSION
    assert output["diagnostics"][0]["code"] == "CRAB100"
