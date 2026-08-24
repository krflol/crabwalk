"""Assign stable semantic identities and hygienic Rust names to local bindings."""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from typing import Any, cast, get_args

from .ir import (
    AssignIR,
    ClosureIR,
    DestructureIR,
    ExpressionIR,
    ForEachIR,
    ForRangeIR,
    FunctionIR,
    IfIR,
    LetIR,
    LocalConstIR,
    MatchArmIR,
    MatchIR,
    NameIR,
    EnumIR,
    EnumVariantIR,
    PackageIR,
    ParameterIR,
    PatternAtIR,
    PatternCaptureIR,
    PatternConstructorIR,
    PatternIR,
    PatternLiteralIR,
    PatternMatchArmIR,
    PatternMatchIR,
    PatternOrIR,
    PatternRangeIR,
    PatternRestIR,
    PatternTupleIR,
    PatternWildcardIR,
    StatementIR,
    StructFieldIR,
    StructIR,
    TraitIR,
    TraitMethodIR,
    TypeParameterIR,
    TypeRef,
    WhileIR,
)
from .symbols import BindingIR, Gensym, RustNamespace, SymbolId
from .types import GenericParameterType, LifetimeReferenceType

_EXPRESSION_CLASSES = get_args(ExpressionIR)


def assign_package_identities(package: PackageIR) -> PackageIR:
    """Return one package whose symbols and local bindings have stable identities."""

    functions = tuple(_bind_function(function) for function in package.functions)
    structs = tuple(_bind_struct(value) for value in package.structs)
    enums = tuple(_bind_enum(value) for value in package.enums)
    traits = tuple(_bind_trait(value) for value in package.traits)
    return replace(
        package,
        functions=functions,
        structs=structs,
        enums=enums,
        traits=traits,
    )


def assign_struct_identity(value: StructIR) -> StructIR:
    """Assign one domain declaration before function/pattern lowering."""

    return _bind_struct(value)


def assign_enum_identity(value: EnumIR) -> EnumIR:
    """Assign one enum and its variant/field member identities."""

    return _bind_enum(value)


def assign_trait_identity(value: TraitIR) -> TraitIR:
    """Assign one trait and its emitted method identities."""

    return _bind_trait(value)


def _bind_fields(fields: tuple[StructFieldIR, ...]) -> tuple[StructFieldIR, ...]:
    gensym = Gensym()
    return tuple(
        replace(
            field,
            binding=gensym.bind(field.name, field.span, RustNamespace.MEMBER),
        )
        for field in fields
    )


def _bind_struct(value: StructIR) -> StructIR:
    return replace(
        value,
        fields=_bind_fields(value.fields),
        symbol_id=SymbolId(f"type:{value.module_name}:{value.name}:{value.symbol}"),
    )


def _bind_enum(value: EnumIR) -> EnumIR:
    variant_gensym = Gensym()
    variants: list[EnumVariantIR] = []
    for variant in value.variants:
        variants.append(
            replace(
                variant,
                fields=_bind_fields(variant.fields),
                binding=variant_gensym.bind(
                    variant.name,
                    variant.span,
                    RustNamespace.MEMBER,
                ),
            )
        )
    return replace(
        value,
        variants=tuple(variants),
        symbol_id=SymbolId(f"type:{value.module_name}:{value.name}:{value.symbol}"),
    )


def _bind_trait(value: TraitIR) -> TraitIR:
    gensym = Gensym()
    methods: list[TraitMethodIR] = []
    for method in value.methods:
        methods.append(
            replace(
                method,
                binding=gensym.bind(
                    method.name,
                    method.span,
                    RustNamespace.MEMBER,
                ),
            )
        )
    return replace(
        value,
        methods=tuple(methods),
        symbol_id=SymbolId(f"trait:{value.module_name}:{value.name}:{value.symbol}"),
    )


