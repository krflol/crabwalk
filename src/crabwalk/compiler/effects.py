"""Exhaustive direct-effect rules for semantic Crabwalk expressions."""

from __future__ import annotations

from typing import get_args

from .ir import (
    ArrayLiteralIR,
    AwaitIR,
    BinaryIR,
    BoolLiteralIR,
    BorrowIR,
    CallIR,
    ClosureIR,
    CompareIR,
    ConstructorIR,
    CrateCallIR,
    Effect,
    EnumConstructorIR,
    ExpressionIR,
    FieldAccessIR,
    FloatLiteralIR,
    FunctionPointerTwiceIR,
    IndexIR,
    IntLiteralIR,
    MethodCallIR,
    NameIR,
    NativePrintlnIR,
    NoneLiteralIR,
    PanicIR,
    PythonPrintIR,
    StringLiteralIR,
    StructConstructorIR,
    TraitCallIR,
    TryIR,
    TupleLiteralIR,
    UnaryIR,
)


PURE_EXPRESSION_TYPES: tuple[type[object], ...] = (
    IntLiteralIR,
    FloatLiteralIR,
    BoolLiteralIR,
    StringLiteralIR,
    TupleLiteralIR,
    ArrayLiteralIR,
    NoneLiteralIR,
    NameIR,
    CompareIR,
    CallIR,
    BorrowIR,
    StructConstructorIR,
    FieldAccessIR,
    EnumConstructorIR,
    TraitCallIR,
    FunctionPointerTwiceIR,
    NativePrintlnIR,
    TryIR,
    AwaitIR,
    ClosureIR,
)

EFFECTFUL_EXPRESSION_TYPES: tuple[type[object], ...] = (
    IndexIR,
    UnaryIR,
    BinaryIR,
    CrateCallIR,
    ConstructorIR,
    MethodCallIR,
    PythonPrintIR,
    PanicIR,
)


def _type_names(values: frozenset[object] | set[object]) -> str:
    return ", ".join(
        sorted(getattr(value, "__name__", repr(value)) for value in values)
    )


EXPRESSION_EFFECT_RULE_TYPES = frozenset(
    (*PURE_EXPRESSION_TYPES, *EFFECTFUL_EXPRESSION_TYPES)
)
_declared_expression_types = frozenset(get_args(ExpressionIR))
if EXPRESSION_EFFECT_RULE_TYPES != _declared_expression_types:
    missing = _declared_expression_types - EXPRESSION_EFFECT_RULE_TYPES
    stale = EXPRESSION_EFFECT_RULE_TYPES - _declared_expression_types
    raise AssertionError(
        "Expression effect rules are not exhaustive; "
        f"missing={_type_names(missing)}, stale={_type_names(stale)}"
    )


def direct_expression_effects(expression: ExpressionIR) -> frozenset[Effect]:
    """Return effects introduced directly by one node, excluding child calls."""

    if isinstance(expression, PURE_EXPRESSION_TYPES):
        return frozenset()
    if isinstance(expression, IndexIR):
        return frozenset({Effect.MAY_PANIC})
    if isinstance(expression, UnaryIR):
        if expression.operator == "negative" and expression.type_ref.is_signed_integer:
            return frozenset({Effect.MAY_PANIC})
        return frozenset()
    if isinstance(expression, BinaryIR):
        return (
            frozenset({Effect.MAY_PANIC})
            if expression.type_ref.is_integer
            else frozenset()
        )
    if isinstance(expression, CrateCallIR):
        if expression.declared_effects is not None:
            return frozenset(expression.declared_effects)
        effects: set[Effect] = set()
        if expression.path[0] != "std":
            effects.update({Effect.OPAQUE_CRATE_CALL, Effect.MAY_PANIC})
        if (
            expression.path == ("std", "mem", "drop")
            and expression.arguments
            and expression.arguments[0].type_ref.underlying.rust_name == "ThreadPool"
        ):
            effects.add(Effect.BLOCKING)
        return frozenset(effects)
    if isinstance(expression, ConstructorIR):
        effects = set()
        if expression.constructor in {"UnsafeRead", "UnsafeWrite"}:
            effects.add(Effect.UNSAFE_MEMORY)
        elif expression.constructor == "CAbs":
            effects.update({Effect.UNSAFE_FFI, Effect.MAY_PANIC})
        elif expression.constructor == "UnsafeStaticIncrement":
            effects.update({Effect.GLOBAL_MUTATION, Effect.MAY_PANIC})
        elif expression.constructor in {"Spawn", "ThreadPool"}:
            effects.update({Effect.THREAD_SPAWN, Effect.MAY_PANIC})
        elif expression.constructor in {
            "BlockOn",
            "SleepMillis",
            "TcpListener",
            "TcpStream",
        }:
            effects.update({Effect.BLOCKING, Effect.MAY_PANIC})
        return frozenset(effects)
    if isinstance(expression, MethodCallIR):
        effects = set()
        receiver = expression.receiver.type_ref.underlying.rust_name
        if receiver == "Vec" and expression.method == "split_at_mut_sum":
            effects.update({Effect.UNSAFE_MEMORY, Effect.MAY_PANIC})
        if receiver in {"TcpListener", "TcpStream"}:
            effects.update({Effect.BLOCKING, Effect.MAY_PANIC})
        if receiver == "ThreadPool":
            effects.update({Effect.THREAD_SPAWN, Effect.BLOCKING, Effect.MAY_PANIC})
        if receiver == "ThreadHandle" and expression.method == "join":
            effects.update({Effect.BLOCKING, Effect.MAY_PANIC})
        if receiver == "Receiver" and expression.method in {"recv", "recv_async"}:
            effects.update({Effect.BLOCKING, Effect.MAY_PANIC})
        if receiver in {"Arc", "Mutex", "RefCell", "Sender"}:
            effects.add(Effect.MAY_PANIC)
        if (
            receiver == "HashMap"
            and expression.method == "add"
            and expression.receiver.type_ref.arguments[1].is_integer
        ):
            effects.add(Effect.MAY_PANIC)
        if expression.method in {"expect", "unwrap"}:
            effects.add(Effect.MAY_PANIC)
        return frozenset(effects)
    if isinstance(expression, PythonPrintIR):
        return frozenset({Effect.PYTHON_RUNTIME})
    if isinstance(expression, PanicIR):
        return frozenset({Effect.MAY_PANIC})
    raise AssertionError(
        f"No direct effect rule for expression {type(expression).__name__}"
    )
