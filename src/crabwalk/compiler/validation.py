"""Cross-pass invariants checked after semantic lowering and before Rust emission."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, Iterator, cast

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic

from .effects import EXPRESSION_EFFECT_RULE_TYPES, direct_expression_effects
from .ir import (
    BinaryIR,
    CallIR,
    ClosureIR,
    ConstructorIR,
    CrateCallIR,
    Effect,
    ExpressionIR,
    FunctionPointerTwiceIR,
    FunctionIR,
    MethodCallIR,
    NameIR,
    PackageIR,
    PythonPrintIR,
    StringLiteralIR,
    TraitCallIR,
    TypeRef,
)
from .types import ExternalType, IteratorExecution, IteratorType
from .naming import (
    PYO3_CARGO_ALIAS,
    cargo_dependency_key,
    is_rust_2024_identifier,
    owned_class_names,
    shared_class_names,
)
from .symbols import BindingIR, RustNamespace, SymbolId


def validate_package_ir(ir: PackageIR) -> None:
    """Assert compiler invariants and reject unsafe cross-feature interactions."""

    validate_function_symbol_identity(ir.functions)
    _validate_symbol_and_binding_identities(ir)
    _validate_trait_conformance(ir)
    _validate_emitted_identifiers(ir)
    functions = {function.rust_symbol: function for function in ir.functions}
    for function in ir.functions:
        expressions = tuple(_walk_ir(function.body))
        _validate_unicode_literals(expressions)
        _validate_effect_annotations(function, expressions)
        _validate_release_gil_policy(function)
        _validate_function_boundary_placement(function, functions)
        worker_closures = {
            id(closure)
            for expression in expressions
            if (closure := _worker_closure(expression)) is not None
        }
        for expression in expressions:
            _validate_closure_contract(expression)
            closure = _worker_closure(expression)
            closures = (() if closure is None else (closure,)) + _parallel_closures(
                expression
            )
            for threaded_closure in closures:
                buffer_offender = _buffer_capture_offender(threaded_closure)
                if buffer_offender is None:
                    continue
                raise CrabwalkCompilationError(
                    Diagnostic(
                        "CRAB229",
                        "Borrowed Python buffer cannot enter a native worker",
                        (
                            f"{function.qualified_name} captures a call-scoped "
                            "rust.Buffer value in a thread or Rayon closure."
                        ),
                        buffer_offender.span,
                        (
                            "Read the buffer on the attached calling thread, or copy "
                            "explicitly into a Rust-owned Vec before parallel work."
                        ),
                    )
                )
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


def _validate_closure_contract(expression: object) -> None:
    if not isinstance(expression, MethodCallIR) or not isinstance(
        expression.receiver.type_ref, IteratorType
    ):
        return
    closures = tuple(
        value for value in expression.arguments if isinstance(value, ClosureIR)
    )
    for closure in closures:
        if (
            expression.receiver.type_ref.execution == IteratorExecution.PARALLEL
            and closure.call_trait in {"FnMut", "FnOnce"}
        ):
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB233",
                    "Parallel closure must implement Fn",
                    (
                        f"Rayon {expression.method} may call the closure concurrently; "
                        f"kind={closure.call_trait!r} is not compatible."
                    ),
                    closure.span,
                    "Use kind='fn' with immutable captures.",
                )
            )
        if (
            expression.receiver.type_ref.execution == IteratorExecution.SEQUENTIAL
            and closure.call_trait == "FnOnce"
        ):
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB233",
                    "Iterator adapter may call its closure more than once",
                    (
                        f"Sequential {expression.method} requires FnMut; an explicit "
                        "FnOnce contract can be consumed after one item."
                    ),
                    closure.span,
                    "Use kind='fn' or kind='fn_mut'.",
                )
            )


def _validate_unicode_literals(expressions: tuple[object, ...]) -> None:
    for expression in expressions:
        if not isinstance(expression, StringLiteralIR):
            continue
        try:
            expression.value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB212",
                    "String is not valid Unicode scalar text",
                    "Rust strings and chars cannot contain an escaped lone surrogate.",
                    expression.span,
                    "Replace the surrogate with a Unicode scalar value or ordinary text.",
                )
            ) from error


def _validate_trait_conformance(ir: PackageIR) -> None:
    traits = {trait.symbol: trait for trait in ir.traits}
    implementations: dict[tuple[str, str], dict[str, FunctionIR]] = {}
    associated_by_impl: dict[tuple[str, str], dict[str, TypeRef]] = {}

    def matches_associated(
        pattern: TypeRef,
        concrete: TypeRef,
        bindings: dict[str, TypeRef],
    ) -> bool:
        if pattern.rust_name == "Associated":
            name = pattern.python_name
            assert name is not None
            previous = bindings.get(name)
            if previous is None:
                bindings[name] = concrete
                return True
            return previous == concrete
        if (
            pattern.rust_name != concrete.rust_name
            or pattern.python_name != concrete.python_name
            or pattern.const_value != concrete.const_value
            or len(pattern.arguments) != len(concrete.arguments)
        ):
            return False
        return all(
            matches_associated(left, right, bindings)
            for left, right in zip(pattern.arguments, concrete.arguments, strict=True)
        )

    for function in ir.functions:
        if function.trait_symbol is None:
            continue
        trait = traits.get(function.trait_symbol)
        if trait is None or function.method_for is None or function.method_name is None:
            raise AssertionError(
                f"incomplete trait implementation IR for {function.qualified_name}"
            )
        declared = next(
            (method for method in trait.methods if method.name == function.method_name),
            None,
        )
        if declared is None:
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB211",
                    "Unknown trait implementation method",
                    (
                        f"{function.qualified_name} implements '{function.method_name}', "
                        f"but {trait.qualified_name} does not declare that method."
                    ),
                    function.span,
                    "Use one of the methods declared by rust.trait.",
                )
            )
        receiver = function.parameters[0].type_ref
        if receiver.ownership != declared.receiver_ownership:
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB211",
                    "Trait implementation receiver mismatch",
                    (
                        f"{trait.qualified_name}.{declared.name} requires a "
                        f"rust.{declared.receiver_ownership} receiver, but "
                        f"{function.qualified_name} uses rust.{receiver.ownership}."
                    ),
                    function.parameters[0].span,
                    "Match the receiver mode declared by rust.trait_method.",
                )
            )
        declared_generics = tuple(
            (value.is_lifetime, value.bounds) for value in declared.type_parameters
        )
        implementation_generics = tuple(
            (value.is_lifetime, value.bounds) for value in function.type_parameters
        )
        if implementation_generics != declared_generics:
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB211",
                    "Trait implementation generic mismatch",
                    (
                        f"{trait.qualified_name}.{declared.name} declares "
                        f"{declared_generics}, but {function.qualified_name} "
                        f"declares {implementation_generics}."
                    ),
                    function.span,
                    "Match the trait method type parameters and bounds.",
                )
            )
        key = (trait.symbol, function.method_for.rust_name)
        associated = associated_by_impl.setdefault(key, {})
        implementation_tail = tuple(
            parameter.type_ref for parameter in function.parameters[1:]
        )
        if len(implementation_tail) != len(declared.parameter_types) or not all(
            matches_associated(pattern, concrete, associated)
            for pattern, concrete in zip(
                declared.parameter_types, implementation_tail, strict=True
            )
        ):
            span = (
                function.parameters[1].span
                if len(function.parameters) > 1
                else function.span
            )
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB211",
                    "Trait implementation parameter mismatch",
                    (
                        f"{trait.qualified_name}.{declared.name} requires "
                        f"{tuple(value.display() for value in declared.parameter_types)}, "
                        f"but {function.qualified_name} declares "
                        f"{tuple(value.display() for value in implementation_tail)}."
                    ),
                    span,
                    "Match every tail parameter declared by rust.trait_method.",
                )
            )
        if not matches_associated(
            declared.return_type, function.return_type, associated
        ):
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB211",
                    "Trait implementation return type mismatch",
                    (
                        f"{function.qualified_name} returns "
                        f"{function.return_type.display()}, but "
                        f"{trait.qualified_name}.{declared.name} requires "
                        f"{declared.return_type.display()}."
                    ),
                    function.span,
                    "Match the return type declared by rust.trait.",
                )
            )
        group = implementations.setdefault(key, {})
        previous = group.get(function.method_name)
        if previous is not None:
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB211",
                    "Duplicate trait implementation method",
                    (
                        f"{previous.qualified_name} and {function.qualified_name} both "
                        f"implement {trait.qualified_name}.{function.method_name} for "
                        f"{function.method_for.display()}."
                    ),
                    function.span,
                    "Keep exactly one implementation of each required method.",
                )
            )
        group[function.method_name] = function

    for (trait_symbol, _concrete_symbol), methods in implementations.items():
        trait = traits[trait_symbol]
        missing = [
            method.name for method in trait.methods if method.name not in methods
        ]
        if not missing:
            continue
        representative = next(iter(methods.values()))
        concrete = representative.method_for
        assert concrete is not None
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB211",
                "Incomplete trait implementation",
                (
                    f"{concrete.display()} implements only part of "
                    f"{trait.qualified_name}; missing: {', '.join(missing)}."
                ),
                representative.span,
                (
                    "Add exactly one @rust.impl declaration for every required "
                    "trait method."
                ),
            )
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


def _validate_symbol_and_binding_identities(ir: PackageIR) -> None:
    """Check semantic identities before any backend constructs name-keyed maps."""

    declarations: tuple[Any, ...] = (
        *ir.structs,
        *ir.enums,
        *ir.traits,
        *ir.functions,
    )
    symbols: dict[SymbolId, object] = {}
    for declaration in declarations:
        symbol_id = declaration.symbol_id
        if symbol_id is None:
            raise AssertionError(
                f"{type(declaration).__name__} reached validation without SymbolId"
            )
        previous = symbols.get(symbol_id)
        if previous is not None and previous is not declaration:
            _identity_error(
                declaration,
                f"semantic symbol identity {symbol_id.value!r} is duplicated",
            )
        symbols[symbol_id] = declaration

    for function in ir.functions:
        _validate_binding_scope(function.qualified_name, _walk_bindings(function))
        for parameter in function.parameters:
            _require_binding_namespace(
                parameter.binding, RustNamespace.VALUE, parameter
            )
        for type_parameter in function.type_parameters:
            expected = (
                RustNamespace.LIFETIME
                if type_parameter.is_lifetime
                else RustNamespace.TYPE
            )
            _require_binding_namespace(
                type_parameter.binding,
                expected,
                type_parameter,
            )
    for struct in ir.structs:
        _validate_binding_scope(
            f"{struct.qualified_name} fields",
            (field.binding for field in struct.fields),
        )
        for field in struct.fields:
            _require_binding_namespace(field.binding, RustNamespace.MEMBER, field)
    for enum in ir.enums:
        _validate_binding_scope(
            f"{enum.qualified_name} variants",
            (variant.binding for variant in enum.variants),
        )
        for variant in enum.variants:
            _require_binding_namespace(variant.binding, RustNamespace.MEMBER, variant)
            _validate_binding_scope(
                f"{enum.qualified_name}.{variant.name} fields",
                (field.binding for field in variant.fields),
            )
            for field in variant.fields:
                _require_binding_namespace(field.binding, RustNamespace.MEMBER, field)
    for trait in ir.traits:
        _validate_binding_scope(
            f"{trait.qualified_name} methods",
            (method.binding for method in trait.methods),
        )
        for method in trait.methods:
            _require_binding_namespace(method.binding, RustNamespace.MEMBER, method)


def _walk_bindings(value: object) -> Iterator[BindingIR | None]:
    if isinstance(value, BindingIR):
        yield value
        return
    if isinstance(value, tuple):
        for item in value:
            yield from _walk_bindings(item)
        return
    if not is_dataclass(value):
        return
    for field in fields(value):
        if field.name == "span":
            continue
        yield from _walk_bindings(getattr(value, field.name))


def _validate_binding_scope(
    label: str,
    candidates: Iterator[BindingIR | None],
) -> None:
    by_identifier: dict[int, BindingIR] = {}
    by_namespace: dict[tuple[RustNamespace, str], BindingIR] = {}
    for binding in candidates:
        if binding is None:
            raise AssertionError(f"{label} reached validation without BindingIR")
        previous_identity = by_identifier.get(binding.identifier.value)
        if previous_identity is not None:
            if previous_identity != binding:
                _identity_error(
                    binding,
                    (
                        f"binding id {binding.identifier.value} identifies both "
                        f"{previous_identity.source_name!r} and {binding.source_name!r}"
                    ),
                )
            continue
        by_identifier[binding.identifier.value] = binding
        if not is_rust_2024_identifier(binding.rust_name):
            _identity_error(
                binding,
                f"emitted {binding.namespace} name {binding.rust_name!r} is invalid",
            )
        key = (binding.namespace, binding.rust_name)
        previous_name = by_namespace.get(key)
        if previous_name is not None:
            _identity_error(
                binding,
                (
                    f"{previous_name.source_name!r} and {binding.source_name!r} "
                    f"both emit {binding.rust_name!r} in the "
                    f"{binding.namespace} namespace of {label}"
                ),
            )
        by_namespace[key] = binding


def _require_binding_namespace(
    binding: BindingIR | None,
    expected: RustNamespace,
    owner: object,
) -> None:
    if binding is None:
        raise AssertionError(
            f"{type(owner).__name__} reached validation without BindingIR"
        )
    if binding.namespace != expected:
        _identity_error(
            owner,
            (
                f"{binding.source_name!r} emits in the {binding.namespace} namespace; "
                f"expected {expected}"
            ),
        )


def _identity_error(owner: object, detail: str) -> None:
    raise CrabwalkCompilationError(
        Diagnostic(
            "CRAB209",
            "Generated Rust identity collision",
            detail,
            getattr(owner, "span", None),
            "Compiler semantic identities and emitted namespaces must be injective.",
        )
    )


def _validate_emitted_identifiers(ir: PackageIR) -> None:
    tables: dict[str, list[tuple[str, object, str]]] = {
        "value": [],
        "type": [],
        "macro": [],
        "lifetime": [],
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
        if trait.external_path is None:
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
        and parameter.type_ref.underlying.rust_name in {"Vec", "TextColumn"}
    ]
    owned_types.extend(struct.type_ref for struct in ir.structs)
    owned_types.extend(enum.type_ref for enum in ir.enums if not enum.is_error)
    owned_types.extend(
        parameter.type_ref.underlying
        for function in ir.functions
        if function.exported
        for parameter in function.parameters
        if parameter.type_ref.ownership is not None
        and isinstance(parameter.type_ref.underlying, ExternalType)
    )
    owned_types.extend(
        function.return_type.underlying
        for function in ir.functions
        if function.exported
        and function.return_type.ownership == "Owned"
        and isinstance(function.return_type.underlying, ExternalType)
    )
    emitted_owned: set[str] = set()
    for type_ref in owned_types:
        _, rust_name = owned_class_names(type_ref)
        if rust_name in emitted_owned:
            continue
        emitted_owned.add(rust_name)
        type_table.append((rust_name, type_ref, type_ref.display()))
    shared_types = {
        parameter.type_ref.underlying.render(): parameter.type_ref.underlying
        for function in ir.functions
        if function.exported
        for parameter in function.parameters
        if parameter.type_ref.ownership == "Shared"
    }
    for type_ref in shared_types.values():
        _, rust_name = shared_class_names(type_ref)
        type_table.append((rust_name, type_ref, f"shared {type_ref.display()}"))
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
        "__CwBuffer",
        "__CwTextColumn",
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
    if function.method_for is not None and (
        function.trait_symbol is not None or function.operator_kind is not None
    ):
        kind = (
            "operator implementation"
            if function.operator_kind is not None
            else "trait implementation"
        )
        _boundary_error(
            f"Python-runtime effect inside a native {kind} is unsupported",
            (
                "The implemented Rust trait/operator signature returns an ordinary "
                "value, not PyResult."
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


def _validate_release_gil_policy(function: FunctionIR) -> None:
    if not function.release_gil:
        return
    if not function.exported:
        raise AssertionError("explicit GIL release reached a non-exported function")
    if Effect.PYTHON_RUNTIME in function.effects:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB236",
                "Audited GIL release reaches Python",
                (
                    f"{function.qualified_name} cannot release the GIL because its "
                    "native call graph reaches Python runtime state."
                ),
                function.span,
                "Remove release_gil=True or move the Python operation outside the native call.",
            )
        )
    borrowed = next(
        (
            parameter
            for parameter in function.parameters
            if _type_retains_python_borrow(parameter.type_ref)
        ),
        None,
    )
    if borrowed is not None:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB236",
                "Audited GIL release retains a Python borrow",
                (
                    f"Parameter '{borrowed.name}' uses {borrowed.type_ref.display()}, "
                    "whose value is valid only while its Python guard remains attached."
                ),
                borrowed.span,
                (
                    "Transfer data through rust.Owned, use an immutable rust.Shared "
                    "handle, or keep the GIL held."
                ),
            )
        )


def _type_retains_python_borrow(type_ref: TypeRef) -> bool:
    if type_ref.ownership in {"Owned", "Shared"}:
        return False
    if type_ref.ownership in {"Ref", "Mut"}:
        return True
    if type_ref.rust_name in {"Buffer", "Str", "LifetimeRef"}:
        return True
    return any(_type_retains_python_borrow(value) for value in type_ref.arguments)


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
        if type(expression) in EXPRESSION_EFFECT_RULE_TYPES:
            required.update(direct_expression_effects(cast(ExpressionIR, expression)))
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


def _parallel_closures(expression: object) -> tuple[ClosureIR, ...]:
    if not isinstance(expression, MethodCallIR):
        return ()
    iterator = expression.receiver.type_ref
    if not isinstance(iterator, IteratorType) or (
        iterator.execution != IteratorExecution.PARALLEL
    ):
        return ()
    return tuple(
        argument for argument in expression.arguments if isinstance(argument, ClosureIR)
    )


def _buffer_capture_offender(closure: ClosureIR) -> NameIR | None:
    return next(
        (
            expression
            for expression in _walk_ir(closure.body)
            if isinstance(expression, NameIR)
            and expression.type_ref.underlying.rust_name == "Buffer"
        ),
        None,
    )


def _python_runtime_offender(
    closure: ClosureIR,
    functions: dict[str, FunctionIR],
) -> object | None:
    for expression in _walk_ir(closure.body):
        if isinstance(expression, PythonPrintIR):
            return expression
        if (
            isinstance(expression, CrateCallIR)
            and expression.declared_effects is not None
            and Effect.PYTHON_RUNTIME in expression.declared_effects
        ):
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
        if (
            isinstance(expression, CrateCallIR)
            and expression.declared_effects is not None
            and Effect.PYTHON_RUNTIME in expression.declared_effects
        ):
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