def _bind_function(function: FunctionIR) -> FunctionIR:
    gensym = Gensym()
    type_bindings: dict[str, BindingIR] = {}
    rewritten_type_parameters: list[TypeParameterIR] = []
    for type_parameter in function.type_parameters:
        namespace = (
            RustNamespace.LIFETIME if type_parameter.is_lifetime else RustNamespace.TYPE
        )
        binding = gensym.bind(type_parameter.name, type_parameter.span, namespace)
        type_bindings[type_parameter.name] = binding
        rewritten_type_parameters.append(replace(type_parameter, binding=binding))

    environment: dict[str, BindingIR] = {}
    rewritten_parameters: list[ParameterIR] = []
    for parameter in function.parameters:
        binding = gensym.bind(parameter.name, parameter.span)
        environment[parameter.name] = binding
        rewritten_parameters.append(
            replace(
                parameter,
                type_ref=_rename_type(parameter.type_ref, type_bindings),
                binding=binding,
            )
        )

    body = _bind_block(function.body, environment, type_bindings, gensym)
    symbol = SymbolId(
        f"function:{function.module_name}:{function.name}:{function.rust_symbol}"
    )
    return replace(
        function,
        parameters=tuple(rewritten_parameters),
        return_type=_rename_type(function.return_type, type_bindings),
        body=body,
        type_parameters=tuple(rewritten_type_parameters),
        method_for=(
            _rename_type(function.method_for, type_bindings)
            if function.method_for is not None
            else None
        ),
        symbol_id=symbol,
    )


def _rename_type(
    type_ref: TypeRef,
    bindings: dict[str, BindingIR],
) -> TypeRef:
    if isinstance(type_ref, GenericParameterType):
        binding = bindings.get(type_ref.name)
        if binding is None:
            return type_ref
        return replace(type_ref, emitted_name=binding.rust_name)
    if isinstance(type_ref, LifetimeReferenceType):
        binding = bindings.get(type_ref.lifetime_name)
        return replace(
            type_ref,
            target=_rename_type(type_ref.target, bindings),
            emitted_lifetime=(
                binding.rust_name if binding is not None else type_ref.emitted_lifetime
            ),
        )
    if not type_ref.arguments:
        return type_ref
    return type_ref.with_arguments(
        tuple(_rename_type(value, bindings) for value in type_ref.arguments)
    )


def _bind_block(
    statements: tuple[StatementIR, ...],
    inherited: dict[str, BindingIR],
    type_bindings: dict[str, BindingIR],
    gensym: Gensym,
) -> tuple[StatementIR, ...]:
    environment = dict(inherited)
    result: list[StatementIR] = []
    for statement in statements:
        result.append(_bind_statement(statement, environment, type_bindings, gensym))
    return tuple(result)


def _bind_statement(
    statement: StatementIR,
    environment: dict[str, BindingIR],
    type_bindings: dict[str, BindingIR],
    gensym: Gensym,
) -> StatementIR:
    if isinstance(statement, LetIR):
        value = _bind_expression(statement.value, environment, type_bindings, gensym)
        binding = gensym.bind(statement.name, statement.span)
        environment[statement.name] = binding
        return replace(
            statement,
            value=value,
            type_ref=_rename_type(statement.type_ref, type_bindings),
            rust_annotation=(
                _rename_type(statement.rust_annotation, type_bindings)
                if statement.rust_annotation is not None
                else None
            ),
            binding=binding,
        )
    if isinstance(statement, LocalConstIR):
        value = _bind_expression(statement.value, environment, type_bindings, gensym)
        binding = gensym.bind(statement.name, statement.span)
        environment[statement.name] = binding
        return replace(
            statement,
            value=value,
            type_ref=_rename_type(statement.type_ref, type_bindings),
            binding=binding,
        )
    if isinstance(statement, AssignIR):
        return replace(
            statement,
            value=_bind_expression(statement.value, environment, type_bindings, gensym),
            binding=environment.get(statement.name),
        )
    if isinstance(statement, DestructureIR):
        value = _bind_expression(statement.value, environment, type_bindings, gensym)
        bindings = tuple(gensym.bind(name, statement.span) for name in statement.names)
        environment.update(
            (name, binding) for name, binding in zip(statement.names, bindings)
        )
        return replace(
            statement,
            value=value,
            type_ref=_rename_type(statement.type_ref, type_bindings),
            bindings=bindings,
        )
    if isinstance(statement, IfIR):
        return replace(
            statement,
            condition=_bind_expression(
                statement.condition, environment, type_bindings, gensym
            ),
            body=_bind_block(statement.body, environment, type_bindings, gensym),
            otherwise=_bind_block(
                statement.otherwise, environment, type_bindings, gensym
            ),
        )
    if isinstance(statement, WhileIR):
        return replace(
            statement,
            condition=_bind_expression(
                statement.condition, environment, type_bindings, gensym
            ),
            body=_bind_block(statement.body, environment, type_bindings, gensym),
        )
    if isinstance(statement, ForRangeIR):
        start = _bind_expression(statement.start, environment, type_bindings, gensym)
        stop = _bind_expression(statement.stop, environment, type_bindings, gensym)
        binding = gensym.bind(statement.variable, statement.span)
        loop_environment = {**environment, statement.variable: binding}
        return replace(
            statement,
            start=start,
            stop=stop,
            body=_bind_block(statement.body, loop_environment, type_bindings, gensym),
            binding=binding,
        )
    if isinstance(statement, ForEachIR):
        iterator = _bind_expression(
            statement.iterator, environment, type_bindings, gensym
        )
        names = _loop_names(statement.variable)
        bindings = tuple(gensym.bind(name, statement.span) for name in names)
        loop_environment = {
            **environment,
            **dict(zip(names, bindings)),
        }
        return replace(
            statement,
            iterator=iterator,
            item_type=_rename_type(statement.item_type, type_bindings),
            body=_bind_block(statement.body, loop_environment, type_bindings, gensym),
            bindings=bindings,
        )
    if isinstance(statement, MatchIR):
        subject = _bind_expression(
            statement.subject, environment, type_bindings, gensym
        )
        enum_arms = tuple(
            _bind_enum_arm(arm, environment, type_bindings, gensym)
            for arm in statement.arms
        )
        return replace(statement, subject=subject, arms=enum_arms)
    if isinstance(statement, PatternMatchIR):
        subject = _bind_expression(
            statement.subject, environment, type_bindings, gensym
        )
        pattern_arms = tuple(
            _bind_pattern_arm(arm, environment, type_bindings, gensym)
            for arm in statement.arms
        )
        return replace(
            statement,
            subject=subject,
            subject_type=_rename_type(statement.subject_type, type_bindings),
            arms=pattern_arms,
        )
    return cast(
        StatementIR,
        _rewrite_dataclass(statement, environment, type_bindings, gensym),
    )


