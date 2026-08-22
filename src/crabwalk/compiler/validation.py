"""Cross-pass invariants checked after semantic lowering and before Rust emission."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, Iterator

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic

from .ir import (
    CallIR,
    ClosureIR,
    ConstructorIR,
    Effect,
    FunctionIR,
    MethodCallIR,
    PackageIR,
    PanicIR,
    PythonPrintIR,
)


def validate_package_ir(ir: PackageIR) -> None:
    """Assert compiler invariants and reject unsafe cross-feature interactions."""

    functions = {function.rust_symbol: function for function in ir.functions}
    for function in ir.functions:
        expressions = tuple(_walk_ir(function.body))
        _validate_effect_annotations(function, expressions)
        for expression in expressions:
            closure = _worker_closure(expression)
            if closure is None:
                continue
            offender = _python_runtime_offender(closure, functions)
            if offender is None:
                continue
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB206",
                    "Python runtime effect inside a native worker",
                    (
                        f"{function.qualified_name} sends a closure to a Rust worker "
                        "that reaches Python runtime state."
                    ),
                    offender.span,
                    "Keep worker closures native-only and cross Python at the exported wrapper.",
                )
            )


def _validate_effect_annotations(
    function: FunctionIR,
    expressions: tuple[object, ...],
) -> None:
    effects = set(function.effects)
    required: set[Effect] = set()
    for expression in expressions:
        if isinstance(expression, PythonPrintIR):
            required.add(Effect.PYTHON_RUNTIME)
        elif isinstance(expression, PanicIR):
            required.add(Effect.MAY_PANIC)
        elif isinstance(expression, ConstructorIR):
            if expression.constructor in {"UnsafeRead", "UnsafeWrite"}:
                required.add(Effect.UNSAFE_MEMORY)
            elif expression.constructor == "CAbs":
                required.update({Effect.UNSAFE_FFI, Effect.MAY_PANIC})
            elif expression.constructor == "UnsafeStaticIncrement":
                required.update({Effect.GLOBAL_MUTATION, Effect.MAY_PANIC})
    missing = required - effects
    if missing:
        names = ", ".join(sorted(effect.value for effect in missing))
        raise AssertionError(
            f"IR effect invariant failed for {function.qualified_name}: missing {names}"
        )
    if function.python_boundary != (Effect.PYTHON_RUNTIME in effects):
        raise AssertionError(
            f"IR Python-boundary invariant failed for {function.qualified_name}"
        )


def _worker_closure(expression: object) -> ClosureIR | None:
    if (
        isinstance(expression, ConstructorIR)
        and expression.constructor == "Spawn"
        and expression.arguments
        and isinstance(expression.arguments[0], ClosureIR)
    ):
        return expression.arguments[0]
    if (
        isinstance(expression, MethodCallIR)
        and expression.receiver.type_ref.underlying.rust_name == "ThreadPool"
        and expression.method == "execute"
        and expression.arguments
        and isinstance(expression.arguments[0], ClosureIR)
    ):
        return expression.arguments[0]
    return None


def _python_runtime_offender(
    closure: ClosureIR,
    functions: dict[str, FunctionIR],
) -> PythonPrintIR | CallIR | None:
    for expression in _walk_ir(closure.body):
        if isinstance(expression, PythonPrintIR):
            return expression
        if isinstance(expression, CallIR):
            target = functions.get(expression.target)
            if target is not None and Effect.PYTHON_RUNTIME in target.effects:
                return expression
    return None


def _walk_ir(value: object) -> Iterator[Any]:
    if isinstance(value, tuple):
        for item in value:
            yield from _walk_ir(item)
        return
    if not is_dataclass(value):
        return
    yield value
    for field in fields(value):
        if field.name in {"span", "type_ref", "return_type", "parameters"}:
            continue
        yield from _walk_ir(getattr(value, field.name))
