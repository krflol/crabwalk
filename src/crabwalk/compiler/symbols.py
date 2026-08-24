"""Stable semantic identities and hygienic emitted-name allocation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from crabwalk.diagnostics import SourceSpan

from .naming import (
    COMPILER_LIFETIME_PREFIX,
    COMPILER_TYPE_PREFIX,
    COMPILER_VALUE_PREFIX,
    CRABWALK_BUILTIN_TYPE_NAMES,
    RUST_PRELUDE_VALUE_CONSTRUCTORS,
    is_rust_2024_identifier,
)


class RustNamespace(StrEnum):
    VALUE = "value"
    TYPE = "type"
    LIFETIME = "lifetime"
    MEMBER = "member"


@dataclass(frozen=True, slots=True, order=True)
class SymbolId:
    value: str


@dataclass(frozen=True, slots=True, order=True)
class BindingId:
    value: int


@dataclass(frozen=True, slots=True)
class BindingIR:
    identifier: BindingId
    source_name: str
    rust_name: str
    namespace: RustNamespace
    span: SourceSpan


class Gensym:
    """Allocate injective Rust names for source bindings and compiler temps."""

    __slots__ = ("_next_binding", "_next_temporary", "_reserved", "_source_names")

    def __init__(self, reserved: set[str] | None = None) -> None:
        self._next_binding = 0
        self._next_temporary = 0
        self._reserved = set(reserved or ())
        self._source_names: set[str] = set()

    def bind(
        self,
        source_name: str,
        span: SourceSpan,
        namespace: RustNamespace = RustNamespace.VALUE,
    ) -> BindingIR:
        identifier = BindingId(self._next_binding)
        self._next_binding += 1
        prefix = {
            RustNamespace.VALUE: "cw_b",
            RustNamespace.TYPE: "CwT",
            RustNamespace.LIFETIME: "cw_l",
            RustNamespace.MEMBER: "cw_m",
        }[namespace]
        candidate = self._source_candidate(source_name, namespace)
        source_candidate = candidate is not None and candidate not in self._reserved
        if not source_candidate:
            encoded = source_name.encode("utf-8").hex() or "empty"
            candidate = f"{prefix}_{identifier.value}_{encoded}"
        assert candidate is not None
        if not source_candidate:
            suffix = 0
            base = candidate
            while candidate in self._reserved or candidate in self._source_names:
                suffix += 1
                candidate = f"{base}_{suffix}"
        if source_candidate:
            self._source_names.add(candidate)
        else:
            self._reserved.add(candidate)
        return BindingIR(identifier, source_name, candidate, namespace, span)

    @staticmethod
    def _source_candidate(
        source_name: str,
        namespace: RustNamespace,
    ) -> str | None:
        if not is_rust_2024_identifier(source_name):
            return None
        if namespace == RustNamespace.VALUE:
            if source_name in RUST_PRELUDE_VALUE_CONSTRUCTORS or source_name.startswith(
                COMPILER_VALUE_PREFIX
            ):
                return None
            return source_name
        if namespace == RustNamespace.TYPE:
            if (
                source_name in CRABWALK_BUILTIN_TYPE_NAMES
                or source_name.startswith(COMPILER_TYPE_PREFIX)
                or source_name.startswith(COMPILER_VALUE_PREFIX)
            ):
                return None
            return source_name
        if namespace == RustNamespace.LIFETIME:
            if (
                source_name in CRABWALK_BUILTIN_TYPE_NAMES
                or source_name.startswith(COMPILER_LIFETIME_PREFIX)
                or source_name.startswith(COMPILER_TYPE_PREFIX)
            ):
                return None
            return source_name
        return source_name

    def temporary(self, hint: str = "value") -> str:
        """Return one compiler-owned value name from the same allocator."""

        while True:
            identifier = self._next_temporary
            self._next_temporary += 1
            encoded = hint.encode("utf-8").hex() or "value"
            candidate = f"__cw_tmp_{identifier}_{encoded}"
            if candidate not in self._reserved and candidate not in self._source_names:
                self._reserved.add(candidate)
                return candidate