def _bind_enum_arm(
    arm: MatchArmIR,
    environment: dict[str, BindingIR],
    type_bindings: dict[str, BindingIR],
    gensym: Gensym,
) -> MatchArmIR:
    local_bindings: list[BindingIR | None] = []
    arm_environment = dict(environment)
    rewritten_pairs: list[tuple[str, str]] = []
    for field_name, local_name in arm.bindings:
        if not local_name:
            local_bindings.append(None)
            rewritten_pairs.append((field_name, local_name))
            continue
        binding = gensym.bind(local_name, arm.span)
        local_bindings.append(binding)
        arm_environment[local_name] = binding
        rewritten_pairs.append((field_name, binding.rust_name))
    return replace(
        arm,
        bindings=tuple(rewritten_pairs),
        body=_bind_block(arm.body, arm_environment, type_bindings, gensym),
        local_bindings=tuple(local_bindings),
    )


def _bind_pattern_arm(
    arm: PatternMatchArmIR,
    environment: dict[str, BindingIR],
    type_bindings: dict[str, BindingIR],
    gensym: Gensym,
) -> PatternMatchArmIR:
    local_bindings = tuple(
        gensym.bind(source_name, arm.span) for source_name, _ in arm.bindings
    )
    arm_environment = {
        **environment,
        **{
            source_name: binding
            for (source_name, _), binding in zip(arm.bindings, local_bindings)
        },
    }
    binding_by_name = {
        source_name: binding
        for (source_name, _), binding in zip(arm.bindings, local_bindings)
    }
    return replace(
        arm,
        pattern=_bind_pattern(arm.pattern, binding_by_name, type_bindings),
        bindings=tuple(
            (name, _rename_type(type_ref, type_bindings))
            for name, type_ref in arm.bindings
        ),
        guard=(
            _bind_expression(arm.guard, arm_environment, type_bindings, gensym)
            if arm.guard is not None
            else None
        ),
        body=_bind_block(arm.body, arm_environment, type_bindings, gensym),
        local_bindings=local_bindings,
    )


