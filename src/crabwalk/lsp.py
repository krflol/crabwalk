"""A small stdio LSP adapter for Crabwalk's source-oriented diagnostics."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlparse

from crabwalk.compiler.frontend import analyze_project_path
from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic


def serve(
    input_stream: BinaryIO | None = None,
    output_stream: BinaryIO | None = None,
) -> int:
    """Serve the bounded Crabwalk diagnostics protocol over LSP stdio framing."""

    reader = input_stream or sys.stdin.buffer
    writer = output_stream or sys.stdout.buffer
    shutdown = False
    while request := _read_message(reader):
        method = request.get("method")
        identifier = request.get("id")
        if method == "initialize":
            _write_message(
                writer,
                {
                    "jsonrpc": "2.0",
                    "id": identifier,
                    "result": {
                        "capabilities": {
                            "textDocumentSync": 1,
                        },
                        "serverInfo": {"name": "crabwalk", "version": "1"},
                    },
                },
            )
        elif method == "shutdown":
            shutdown = True
            _write_message(writer, {"jsonrpc": "2.0", "id": identifier, "result": None})
        elif method == "exit":
            return 0 if shutdown else 1
        elif method in {"textDocument/didOpen", "textDocument/didChange"}:
            uri, text = _document_update(request)
            diagnostics = _analyze_document(uri, text)
            _write_message(
                writer,
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {
                        "uri": uri,
                        "diagnostics": [
                            _lsp_diagnostic(value) for value in diagnostics
                        ],
                    },
                },
            )
        elif identifier is not None:
            _write_message(
                writer,
                {
                    "jsonrpc": "2.0",
                    "id": identifier,
                    "error": {"code": -32601, "message": "Method not found"},
                },
            )
    return 0


def _document_update(message: dict[str, object]) -> tuple[str, str | None]:
    params = message.get("params")
    if not isinstance(params, dict):
        return "", None
    document = params.get("textDocument")
    uri = str(document.get("uri", "")) if isinstance(document, dict) else ""
    if message.get("method") == "textDocument/didOpen":
        text = document.get("text") if isinstance(document, dict) else None
        return uri, text if isinstance(text, str) else None
    changes = params.get("contentChanges")
    if isinstance(changes, list) and changes and isinstance(changes[-1], dict):
        text = changes[-1].get("text")
        return uri, text if isinstance(text, str) else None
    return uri, None


def _analyze_document(uri: str, text: str | None) -> tuple[Diagnostic, ...]:
    path = _file_uri_path(uri)
    try:
        if text is None:
            analyze_project_path(path)
        else:
            with tempfile.TemporaryDirectory(prefix="crabwalk-lsp-") as directory:
                snapshot = Path(directory) / (path.name or "document.py")
                snapshot.write_text(text, encoding="utf-8", newline="\n")
                analyze_project_path(snapshot, path.stem or "document")
    except CrabwalkCompilationError as error:
        return error.diagnostics
    return ()


def _file_uri_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return Path(uri)
    value = unquote(parsed.path)
    if sys.platform == "win32" and value.startswith("/"):
        value = value[1:]
    return Path(value)


def _lsp_diagnostic(diagnostic: Diagnostic) -> dict[str, object]:
    span = diagnostic.span
    line = max(0, (span.line if span is not None else 1) - 1)
    column = max(0, (span.column if span is not None else 1) - 1)
    end_line = max(line, (span.end_line if span is not None else line + 1) - 1)
    end_column = max(
        column + 1, (span.end_column if span is not None else column + 2) - 1
    )
    return {
        "range": {
            "start": {"line": line, "character": column},
            "end": {"line": end_line, "character": end_column},
        },
        "severity": 1,
        "code": diagnostic.code,
        "source": "crabwalk",
        "message": f"{diagnostic.title}: {diagnostic.message}",
        "data": {
            "help": diagnostic.help,
            "rustc_code": diagnostic.rustc_code,
            "external_origin": diagnostic.external_origin,
        },
    }


def _read_message(stream: BinaryIO) -> dict[str, object] | None:
    length: int | None = None
    while line := stream.readline():
        if line in {b"\r\n", b"\n"}:
            break
        name, _, value = line.decode("ascii").partition(":")
        if name.casefold() == "content-length":
            length = int(value.strip())
    if length is None:
        return None
    payload = json.loads(stream.read(length).decode("utf-8"))
    return payload if isinstance(payload, dict) else None


def _write_message(stream: BinaryIO, message: dict[str, object]) -> None:
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
    stream.write(payload)
    stream.flush()
