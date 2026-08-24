"""Source decoding and Python parsing with Crabwalk diagnostics."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic, SourceSpan


@dataclass(frozen=True, slots=True)
class ParsedSource:
    path: Path
    source_bytes: bytes
    text: str
    tree: ast.Module


def attribute_parts(node: ast.AST) -> tuple[str, ...]:
    """Return the dotted source path represented by a Name/Attribute tree."""

    values: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        values.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        values.append(current.id)
        return tuple(reversed(values))
    return ()


def parse_source(path: str | Path) -> ParsedSource:
    source_path = Path(path).resolve()
    try:
        source_bytes = source_path.read_bytes()
        text = source_bytes.decode("utf-8-sig")
    except OSError as error:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB001",
                "Cannot read source",
                str(error),
                help="Check the path and file permissions.",
            )
        ) from error
    except UnicodeDecodeError as error:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB002",
                "Source is not UTF-8",
                str(error),
                help="Save Crabwalk source as UTF-8.",
            )
        ) from error

    try:
        tree = ast.parse(text, filename=str(source_path))
    except SyntaxError as error:
        span = SourceSpan(
            str(source_path),
            error.lineno or 1,
            error.offset or 1,
            error.end_lineno or error.lineno or 1,
            error.end_offset or (error.offset or 1) + 1,
        )
        raise CrabwalkCompilationError(
            Diagnostic("CRAB100", "Invalid Python syntax", error.msg, span)
        ) from error
    return ParsedSource(source_path, source_bytes, text, tree)
