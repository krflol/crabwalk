"""Cross-pass invariants checked after semantic lowering and before Rust emission."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, Iterator

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic

from .ir import (
    BinaryIR,
    CallIR,
    ClosureIR,
    ConstructorIR,
    Effect,
    FunctionPointerTwiceIR,
    FunctionIR,
    MethodCallIR,
    PackageIR,
    PanicIR,
    PythonPrintIR,
    TraitCallIR,
)
from .naming import (
    PYO3_CARGO_ALIAS,
    cargo_dependency_key,
    owned_class_names,
)


def validate_package_ir(ir: PackageIR) -> None:
    """Assert compiler invariants and reject unsafe cross-feature interactions."""

    validate_function_symbol_identity(ir.functions)
    _validate_emitted_identifiers(ir)
    functions = {function.rust_symbol: function for function in ir.functions}
    for function in ir.functions:
        expressions = tuple(_walk_ir(function.body))
        _validate_effect_annotations(function, expressions)
        _validate_function_boundary_placement(function, functions)
        worker_closures = {
            id(closure)
            for expression in expressions
            if (closure := _worker_closure(expression)) is not None
        }
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
                    getattr(offender, "span", None),
                    "Keep worker closures native-only and cross Python at the exported wrapper.",
                )
            )
        for expression in expressions:
            if isinstance(expression, FunctionPointerTwiceIR):
                target = functions.get(expression.target)
                if target is not None and Effect.PYTHON_RUNTIME in target.effects:
                    _boundary_error(
                        "Python-runtime function-pointer target is unsupported",
                        (
                            f"{target.qualified_name} returns PyResult at the native "
                            "boundary and cannot inhabit fn(T) -> T."
                        ),
                        expression,
                        "Call the helper directly from an exported synchronous function.",
                    )
            if (
                not isinstance(expression, ClosureIR)
                or id(expression) in worker_closures
            ):
                continue
            offender = _python_runtime_offender(expression, functions)
            if offender is not None:
                _boundary_error(
                    "Python-runtime effect inside a native closure is unsupported",
                    (
                        "Generated iterator and native closures return ordinary Rust "
                        "values, not PyResult."
                    ),
                    offender,
                    "Move the Python operation outside the closure.",
                )


def validate_function_symbol_identity(functions: tuple[FunctionIR, ...]) -> None:
    """Protect symbol-keyed compiler passes before they construct maps."""

    seen: dict[str, FunctionIR] = {}
    for function in functions:
        previous = seen.get(function.rust_symbol)
        if previous is None:
            seen[function.rust_symbol] = function
            continue
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB209",
                "Generated Rust identifier collision",
                (
                    f"{previous.qualified_name} and {function.qualified_name} both "
                    f"map to {function.rust_symbol!r}."
                ),
                function.span,
                "Rename one declaration; compiler-generated identifiers must be unique.",
            )
        )


def _validate_emitted_identifiers(ir: PackageIR) -> None:
    tables: dict[str, list[tuple[str, object, str]]] = {
        "value": [],
        "type": [],
        "method glue": [],
        "cargo dependency": [],
        "crate binding": [],
    }
    value_table = tables["value"]
    type_table = tables["type"]
    method_table = tables["method glue"]
    dependency_table = tables["cargo dependency"]
    crate_binding_table = tables["crate binding"]
    value_table.extend(
        (f"__cw_native_{function.rust_symbol}", function, function.qualified_name)
        for function in ir.functions
    )
    value_table.extend(
        (function.rust_symbol, function, function.qualified_name)
        for function in ir.functions
        if function.exported
    )
    for struct in ir.structs:
        type_table.append((struct.symbol, struct, struct.qualified_name))
    for enum in ir.enums:
        type_table.append((enum.symbol, enum, enum.qualified_name))
    for trait in ir.traits:
        type_table.append((trait.symbol, trait, trait.qualified_name))
    for function in ir.functions:
        if function.method_for is None or function.method_name is None:
            continue
        dispatch = (
            f"trait:{function.trait_symbol}"
            if function.trait_symbol is not None
            else f"operator:{function.operator_kind}"
            if function.operator_kind is not None
            else "inherent"
        )
        method_table.append(
            (
                f"{function.method_for.render()}|{dispatch}|{function.method_name}",
                function,
                function.qualified_name,
            )
        )
    owned_types = [
        parameter.type_ref.underlying
        for function in ir.functions
        if function.exported
        for parameter in function.parameters
        if parameter.type_ref.ownership is not None
        and parameter.type_ref.underlying.rust_name == "Vec"
    ]
    owned_types.extend(struct.type_ref for struct in ir.structs)
    owned_types.extend(enum.type_ref for enum in ir.enums)
    emitted_owned: set[str] = set()
    for type_ref in owned_types:
        _, rust_name = owned_class_names(type_ref)
        if rust_name in emitted_owned:
            continue
        emitted_owned.add(rust_name)
        type_table.append((rust_name, type_ref, type_ref.display()))
    dependency_table.append((PYO3_CARGO_ALIAS, ir, "mandatory PyO3 runtime"))
    dependency_table.extend(
        (
            cargo_dependency_key(crate.package, crate.binding),
            crate,
            crate.package,
        )
        for crate in ir.crates
    )
    crate_binding_table.append(("pyo3", ir, "mandatory PyO3 runtime"))
    crate_binding_table.extend(
        (crate.binding, crate, crate.package) for crate in ir.crates
    )

    reserved_values = {
        "__crabwalk_module",
        "__cw_catch_panic",
        "__cw_panic_message",
    }
    reserved_types = {
        "__CwThreadPool",
        "__CwWorker",
        "__CwNoopWake",
        "__CwJob",
        "__CwWorkerFailure",
    }
    value_table.extend((name, ir, "Crabwalk runtime") for name in reserved_values)
    type_table.extend((name, ir, "Crabwalk runtime") for name in reserved_types)

    for namespace, entries in tables.items():
        seen: dict[str, tuple[object, str]] = {}
        for name, owner, label in entries:
            previous = seen.get(name)
            if previous is None:
                seen[name] = (owner, label)
                continue
            previous_owner, previous_label = previous
            span = getattr(owner, "span", None) or getattr(previous_owner, "span", None)
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB209",
                    "Generated Rust identifier collision",
                    (
                        f"{previous_label} and {label} both emit {name!r} in the "
                        f"{namespace} namespace."
                    ),
                    span,
                    "Rename the source declaration or dependency binding.",
                )
            )


def _validate_function_boundary_placement(
    function: FunctionIR,
    functions: dict[str, FunctionIR],
) -> None:
    if Effect.PYTHON_RUNTIME not in function.effects:
        return
    offender = _python_runtime_offender_in_body(function, functions)
    if function.method_for is not None:
        kind = (
            "operator implementation"
            if function.operator_kind is not None
            else "trait implementation"
            if function.trait_symbol is not None
            else "method"
        )
        _boundary_error(
            f"Python-runtime effect inside a native {kind} is unsupported",
            (
                "Generated Rust method and operator signatures return ordinary "
                "values, not PyResult."
            ),
            offender or function,
            "Keep the implementation native-only and cross Python in an exported wrapper.",
        )
    if function.is_async:
        _boundary_error(
            "Python-runtime effect inside a native async helper is unsupported",
            "Native async helpers produce Future<Output = T>, not Future<Output = PyResult<T>>.",
            offender or function,
            "Cross Python before or after rust.block_on, outside the async helper.",
        )


def _boundary_error(
    title: str,
    message: str,
    offender: object,
    help_text: str,
) -> None:
    raise CrabwalkCompilationError(
        Diagnostic(
            "CRAB207",
            title,
            message,
            getattr(offender, "span", None),
            help_text,
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
) -> object | None:
    for expression in _walk_ir(closure.body):
        if isinstance(expression, PythonPrintIR):
            return expression
        for target_name in _dispatch_targets(expression):
            target = functions.get(target_name)
            if target is not None and Effect.PYTHON_RUNTIME in target.effects:
                return expression
    return None


def _python_runtime_offender_in_body(
    function: FunctionIR,
    functions: dict[str, FunctionIR],
) -> object | None:
    for expression in _walk_ir(function.body):
        if isinstance(expression, PythonPrintIR):
            return expression
        for target_name in _dispatch_targets(expression):
            target = functions.get(target_name)
            if target is not None and Effect.PYTHON_RUNTIME in target.effects:
                return expression
    return None


def _dispatch_targets(expression: object) -> tuple[str, ...]:
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
