"""Exhaustive direct-effect rules for semantic Crabwalk expressions."""

from __future__ import annotations

from dataclasses import replace
from typing import get_args

from .ir import (
    ArrayLiteralIR,
    AssignIR,
    AwaitIR,
    BinaryIR,
    BoolLiteralIR,
    BorrowIR,
    CallIR,
    ClosureIR,
    CompareIR,
    ConstructorIR,
    DestructureIR,
    CrateCallIR,
    Effect,
    EnumConstructorIR,
    ExpressionIR,
    ExpressionStatementIR,
    FieldAccessIR,
    FieldAssignIR,
    FloatLiteralIR,
    ForEachIR,
    ForRangeIR,
    FunctionPointerTwiceIR,
    FunctionIR,
    IfIR,
    IndexIR,
    IntLiteralIR,
    LetIR,
    LocalConstIR,
    MatchIR,
    MethodCallIR,
    NameIR,
    NativePrintlnIR,
    NoneLiteralIR,
    PanicIR,
    PatternMatchIR,
    PythonPrintIR,
    ReturnIR,
    StatementIR,
    StringLiteralIR,
    StructConstructorIR,
    TraitCallIR,
    TryIR,
    TupleLiteralIR,
    UnaryIR,
    UNIT,
    WhileIR,
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


EFFECT_ORDER = (
    Effect.NATIVE_RUST,
    Effect.CONVERSION_BOUNDARY,
    Effect.BORROWED_BUFFER,
    Effect.OPAQUE_CRATE_CALL,
    Effect.PYTHON_RUNTIME,
    Effect.BLOCKING,
    Effect.THREAD_SPAWN,
    Effect.GLOBAL_MUTATION,
    Effect.UNSAFE_MEMORY,
    Effect.UNSAFE_FFI,
    Effect.MAY_PANIC,
)


def propagate_effects(functions: tuple[FunctionIR, ...]) -> tuple[FunctionIR, ...]:
    """Infer direct effects and propagate dispatch effects to a fixed point."""

    from .validation import validate_function_symbol_identity

    validate_function_symbol_identity(functions)
    direct = {
        function.rust_symbol: direct_function_effects(function)
        for function in functions
    }
    calls = {
        function.rust_symbol: statement_calls(function.body) for function in functions
    }
    changed = True
    while changed:
        changed = False
        for name, targets in calls.items():
            inherited = {
                effect
                for target in targets
                for effect in direct.get(target, ())
                if effect not in {Effect.NATIVE_RUST, Effect.CONVERSION_BOUNDARY}
            }
            expanded = direct[name] | inherited
            if expanded != direct[name]:
                direct[name] = expanded
                changed = True
    values = []
    for function in functions:
        effects = tuple(
            effect for effect in EFFECT_ORDER if effect in direct[function.rust_symbol]
        )
        values.append(
            replace(
                function,
                python_boundary=Effect.PYTHON_RUNTIME in effects,
                effects=effects,
            )
        )
    return tuple(values)


def direct_function_effects(function: FunctionIR) -> set[Effect]:
    effects = {Effect.NATIVE_RUST}
    if function.parameters or function.return_type != UNIT:
        effects.add(Effect.CONVERSION_BOUNDARY)
    if any(
        parameter.type_ref.underlying.rust_name == "Buffer"
        for parameter in function.parameters
    ):
        effects.add(Effect.BORROWED_BUFFER)
    for statement in function.body:
        for expression in statement_expressions(statement):
            effects.update(direct_expression_effects(expression))
    return effects


def statement_calls(statements: tuple[StatementIR, ...]) -> set[str]:
    return {
        target
        for statement in statements
        for value in statement_expressions(statement)
        for target in expression_dispatch_targets(value)
    }


def expression_dispatch_targets(expression: ExpressionIR) -> tuple[str, ...]:
    if isinstance(expression, CallIR):
        return (expression.target,)
    if isinstance(expression, MethodCallIR):
        values = expression.dispatch_targets
        if (
            expression.target_symbol is not None
            and expression.target_symbol not in values
        ):
            values = (expression.target_symbol, *values)
        return values
    if isinstance(expression, TraitCallIR) and expression.target_symbol is not None:
        return (expression.target_symbol,)
    if isinstance(expression, FunctionPointerTwiceIR):
        return (expression.target,)
    if isinstance(expression, BinaryIR) and expression.target_symbol is not None:
        return (expression.target_symbol,)
    return ()


def statement_expressions(statement: StatementIR) -> tuple[ExpressionIR, ...]:
    """Return every expression in one statement in deterministic preorder."""

    values: list[ExpressionIR] = []

    def visit_expression(expression: ExpressionIR) -> None:
        values.append(expression)
        if isinstance(expression, UnaryIR):
            visit_expression(expression.operand)
        elif isinstance(expression, BorrowIR):
            visit_expression(expression.value)
        elif isinstance(expression, (BinaryIR, CompareIR)):
            visit_expression(expression.left)
            visit_expression(expression.right)
        elif isinstance(expression, (TupleLiteralIR, ArrayLiteralIR)):
            for value in expression.values:
                visit_expression(value)
        elif isinstance(expression, IndexIR):
            visit_expression(expression.receiver)
            visit_expression(expression.index)
        elif isinstance(expression, (CallIR, CrateCallIR, ConstructorIR)):
            for argument in expression.arguments:
                visit_expression(argument)
        elif isinstance(expression, (StructConstructorIR, EnumConstructorIR)):
            for _, argument in expression.arguments:
                visit_expression(argument)
        elif isinstance(expression, FieldAccessIR):
            visit_expression(expression.receiver)
        elif isinstance(expression, MethodCallIR):
            visit_expression(expression.receiver)
            for argument in expression.arguments:
                visit_expression(argument)
        elif isinstance(expression, TraitCallIR):
            visit_expression(expression.receiver)
        elif isinstance(expression, FunctionPointerTwiceIR):
            visit_expression(expression.argument)
        elif isinstance(expression, (NativePrintlnIR, PythonPrintIR)):
            visit_expression(expression.value)
        elif isinstance(expression, (TryIR, AwaitIR)):
            visit_expression(expression.value)
        elif isinstance(expression, PanicIR):
            visit_expression(expression.message)
        elif isinstance(expression, ClosureIR):
            visit_expression(expression.body)

    if isinstance(statement, ReturnIR) and statement.value is not None:
        visit_expression(statement.value)
    elif isinstance(statement, FieldAssignIR):
        visit_expression(statement.receiver)
        visit_expression(statement.value)
    elif isinstance(
        statement,
        (LetIR, AssignIR, DestructureIR, LocalConstIR, ExpressionStatementIR),
    ):
        visit_expression(statement.value)
    elif isinstance(statement, IfIR):
        visit_expression(statement.condition)
        for child in (*statement.body, *statement.otherwise):
            values.extend(statement_expressions(child))
    elif isinstance(statement, WhileIR):
        visit_expression(statement.condition)
        for child in statement.body:
            values.extend(statement_expressions(child))
    elif isinstance(statement, ForRangeIR):
        visit_expression(statement.start)
        visit_expression(statement.stop)
        for child in statement.body:
            values.extend(statement_expressions(child))
    elif isinstance(statement, ForEachIR):
        visit_expression(statement.iterator)
        for child in statement.body:
            values.extend(statement_expressions(child))
    elif isinstance(statement, MatchIR):
        visit_expression(statement.subject)
        for match_arm in statement.arms:
            for child in match_arm.body:
                values.extend(statement_expressions(child))
    elif isinstance(statement, PatternMatchIR):
        visit_expression(statement.subject)
        for pattern_arm in statement.arms:
            if pattern_arm.guard is not None:
                visit_expression(pattern_arm.guard)
            for child in pattern_arm.body:
                values.extend(statement_expressions(child))
    return tuple(values)
