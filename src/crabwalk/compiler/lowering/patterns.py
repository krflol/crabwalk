"""Typed match-pattern lowering from Python AST into Rust-pattern IR."""

from __future__ import annotations

import ast
from pathlib import Path

from crabwalk.diagnostics import SourceSpan

from ..ir import (
    BOOL,
    CHAR,
    EnumIR,
    EnumVariantIR,
    ExpressionIR,
    PatternMatchArmIR,
    PatternMatchIR,
    StatementIR,
    StructFieldIR,
    StructIR,
    TypeRef,
)
from ..source import attribute_parts
from .common import fail, unsupported, validate_source_binding, validate_unicode_text
from .expressions import integer_fits


class PatternLoweringMixin:
    """The pattern phase, mixed into the stateful function lowerer.

    The frontend supplies symbol tables plus expression/block lowering. Keeping
    this phase separate makes its accepted AST forms and diagnostics directly
    testable without coupling them to declaration discovery or Rust emission.
    """

    path: Path
    parameter_ownership: dict[str, str | None]
    enums_by_symbol: dict[str, EnumIR]
    domain_enums: dict[str, EnumIR]
    structs_by_symbol: dict[str, StructIR]
    domain_structs: dict[str, StructIR]

    def _lower_expression(
        self,
        node: ast.expr,
        environment: dict[str, TypeRef],
        expected: TypeRef | None = None,
    ) -> ExpressionIR:
        raise NotImplementedError

    def _lower_block(
        self,
        nodes: list[ast.stmt],
        environment: dict[str, TypeRef],
    ) -> tuple[StatementIR, ...]:
        raise NotImplementedError

    def _lower_match(
        self,
        node: ast.Match,
        environment: dict[str, TypeRef],
    ) -> PatternMatchIR:
        subject = self._lower_expression(node.subject, environment)
        arms: list[PatternMatchArmIR] = []
        for case in node.cases:
            pattern, bindings = self._lower_general_pattern(
                case.pattern,
                subject.type_ref,
            )
            arm_environment = dict(environment)
            arm_environment.update(bindings)
            guard = (
                self._lower_expression(case.guard, arm_environment, BOOL)
                if case.guard is not None
                else None
            )
            body = self._lower_block(case.body, arm_environment)
            arms.append(
                PatternMatchArmIR(
                    pattern,
                    tuple(bindings.items()),
                    guard,
                    body,
                    SourceSpan.from_ast(self.path, case.pattern),
                )
            )
        borrowed = isinstance(node.subject, ast.Name) and self.parameter_ownership.get(
            node.subject.id
        ) in {"Ref", "Mut"}
        return PatternMatchIR(
            subject,
            subject.type_ref,
            borrowed,
            tuple(arms),
            SourceSpan.from_ast(self.path, node),
        )

    def _lower_general_pattern(
        self,
        pattern: ast.pattern,
        expected: TypeRef,
    ) -> tuple[str, dict[str, TypeRef]]:
        if isinstance(pattern, ast.MatchAs):
            if pattern.name is not None:
                validate_source_binding(
                    pattern.name,
                    self.path,
                    pattern,
                    "pattern binding",
                )
            if pattern.pattern is None:
                if pattern.name is None:
                    return "_", {}
                return pattern.name, {pattern.name: expected}
            rendered, bindings = self._lower_general_pattern(pattern.pattern, expected)
            if pattern.name is None:
                return rendered, bindings
            if pattern.name in bindings:
                fail(
                    "CRAB192",
                    "Duplicate pattern binding",
                    f"'{pattern.name}' is bound more than once.",
                    self.path,
                    pattern,
                )
            return f"{pattern.name} @ ({rendered})", {
                **bindings,
                pattern.name: expected,
            }

        if isinstance(pattern, ast.MatchOr):
            lowered = [
                self._lower_general_pattern(value, expected)
                for value in pattern.patterns
            ]
            first_bindings = lowered[0][1]
            if any(bindings != first_bindings for _, bindings in lowered[1:]):
                fail(
                    "CRAB192",
                    "Or-pattern bindings differ",
                    "Every side of a Rust or-pattern must bind the same names and types.",
                    self.path,
                    pattern,
                )
            return " | ".join(value for value, _ in lowered), first_bindings

        if isinstance(pattern, ast.MatchSingleton):
            if pattern.value is None and expected.rust_name == "Option":
                return "std::option::Option::None", {}
            if isinstance(pattern.value, bool) and expected == BOOL:
                return ("true" if pattern.value else "false"), {}
            unsupported(
                pattern,
                self.path,
                "This singleton pattern does not match the subject type.",
            )

        if isinstance(pattern, ast.MatchValue):
            if isinstance(pattern.value, ast.Constant):
                return self._render_pattern_literal(
                    pattern.value.value,
                    expected,
                    pattern,
                ), {}
            if (
                isinstance(pattern.value, ast.UnaryOp)
                and isinstance(pattern.value.op, ast.USub)
                and isinstance(pattern.value.operand, ast.Constant)
            ):
                value = pattern.value.operand.value
                if type(value) is int and expected.is_signed_integer:
                    return str(-value), {}
            enum = self.enums_by_symbol.get(expected.rust_name)
            if enum is not None:
                variant = self._enum_pattern_variant(
                    attribute_parts(pattern.value),
                    enum,
                    pattern,
                )
                if variant.fields:
                    fail(
                        "CRAB192",
                        "Payload enum variant needs a class pattern",
                        f"Match {variant.name} with its payload fields.",
                        self.path,
                        pattern,
                    )
                return f"{enum.symbol}::{variant.rust_name}", {}
            unsupported(
                pattern,
                self.path,
                "Use a literal or a visible unit enum variant.",
            )

        if isinstance(pattern, ast.MatchSequence):
            if expected.rust_name != "Tuple":
                fail(
                    "CRAB192",
                    "Sequence pattern requires a Rust tuple",
                    f"Found {expected.display()}.",
                    self.path,
                    pattern,
                )
            stars = [
                index
                for index, value in enumerate(pattern.patterns)
                if isinstance(value, ast.MatchStar)
            ]
            if len(stars) > 1:
                unsupported(
                    pattern,
                    self.path,
                    "A tuple pattern can contain one rest pattern.",
                )
            if not stars and len(pattern.patterns) != len(expected.arguments):
                fail(
                    "CRAB192",
                    "Tuple pattern length mismatch",
                    f"Expected {len(expected.arguments)} elements.",
                    self.path,
                    pattern,
                )
            if stars and len(pattern.patterns) - 1 > len(expected.arguments):
                fail(
                    "CRAB192",
                    "Tuple rest pattern is too long",
                    f"The subject has {len(expected.arguments)} elements.",
                    self.path,
                    pattern,
                )
            rendered_values: list[str] = []
            tuple_bindings: dict[str, TypeRef] = {}
            star_index = stars[0] if stars else None
            for index, child in enumerate(pattern.patterns):
                if isinstance(child, ast.MatchStar):
                    if child.name is not None:
                        unsupported(
                            child,
                            self.path,
                            "Named tuple rest bindings are deferred.",
                        )
                    rendered_values.append("..")
                    continue
                type_index = (
                    index
                    if star_index is None or index < star_index
                    else len(expected.arguments) - (len(pattern.patterns) - index)
                )
                rendered, child_bindings = self._lower_general_pattern(
                    child,
                    expected.arguments[type_index],
                )
                self._merge_pattern_bindings(
                    tuple_bindings,
                    child_bindings,
                    child,
                )
                rendered_values.append(rendered)
            values = ", ".join(rendered_values)
            return (
                f"({values}{',' if len(rendered_values) == 1 else ''})",
                tuple_bindings,
            )

        if isinstance(pattern, ast.MatchClass):
            path = attribute_parts(pattern.cls)
            if path == ("rust", "Range"):
                if pattern.kwd_patterns or len(pattern.patterns) != 2:
                    unsupported(
                        pattern,
                        self.path,
                        "rust.Range needs two positional literals.",
                    )
                low, low_bindings = self._lower_general_pattern(
                    pattern.patterns[0], expected
                )
                high, high_bindings = self._lower_general_pattern(
                    pattern.patterns[1], expected
                )
                if low_bindings or high_bindings:
                    unsupported(
                        pattern,
                        self.path,
                        "Range endpoints must be literals.",
                    )
                return f"{low}..={high}", {}

            if expected.rust_name == "Option" and path == ("rust", "Some"):
                if pattern.kwd_patterns or len(pattern.patterns) != 1:
                    unsupported(
                        pattern,
                        self.path,
                        "rust.Some patterns take one payload.",
                    )
                rendered, bindings = self._lower_general_pattern(
                    pattern.patterns[0],
                    expected.arguments[0],
                )
                return f"std::option::Option::Some({rendered})", bindings

            if expected.rust_name == "Result" and path in {
                ("rust", "Ok"),
                ("rust", "Err"),
            }:
                if pattern.kwd_patterns or len(pattern.patterns) != 1:
                    unsupported(
                        pattern,
                        self.path,
                        "rust.Ok and rust.Err patterns take one payload.",
                    )
                index = 0 if path == ("rust", "Ok") else 1
                rendered, bindings = self._lower_general_pattern(
                    pattern.patterns[0],
                    expected.arguments[index],
                )
                constructor = "Ok" if index == 0 else "Err"
                return f"std::result::Result::{constructor}({rendered})", bindings

            enum = self.enums_by_symbol.get(expected.rust_name)
            if enum is not None:
                variant = self._enum_pattern_variant(path, enum, pattern)
                return self._lower_domain_pattern(
                    pattern,
                    f"{enum.symbol}::{variant.rust_name}",
                    variant.fields,
                    variant.tuple_style,
                )

            struct = self.structs_by_symbol.get(expected.rust_name)
            visible_struct = self.domain_structs.get(".".join(path))
            if (
                struct is not None
                and visible_struct is not None
                and visible_struct.symbol == struct.symbol
            ):
                return self._lower_domain_pattern(
                    pattern,
                    struct.symbol,
                    struct.fields,
                    False,
                )
            unsupported(
                pattern,
                self.path,
                "Use a matching struct, enum, Option, Result, or rust.Range pattern.",
            )

        unsupported(
            pattern,
            self.path,
            "This Python pattern has no Crabwalk Rust lowering yet.",
        )

    def _lower_domain_pattern(
        self,
        pattern: ast.MatchClass,
        rust_path: str,
        fields: tuple[StructFieldIR, ...],
        tuple_style: bool,
    ) -> tuple[str, dict[str, TypeRef]]:
        bindings: dict[str, TypeRef] = {}
        if tuple_style:
            if pattern.kwd_patterns or len(pattern.patterns) != len(fields):
                fail(
                    "CRAB192",
                    "Tuple-style pattern shape mismatch",
                    f"{rust_path} has {len(fields)} positional fields.",
                    self.path,
                    pattern,
                )
            rendered_values: list[str] = []
            for child, field in zip(pattern.patterns, fields):
                rendered, child_bindings = self._lower_general_pattern(
                    child,
                    field.type_ref,
                )
                self._merge_pattern_bindings(bindings, child_bindings, child)
                rendered_values.append(rendered)
            return f"{rust_path}({', '.join(rendered_values)})", bindings

        if pattern.patterns or len(set(pattern.kwd_attrs)) != len(pattern.kwd_attrs):
            unsupported(pattern, self.path, "Record patterns use unique named fields.")
        fields_by_name = {field.name: field for field in fields}
        if any(name not in fields_by_name for name in pattern.kwd_attrs):
            fail(
                "CRAB192",
                "Unknown record pattern field",
                f"{rust_path} fields: {', '.join(fields_by_name)}.",
                self.path,
                pattern,
            )
        rendered_fields: list[str] = []
        for name, child in zip(pattern.kwd_attrs, pattern.kwd_patterns):
            rendered, child_bindings = self._lower_general_pattern(
                child,
                fields_by_name[name].type_ref,
            )
            self._merge_pattern_bindings(bindings, child_bindings, child)
            rendered_fields.append(f"{fields_by_name[name].rust_name}: {rendered}")
        if len(rendered_fields) < len(fields):
            rendered_fields.append("..")
        return f"{rust_path} {{ {', '.join(rendered_fields)} }}", bindings

    def _merge_pattern_bindings(
        self,
        destination: dict[str, TypeRef],
        incoming: dict[str, TypeRef],
        node: ast.AST,
    ) -> None:
        duplicate = destination.keys() & incoming.keys()
        if duplicate:
            fail(
                "CRAB192",
                "Duplicate pattern binding",
                f"Bound more than once: {', '.join(sorted(duplicate))}.",
                self.path,
                node,
            )
        destination.update(incoming)

    def _render_pattern_literal(
        self,
        value: object,
        expected: TypeRef,
        node: ast.AST,
    ) -> str:
        if isinstance(value, str):
            validate_unicode_text(value, self.path, node)
        if type(value) is int and expected.is_integer:
            if not integer_fits(int(value), expected):
                fail(
                    "CRAB111",
                    f"Integer does not fit {expected.display()}",
                    f"The pattern literal {value!r} is out of range.",
                    self.path,
                    node,
                )
            return str(value)
        if isinstance(value, str) and expected == CHAR and len(value) == 1:
            return rust_pattern_char(value)
        if isinstance(value, bool) and expected == BOOL:
            return "true" if value else "false"
        fail(
            "CRAB192",
            "Pattern literal type mismatch",
            f"{value!r} cannot pattern-match {expected.display()}.",
            self.path,
            node,
        )

    def _enum_pattern_variant(
        self,
        path: tuple[str, ...],
        enum: EnumIR,
        node: ast.AST,
    ) -> EnumVariantIR:
        if len(path) < 2:
            unsupported(node, self.path, "Enum patterns must be Type.Variant.")
        visible = self.domain_enums.get(".".join(path[:-1]))
        variant = (
            next((value for value in enum.variants if value.name == path[-1]), None)
            if visible is not None and visible.symbol == enum.symbol
            else None
        )
        if variant is None:
            fail(
                "CRAB169",
                "Pattern variant does not belong to subject enum",
                ".".join(path),
                self.path,
                node,
            )
        return variant


def rust_pattern_char(value: str) -> str:
    """Render one validated Python character as a Rust pattern literal."""

    character = value[0]
    escapes = {
        "'": "\\'",
        "\\": "\\\\",
        "\n": "\\n",
        "\r": "\\r",
        "\t": "\\t",
        "\0": "\\0",
    }
    escaped = escapes.get(character)
    if escaped is None:
        code = ord(character)
        escaped = f"\\u{{{code:x}}}" if code < 0x20 or code == 0x7F else character
    return f"'{escaped}'"