def _bind_pattern(
    pattern: PatternIR,
    local_bindings: dict[str, BindingIR],
    type_bindings: dict[str, BindingIR],
) -> PatternIR:
    """Assign capture identities without rewriting rendered Rust source text."""

    if isinstance(pattern, PatternCaptureIR):
        binding = local_bindings.get(pattern.name)
        if binding is None:
            raise AssertionError(f"missing pattern binding for {pattern.name!r}")
        return replace(
            pattern,
            type_ref=_rename_type(pattern.type_ref, type_bindings),
            binding=binding,
        )
    if isinstance(pattern, PatternLiteralIR):
        return replace(
            pattern,
            type_ref=_rename_type(pattern.type_ref, type_bindings),
        )
    if isinstance(pattern, PatternTupleIR):
        return replace(
            pattern,
            items=tuple(
                _bind_pattern(value, local_bindings, type_bindings)
                for value in pattern.items
            ),
        )
    if isinstance(pattern, PatternConstructorIR):
        return replace(
            pattern,
            items=tuple(
                _bind_pattern(value, local_bindings, type_bindings)
                for value in pattern.items
            ),
            fields=tuple(
                replace(
                    field,
                    pattern=_bind_pattern(
                        field.pattern,
                        local_bindings,
                        type_bindings,
                    ),
                )
                for field in pattern.fields
            ),
        )
    if isinstance(pattern, PatternOrIR):
        return replace(
            pattern,
            alternatives=tuple(
                _bind_pattern(value, local_bindings, type_bindings)
                for value in pattern.alternatives
            ),
        )
    if isinstance(pattern, PatternRangeIR):
        return replace(
            pattern,
            low=_bind_pattern(pattern.low, local_bindings, type_bindings),
            high=_bind_pattern(pattern.high, local_bindings, type_bindings),
        )
    if isinstance(pattern, PatternAtIR):
        capture = _bind_pattern(pattern.capture, local_bindings, type_bindings)
        assert isinstance(capture, PatternCaptureIR)
        return replace(
            pattern,
            capture=capture,
            pattern=_bind_pattern(pattern.pattern, local_bindings, type_bindings),
        )
    if isinstance(pattern, (PatternWildcardIR, PatternRestIR)):
        return pattern
    raise AssertionError(f"unhandled pattern IR: {type(pattern).__name__}")


def _bind_expression(
    expression: ExpressionIR,
    environment: dict[str, BindingIR],
    type_bindings: dict[str, BindingIR],
    gensym: Gensym,
) -> ExpressionIR:
    if isinstance(expression, NameIR):
        return replace(
            expression,
            type_ref=_rename_type(expression.type_ref, type_bindings),
            binding=environment.get(expression.name),
        )
    if isinstance(expression, ClosureIR):
        closure_environment = dict(environment)
        parameter_binding = None
        second_parameter_binding = None
        if expression.parameter is not None:
            parameter_binding = gensym.bind(expression.parameter, expression.span)
            closure_environment[expression.parameter] = parameter_binding
        if expression.second_parameter is not None:
            second_parameter_binding = gensym.bind(
                expression.second_parameter,
                expression.span,
            )
            closure_environment[expression.second_parameter] = second_parameter_binding
        return replace(
            expression,
            parameter_type=_rename_type(expression.parameter_type, type_bindings),
            second_parameter_type=(
                _rename_type(expression.second_parameter_type, type_bindings)
                if expression.second_parameter_type is not None
                else None
            ),
            body=_bind_expression(
                expression.body, closure_environment, type_bindings, gensym
            ),
            type_ref=_rename_type(expression.type_ref, type_bindings),
            parameter_binding=parameter_binding,
            second_parameter_binding=second_parameter_binding,
        )
    return cast(
        ExpressionIR,
        _rewrite_fields(expression, environment, type_bindings, gensym),
    )


def _rewrite_dataclass(
    value: Any,
    environment: dict[str, BindingIR],
    type_bindings: dict[str, BindingIR],
    gensym: Gensym,
) -> Any:
    if isinstance(value, TypeRef):
        return _rename_type(value, type_bindings)
    if isinstance(value, _EXPRESSION_CLASSES):
        return _bind_expression(value, environment, type_bindings, gensym)
    if isinstance(value, tuple):
        return tuple(
            _rewrite_dataclass(item, environment, type_bindings, gensym)
            for item in value
        )
    if not is_dataclass(value):
        return value
    return _rewrite_fields(value, environment, type_bindings, gensym)


def _rewrite_fields(
    value: Any,
    environment: dict[str, BindingIR],
    type_bindings: dict[str, BindingIR],
    gensym: Gensym,
) -> Any:
    updates: dict[str, Any] = {}
    for field in fields(value):
        current = getattr(value, field.name)
        rewritten = _rewrite_dataclass(current, environment, type_bindings, gensym)
        if rewritten is not current:
            updates[field.name] = rewritten
    return replace(value, **updates) if updates else value


def _loop_names(variable: str) -> tuple[str, ...]:
    if variable.startswith("(") and variable.endswith(")"):
        return tuple(value.strip() for value in variable[1:-1].split(","))
    return (variable,)
