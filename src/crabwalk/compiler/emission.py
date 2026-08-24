"""Shared deterministic Rust-emission state.

The semantic compiler owns source bindings. Rust backends own temporary names.
Keeping both identities in one namespace-aware allocator makes it impossible for
an intrinsic, ABI wrapper, or closure adapter to capture a user binding.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import Any

from crabwalk.diagnostics import SourceSpan

from .ir import FunctionIR
from .symbols import BindingIR, Gensym, RustNamespace


class Writer:
    """Indent-aware Rust writer with source-map entries."""

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._indent = 0
        self._map: list[dict[str, object]] = []

    def line(
        self,
        value: str = "",
        span: SourceSpan | None = None,
        kind: str = "generated",
    ) -> None:
        self._lines.append(f"{'    ' * self._indent}{value}" if value else "")
        if span is not None:
            self._map.append(
                {
                    "generated_line": len(self._lines),
                    "source": span.to_dict(),
                    "kind": kind,
                }
            )

    def enter(self) -> None:
        self._indent += 1

    def leave(self) -> None:
        if self._indent == 0:
            raise AssertionError("unbalanced writer indentation")
        self._indent -= 1

    def render(self) -> str:
        if self._indent:
            raise AssertionError("unbalanced writer indentation")
        return "\n".join(self._lines) + "\n"

    @property
    def mappings(self) -> list[dict[str, object]]:
        return list(self._map)


@dataclass(slots=True)
class EmissionNames:
    """Allocate compiler-owned names within one emitted Rust value scope."""

    _gensym: Gensym

    @classmethod
    def empty(cls) -> EmissionNames:
        return cls(Gensym())

    @classmethod
    def for_function(cls, function: FunctionIR) -> EmissionNames:
        return cls(Gensym(reserved_by_namespace=_binding_names(function)))

    @classmethod
    def reserving(cls, *names: str) -> EmissionNames:
        return cls(
            Gensym(
                reserved_by_namespace={RustNamespace.VALUE: set(names)},
            )
        )

    def temporary(self, hint: str = "value") -> str:
        return self._gensym.temporary(hint)

    def type_item(self, hint: str = "type") -> str:
        return self._gensym.temporary(hint, RustNamespace.TYPE)


def _binding_names(value: Any) -> dict[RustNamespace, set[str]]:
    """Collect every semantic binding recursively from one immutable IR value."""

    result: dict[RustNamespace, set[str]] = {
        namespace: set() for namespace in RustNamespace
    }
    pending = [value]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if isinstance(current, BindingIR):
            result[current.namespace].add(current.rust_name)
            continue
        if isinstance(current, (str, bytes, int, float, bool, type(None))):
            continue
        if isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
            continue
        if isinstance(current, (tuple, list, set, frozenset)):
            pending.extend(current)
            continue
        if not is_dataclass(current):
            continue
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        pending.extend(getattr(current, field.name) for field in fields(current))
    return result
