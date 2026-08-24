"""Source-oriented diagnostics shared by typed lowering passes."""

from __future__ import annotations

import ast
import keyword
from collections.abc import Collection
from pathlib import Path
from typing import Literal, NoReturn

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic, SourceSpan


def fail(
    code: str,
    title: str,
    message: str,
    path: Path,
    node: ast.AST,
    help_text: str | None = None,
) -> NoReturn:
    raise CrabwalkCompilationError(
        Diagnostic(
            code,
            title,
            message,
            SourceSpan.from_ast(path, node),
            help_text,
        )
    )


def unsupported(
    node: ast.AST,
    path: Path,
    help_text: str | None = None,
    *,
    construct_name: str | None = None,
) -> NoReturn:
    fail(
        "CRAB102",
        "Unsupported construct in @rust.fn",
        (
            f"{construct_name or type(node).__name__} cannot be lowered by "
            "the active compiler."
        ),
        path,
        node,
        help_text or "Move it outside @rust.fn or use a supported Rust equivalent.",
    )


def validate_source_binding(
    name: str,
    path: Path,
    node: ast.AST,
    kind: str,
    *,
    reserved: Collection[str] | None = None,
    rust_namespace: Literal["value", "type", "member"] = "value",
) -> None:
    reserved = reserved or ()
    del rust_namespace
    if not name.isidentifier() or keyword.iskeyword(name) or name in reserved:
        reason = (
            "a generated or runtime-reserved Python member"
            if name in reserved
            else "an unsupported Python identifier"
        )
        fail(
            "CRAB210",
            "Unsupported Rust binding name",
            f"The {kind} name '{name}' is {reason}.",
            path,
            node,
            (
                "Choose a valid Python identifier that does not overlap the "
                "generated Python wrapper API for this declaration."
            ),
        )


def validate_unicode_text(value: str, path: Path, node: ast.AST) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        fail(
            "CRAB212",
            "String is not valid Unicode scalar text",
            "Rust strings and chars cannot contain an escaped lone surrogate.",
            path,
            node,
            "Replace the surrogate with a Unicode scalar value or ordinary text.",
        )
