"""Resolved compiler signatures shared by discovery and typed lowering."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .ir import Effect, ParameterIR, TypeParameterIR, TypeRef


@dataclass(frozen=True, slots=True)
class Signature:
    name: str
    parameters: tuple[ParameterIR, ...]
    return_type: TypeRef
    node: ast.FunctionDef | ast.AsyncFunctionDef
    module_name: str = ""
    symbol: str = ""
    type_parameters: tuple[TypeParameterIR, ...] = ()
    exported: bool = True
    is_async: bool = False
    method_name: str | None = None
    method_for: TypeRef | None = None
    trait_symbol: str | None = None
    operator_kind: str | None = None
    external_path: tuple[str, ...] | None = None
    external_effects: tuple[Effect, ...] | None = None
    python_error_hook: str | None = None
    release_gil: bool = False

    @property
    def rust_symbol(self) -> str:
        return self.symbol or self.name
