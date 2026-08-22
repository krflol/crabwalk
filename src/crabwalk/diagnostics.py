"""Structured, source-oriented Crabwalk diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from pathlib import Path
from typing import Any, Iterable, cast

_ANSI_ESCAPE = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_URL_CREDENTIALS = re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE)
_SECRET_QUERY = re.compile(
    r"([?&](?:access_token|auth|key|password|secret|token)=)[^&#\s]+",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """A half-open source range using one-based display coordinates."""

    path: str
    line: int
    column: int
    end_line: int
    end_column: int

    @classmethod
    def from_ast(cls, path: Path, node: object) -> "SourceSpan":
        line = int(getattr(node, "lineno", 1))
        column = _unicode_column(path, line, int(getattr(node, "col_offset", 0)))
        end_line = int(getattr(node, "end_lineno", line) or line)
        end_offset = getattr(node, "end_col_offset", None)
        end_column = (
            _unicode_column(path, end_line, int(end_offset))
            if end_offset is not None
            else column + 1
        )
        return cls(
            path=str(path.resolve()),
            line=line,
            column=column,
            end_line=end_line,
            end_column=max(column + 1, end_column),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "SourceSpan":
        return cls(
            path=str(value["path"]),
            line=int(cast(Any, value["line"])),
            column=int(cast(Any, value["column"])),
            end_line=int(cast(Any, value["end_line"])),
            end_column=int(cast(Any, value["end_column"])),
        )


def _unicode_column(path: Path, line_number: int, utf8_offset: int) -> int:
    """Translate CPython AST UTF-8 byte offsets to visible character columns."""

    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        line = lines[line_number - 1]
        prefix = line.encode("utf-8")[:utf8_offset].decode("utf-8")
    except (OSError, UnicodeError, IndexError):
        return utf8_offset + 1
    return len(prefix) + 1


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    title: str
    message: str
    span: SourceSpan | None = None
    help: str | None = None
    rustc_code: str | None = None
    detail: str | None = None

    def render(self) -> str:
        heading = f"{self.code} {self.title}"
        pieces = [heading]
        if self.span is not None:
            pieces.append(f"  --> {self.span.path}:{self.span.line}:{self.span.column}")
            snippet = _read_source_line(self.span)
            if snippet is not None:
                pieces.append("   |")
                pieces.append(f"{self.span.line:>3} | {snippet}")
                width = _caret_width(self.span, snippet)
                pieces.append(f"   | {' ' * max(0, self.span.column - 1)}{'^' * width}")
        pieces.append("")
        pieces.append(self.message)
        if self.help:
            pieces.append(f"help: {self.help}")
        if self.rustc_code:
            pieces.append(f"rustc: {self.rustc_code}")
        if self.detail:
            pieces.append("")
            pieces.append(self.detail.rstrip())
        return "\n".join(pieces)


def _read_source_line(span: SourceSpan) -> str | None:
    try:
        lines = Path(span.path).read_text(encoding="utf-8-sig").splitlines()
        return lines[span.line - 1] if 0 < span.line <= len(lines) else None
    except (OSError, UnicodeError):
        return None


def _caret_width(span: SourceSpan, source_line: str) -> int:
    if span.line != span.end_line:
        return max(1, len(source_line) - span.column + 2)
    return max(1, span.end_column - span.column)


class CrabwalkError(Exception):
    """Base class for Crabwalk failures."""


class CrabwalkCompilationError(CrabwalkError):
    """Compilation failed with one or more structured diagnostics."""

    def __init__(self, diagnostics: Diagnostic | Iterable[Diagnostic]):
        values: tuple[Diagnostic, ...]
        if isinstance(diagnostics, Diagnostic):
            values = (diagnostics,)
        else:
            values = tuple(diagnostics)
        if not values:
            raise ValueError("at least one diagnostic is required")
        self.diagnostics = values
        super().__init__("\n\n".join(item.render() for item in values))


class CrabwalkMoveError(CrabwalkError, RuntimeError):
    """A Rust-owned value was used after its value had moved."""


class CrabwalkBorrowError(CrabwalkError, RuntimeError):
    """A call-scoped shared/mutable borrow conflicted with another access."""


class CrabwalkPanicError(CrabwalkError, RuntimeError):
    """Generated Rust panicked and the extension boundary contained it."""


class CrabwalkRustError(CrabwalkError, RuntimeError):
    """An exported Rust ``Result`` contained ``Err``."""

    def __init__(self, rust_type: str, message: str):
        self.rust_type = rust_type
        self.rust_message = message
        super().__init__(f"{rust_type}: {message}")


class CrabwalkThreadError(CrabwalkError, RuntimeError):
    """A Rust-owned handle crossed threads without an exposed Send policy."""


def sanitize_external_text(value: str, *, limit: int = 20_000) -> str:
    """Remove terminal control sequences and likely credentials from tool output."""

    cleaned = _ANSI_ESCAPE.sub("", value)
    cleaned = _CONTROL.sub("", cleaned)
    cleaned = _URL_CREDENTIALS.sub(r"\1<redacted>@", cleaned)
    cleaned = _SECRET_QUERY.sub(r"\1<redacted>", cleaned)
    for name, secret in os.environ.items():
        if not re.search(r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY)", name, re.I):
            continue
        if len(secret) >= 4:
            cleaned = cleaned.replace(secret, "<redacted>")
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "\n... external diagnostic truncated ..."
    return cleaned
