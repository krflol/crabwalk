"""Deterministic Rust emission for typed native function bodies."""

from __future__ import annotations

from .emission import EmissionNames, Writer
from .ir import (
    ArrayLiteralIR,
    AssignIR,
    AwaitIR,
    BinaryIR,
    BoolLiteralIR,
    BorrowIR,
    BreakIR,
    CallIR,
    ClosureIR,
    CompareIR,
    ConstructorIR,
    ContinueIR,
    CrateCallIR,
    DestructureIR,
    EnumConstructorIR,
    ExpressionIR,
    ExpressionStatementIR,
    FieldAccessIR,
    FieldAssignIR,
    FloatLiteralIR,
    ForEachIR,
    ForRangeIR,
    FunctionIR,
    FunctionPointerTwiceIR,
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
    PassIR,
    PatternAtIR,
    PatternCaptureIR,
    PatternConstructorIR,
    PatternIR,
    PatternLiteralIR,
    PatternMatchIR,
    PatternOrIR,
    PatternRangeIR,
    PatternRestIR,
    PatternTupleIR,
    PatternWildcardIR,
    PythonPrintIR,
    ReturnIR,
    STR,
    StatementIR,
    StringLiteralIR,
    StructConstructorIR,
    TraitCallIR,
    TryIR,
    TupleLiteralIR,
    TypeRef,
    UnaryIR,
    WhileIR,
)

_Writer = Writer


def write_native_function(
    writer: _Writer,
    function: FunctionIR,
    boundary_names: set[str],
) -> None:
    emission_names = EmissionNames.for_function(function)
    parameters = ", ".join(
        (
            f"mut {parameter.rust_name}: {parameter.type_ref.render()}"
            if parameter.mutable
            else f"{parameter.rust_name}: {parameter.type_ref.render()}"
        )
        for parameter in function.parameters
    )
    native_return = (
        f"PyResult<{function.return_type.render()}>"
        if function.python_boundary
        else function.return_type.render()
    )
    generic_parameters = ""
    if function.type_parameters:
        rendered = []
        for parameter in function.type_parameters:
            if parameter.is_lifetime:
                rendered.append(f"'{parameter.rust_name}")
            else:
                qualified_bounds = tuple(
                    {
                        "Clone": "std::clone::Clone",
                        "Copy": "std::marker::Copy",
                        "Debug": "std::fmt::Debug",
                        "Display": "std::fmt::Display",
                        "Ord": "std::cmp::Ord",
                        "PartialOrd": "std::cmp::PartialOrd",
                    }.get(value, value)
                    for value in parameter.bounds
                )
                bounds = f": {' + '.join(qualified_bounds)}" if qualified_bounds else ""
                rendered.append(f"{parameter.rust_name}{bounds}")
        generic_parameters = f"<{', '.join(rendered)}>"
    writer.line(
        (
            f"{'async ' if function.is_async else ''}fn "
            f"__cw_native_{function.rust_symbol}{generic_parameters}"
            f"({parameters}) -> {native_return} {{"
        ),
        function.span,
        "function",
    )
    writer.enter()
    for statement in function.body:
        _write_statement(
            writer,
            statement,
            boundary_names,
            function.python_boundary,
            emission_names,
        )
    if function.return_type.rust_name == "Unit" and not _ends_with_return(
        function.body
    ):
        writer.line(
            "std::result::Result::Ok(())" if function.python_boundary else "()",
            function.span,
            "implicit_unit_return",
        )
    writer.leave()
    writer.line("}")


def _write_statement(
    writer: _Writer,
    statement: StatementIR,
    boundary_names: set[str],
    current_boundary: bool,
    emission_names: EmissionNames,
) -> None:
    if isinstance(statement, ReturnIR):
        if current_boundary:
            value = (
                "return std::result::Result::Ok(());"
                if statement.value is None
                else (
                    "return std::result::Result::Ok("
                    f"{_render_expression(statement.value, boundary_names, emission_names)});"
                )
            )
        else:
            value = (
                "return;"
                if statement.value is None
                else (
                    "return "
                    f"{_render_expression(statement.value, boundary_names, emission_names)};"
                )
            )
        writer.line(value, statement.span, "return")
        return
    if isinstance(statement, LetIR):
        mutability = "mut " if statement.mutable else ""
        annotation = (
            f": {statement.rust_annotation.render()}"
            if statement.rust_annotation is not None
            else ""
        )
        writer.line(
            (
                f"let {mutability}{statement.rust_name}{annotation} "
                f"= {_render_expression(statement.value, boundary_names, emission_names)};"
            ),
            statement.span,
            "let",
        )
        return
    if isinstance(statement, AssignIR):
        writer.line(
            (
                f"{statement.rust_name} = "
                f"{_render_expression(statement.value, boundary_names, emission_names)};"
            ),
            statement.span,
            "assign",
        )
        return
    if isinstance(statement, FieldAssignIR):
        writer.line(
            (
                f"{_render_place_expression(statement.receiver, boundary_names, emission_names)}."
                f"{statement.field} = "
                f"{_render_expression(statement.value, boundary_names, emission_names)};"
            ),
            statement.span,
            "field_assign",
        )
        return
    if isinstance(statement, DestructureIR):
        names = ", ".join(
            f"mut {name}" if mutable else name
            for name, mutable in zip(statement.rust_names, statement.mutable)
        )
        writer.line(
            (
                f"let ({names}): {statement.type_ref.render()} = "
                f"{_render_expression(statement.value, boundary_names, emission_names)};"
            ),
            statement.span,
            "tuple_destructure",
        )
        return
    if isinstance(statement, LocalConstIR):
        writer.line(
            (
                f"const {statement.rust_name}: {statement.type_ref.render()} = "
                f"{_render_expression(statement.value, boundary_names, emission_names)};"
            ),
            statement.span,
            "local_const",
        )
        return
    if isinstance(statement, ExpressionStatementIR):
        writer.line(
            f"{_render_expression(statement.value, boundary_names, emission_names)};",
            statement.span,
            "expression_statement",
        )
        return
    if isinstance(statement, IfIR):
        writer.line(
            f"if {_render_expression(statement.condition, boundary_names, emission_names)} {{",
            statement.condition.span,
            "if_condition",
        )
        writer.enter()
        for child in statement.body:
            _write_statement(
                writer, child, boundary_names, current_boundary, emission_names
            )
        writer.leave()
        if statement.otherwise:
            writer.line("} else {", statement.span, "else")
            writer.enter()
            for child in statement.otherwise:
                _write_statement(
                    writer, child, boundary_names, current_boundary, emission_names
                )
            writer.leave()
        writer.line("}")
        return
    if isinstance(statement, WhileIR):
        writer.line(
            f"while {_render_expression(statement.condition, boundary_names, emission_names)} {{",
            statement.condition.span,
            "while_condition",
        )
        writer.enter()
        for child in statement.body:
            _write_statement(
                writer, child, boundary_names, current_boundary, emission_names
            )
        writer.leave()
        writer.line("}")
        return
    if isinstance(statement, ForRangeIR):
        writer.line(
            (
                f"for {statement.rust_variable} in "
                f"{_render_expression(statement.start, boundary_names, emission_names)}.."
                f"{_render_expression(statement.stop, boundary_names, emission_names)} {{"
            ),
            statement.span,
            "for_range",
        )
        writer.enter()
        for child in statement.body:
            _write_statement(
                writer, child, boundary_names, current_boundary, emission_names
            )
        writer.leave()
        writer.line("}")
        return
    if isinstance(statement, ForEachIR):
        writer.line(
            (
                f"for {statement.rust_variable} in "
                f"{_render_expression(statement.iterator, boundary_names, emission_names)} {{"
            ),
            statement.span,
            "for_each",
        )
        writer.enter()
        for child in statement.body:
            _write_statement(
                writer, child, boundary_names, current_boundary, emission_names
            )
        writer.leave()
        writer.line("}")
        return
    if isinstance(statement, MatchIR):
        subject = _render_expression(statement.subject, boundary_names, emission_names)
        borrowed = subject if statement.subject_borrowed else f"&{subject}"
        writer.line(
            f"match <{statement.enum_symbol} as std::clone::Clone>::clone({borrowed}) {{",
            statement.span,
            "match",
        )
        writer.enter()
        for match_arm in statement.arms:
            if match_arm.variant is None:
                pattern = "_"
            elif not match_arm.bindings:
                pattern = f"{match_arm.enum_symbol}::{match_arm.variant}"
            elif match_arm.tuple_style:
                values = ", ".join(local or "_" for _, local in match_arm.bindings)
                pattern = f"{match_arm.enum_symbol}::{match_arm.variant}({values})"
            else:
                values = ", ".join(
                    f"{field}: {local or '_'}" for field, local in match_arm.bindings
                )
                pattern = f"{match_arm.enum_symbol}::{match_arm.variant} {{ {values} }}"
            writer.line(f"{pattern} => {{", match_arm.span, "match_arm")
            writer.enter()
            for child in match_arm.body:
                _write_statement(
                    writer, child, boundary_names, current_boundary, emission_names
                )
            writer.leave()
            writer.line("},")
        writer.leave()
        writer.line("}")
        return
    if isinstance(statement, PatternMatchIR):
        subject = _render_expression(statement.subject, boundary_names, emission_names)
        borrowed = subject if statement.subject_borrowed else f"&{subject}"
        subject_type = statement.subject_type.render()
        writer.line(
            f"match <{subject_type} as std::clone::Clone>::clone({borrowed}) {{",
            statement.span,
            "pattern_match",
        )
        writer.enter()
        for pattern_arm in statement.arms:
            guard = (
                ""
                if pattern_arm.guard is None
                else (
                    " if "
                    f"{_render_expression(pattern_arm.guard, boundary_names, emission_names)}"
                )
            )
            writer.line(
                f"{_render_pattern(pattern_arm.pattern)}{guard} => {{",
                pattern_arm.span,
                "pattern_match_arm",
            )
            writer.enter()
            for child in pattern_arm.body:
                _write_statement(
                    writer, child, boundary_names, current_boundary, emission_names
                )
            writer.leave()
            writer.line("},")
        writer.leave()
        writer.line("}")
        return
    if isinstance(statement, BreakIR):
        writer.line("break;", statement.span, "break")
        return
    if isinstance(statement, ContinueIR):
        writer.line("continue;", statement.span, "continue")
        return
    if isinstance(statement, PassIR):
        writer.line("();", statement.span, "pass")
        return
    raise AssertionError(f"unhandled statement IR: {type(statement).__name__}")


def _render_pattern(pattern: PatternIR) -> str:
    """Render semantic pattern nodes after capture identities are assigned."""

    if isinstance(pattern, PatternWildcardIR):
        return "_"
    if isinstance(pattern, PatternCaptureIR):
        return pattern.rust_name
    if isinstance(pattern, PatternLiteralIR):
        if isinstance(pattern.value, bool):
            return "true" if pattern.value else "false"
        if isinstance(pattern.value, int):
            return str(pattern.value)
        return _rust_char_literal(pattern.value)
    if isinstance(pattern, PatternRestIR):
        return ".."
    if isinstance(pattern, PatternTupleIR):
        values = ", ".join(_render_pattern(value) for value in pattern.items)
        suffix = "," if len(pattern.items) == 1 else ""
        return f"({values}{suffix})"
    if isinstance(pattern, PatternConstructorIR):
        if pattern.style == "unit":
            return pattern.rust_path
        if pattern.style == "tuple":
            values = ", ".join(_render_pattern(value) for value in pattern.items)
            return f"{pattern.rust_path}({values})"
        fields = [
            f"{field.rust_name}: {_render_pattern(field.pattern)}"
            for field in pattern.fields
        ]
        if pattern.record_rest:
            fields.append("..")
        return f"{pattern.rust_path} {{ {', '.join(fields)} }}"
    if isinstance(pattern, PatternOrIR):
        return " | ".join(_render_pattern(value) for value in pattern.alternatives)
    if isinstance(pattern, PatternRangeIR):
        return f"{_render_pattern(pattern.low)}..={_render_pattern(pattern.high)}"
    if isinstance(pattern, PatternAtIR):
        return (
            f"{_render_pattern(pattern.capture)} @ ({_render_pattern(pattern.pattern)})"
        )
    raise AssertionError(f"unhandled pattern IR: {type(pattern).__name__}")


def _render_expression(
    expression: ExpressionIR,
    boundary_names: set[str] | None = None,
    emission_names: EmissionNames | None = None,
) -> str:
    boundary_names = boundary_names or set()
    emission_names = emission_names or EmissionNames.empty()
    if isinstance(expression, IntLiteralIR):
        return f"{expression.value}{expression.type_ref.render()}"
    if isinstance(expression, FloatLiteralIR):
        value = repr(expression.value)
        if "." not in value and "e" not in value.lower():
            value += ".0"
        return f"{value}{expression.type_ref.render()}"
    if isinstance(expression, BoolLiteralIR):
        return "true" if expression.value else "false"
    if isinstance(expression, StringLiteralIR):
        if expression.type_ref.rust_name == "char":
            return _rust_char_literal(expression.value)
        literal = _rust_string_literal(expression.value)
        return (
            f"String::from({literal})"
            if expression.type_ref.rust_name == "String"
            else literal
        )
    if isinstance(expression, TupleLiteralIR):
        values = ", ".join(
            _render_expression(value, boundary_names, emission_names)
            for value in expression.values
        )
        return f"({values}{',' if len(expression.values) == 1 else ''})"
    if isinstance(expression, ArrayLiteralIR):
        values = ", ".join(
            _render_expression(value, boundary_names, emission_names)
            for value in expression.values
        )
        return f"[{values}]"
    if isinstance(expression, IndexIR):
        receiver = _render_expression(
            expression.receiver, boundary_names, emission_names
        )
        if expression.receiver.type_ref.rust_name == "Tuple" and isinstance(
            expression.index, IntLiteralIR
        ):
            rendered = f"{receiver}.{expression.index.value}"
        elif expression.receiver.type_ref.rust_name == "Buffer":
            rendered = (
                f"{receiver}.get("
                f"{_render_expression(expression.index, boundary_names, emission_names)})"
            )
        else:
            rendered = f"{receiver}[{_render_expression(expression.index, boundary_names, emission_names)}]"
        return rendered if _is_copy_type(expression.type_ref) else f"{rendered}.clone()"
    if isinstance(expression, NoneLiteralIR):
        return "()"
    if isinstance(expression, NameIR):
        return expression.rust_name
    if isinstance(expression, BorrowIR):
        operator = "&mut " if expression.kind == "mutable" else "&"
        return (
            f"{operator}"
            f"{_render_place_expression(expression.value, boundary_names, emission_names)}"
        )
    if isinstance(expression, UnaryIR):
        operator = {"positive": "+", "negative": "-", "not": "!"}[expression.operator]
        return (
            f"({operator}"
            f"{_render_expression(expression.operand, boundary_names, emission_names)})"
        )
    if isinstance(expression, BinaryIR):
        operator = {
            "add": "+",
            "subtract": "-",
            "multiply": "*",
            "divide": "/",
            "remainder": "%",
            "and": "&&",
            "or": "||",
        }[expression.operator]
        return (
            f"({_render_expression(expression.left, boundary_names, emission_names)} "
            f"{operator} "
            f"{_render_expression(expression.right, boundary_names, emission_names)})"
        )
    if isinstance(expression, CompareIR):
        operator = {
            "eq": "==",
            "not_eq": "!=",
            "lt": "<",
            "lt_eq": "<=",
            "gt": ">",
            "gt_eq": ">=",
        }[expression.operator]
        return (
            f"({_render_expression(expression.left, boundary_names, emission_names)} "
            f"{operator} "
            f"{_render_expression(expression.right, boundary_names, emission_names)})"
        )
    if isinstance(expression, CallIR):
        arguments = ", ".join(
            _render_expression(value, boundary_names, emission_names)
            for value in expression.arguments
        )
        suffix = "?" if expression.target in boundary_names else ""
        return f"__cw_native_{expression.target}({arguments}){suffix}"
    if isinstance(expression, CrateCallIR):
        arguments = ", ".join(
            _render_expression(value, boundary_names, emission_names)
            for value in expression.arguments
        )
        return f"{'::'.join(expression.path)}({arguments})"
    if isinstance(expression, ConstructorIR):
        values = ", ".join(
            _render_expression(value, boundary_names, emission_names)
            for value in expression.arguments
        )
        if expression.constructor == "String":
            return f"String::from({values})"
        if expression.constructor == "Vec":
            return f"vec![{values}]"
        if expression.constructor == "HashMap":
            return "std::collections::HashMap::new()"
        if expression.constructor == "Box":
            return f"Box::new({values})"
        if expression.constructor == "Rc":
            return f"std::rc::Rc::new({values})"
        if expression.constructor == "RefCell":
            return f"std::cell::RefCell::new({values})"
        if expression.constructor == "Arc":
            return f"std::sync::Arc::new({values})"
        if expression.constructor == "Mutex":
            return f"std::sync::Mutex::new({values})"
        if expression.constructor == "Channel":
            message_type = expression.type_ref.arguments[0].arguments[0].render()
            return f"std::sync::mpsc::channel::<{message_type}>()"
        if expression.constructor == "Spawn":
            return f"std::thread::spawn({values})"
        if expression.constructor == "BlockOn":
            return f"__cw_block_on({values})"
        if expression.constructor == "Join":
            return f"__cw_join2({values})"
        if expression.constructor == "Select":
            return f"__cw_select2({values})"
        if expression.constructor == "YieldNow":
            return "__cw_yield_now()"
        if expression.constructor == "SleepMillis":
            return f"__cw_sleep_millis({values})"
        if expression.constructor == "DynBox":
            return f"Box::new({values}) as {expression.type_ref.render()}"
        if expression.constructor == "ArrayRepeat":
            return f"[{values}; {expression.type_ref.const_value}]"
        if expression.constructor == "Some":
            return f"std::option::Option::Some({values})"
        if expression.constructor == "None":
            return "std::option::Option::None"
        if expression.constructor == "Ok":
            return f"std::result::Result::Ok({values})"
        if expression.constructor == "Err":
            return f"std::result::Result::Err({values})"
        if expression.constructor == "UnsafeRead":
            value = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            pointer = emission_names.temporary("pointer")
            return f"{{ let {pointer} = &raw const {value}; unsafe {{ *{pointer} }} }}"
        if expression.constructor == "UnsafeWrite":
            target = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            value = _render_expression(
                expression.arguments[1], boundary_names, emission_names
            )
            pointer = emission_names.temporary("pointer")
            return (
                f"{{ let {pointer} = &raw mut "
                f"{target}; unsafe {{ *{pointer} = {value}; }} }}"
            )
        if expression.constructor == "CAbs":
            value = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            checked_value = emission_names.temporary("c_abs_value")
            return (
                f"{{ let {checked_value}: i32 = "
                f"{value}; if {checked_value} == i32::MIN {{ "
                'panic!("C abs is undefined for i32::MIN"); } '
                f"unsafe {{ __crabwalk_ffi::c_abs({checked_value}) }} }}"
            )
        if expression.constructor == "UnsafeStaticIncrement":
            value = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            counter = emission_names.temporary("static_counter")
            amount = emission_names.temporary("increment_amount")
            previous = emission_names.temporary("previous_counter")
            current = emission_names.temporary("current_counter")
            return (
                f"{{ static {counter}: std::sync::atomic::AtomicU64 = "
                "std::sync::atomic::AtomicU64::new(0); "
                f"let {amount}: u64 = {value}; "
                f"let {previous} = {counter}.fetch_update("
                "std::sync::atomic::Ordering::Relaxed, "
                "std::sync::atomic::Ordering::Relaxed, "
                f"|{current}| {current}.checked_add({amount}))"
                '.expect("unsafe static counter overflow"); '
                f"{previous}.checked_add({amount})"
                '.expect("unsafe static counter overflow") }'
            )
        if expression.constructor == "TypeAliasIdentity":
            value = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            type_name = expression.type_ref.render()
            alias = emission_names.type_item("alias")
            alias_value = emission_names.temporary("alias_value")
            return (
                f"{{ type {alias} = {type_name}; "
                f"let {alias_value}: {alias} = {value}; {alias_value} }}"
            )
        if expression.constructor == "BoxedClosureCall":
            value = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            addend = _render_expression(
                expression.arguments[1], boundary_names, emission_names
            )
            helper = emission_names.temporary("returns_closure")
            helper_addend = emission_names.temporary("closure_addend")
            helper_value = emission_names.temporary("closure_value")
            return (
                f"{{ fn {helper}({helper_addend}: u64) -> "
                "Box<dyn Fn(u64) -> u64> { "
                f"Box::new(move |{helper_value}| {helper_value} + {helper_addend}) }} "
                f"{helper}({addend})({value}) }}"
            )
        if expression.constructor == "ClosureVectorTotal":
            value = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            callbacks = emission_names.temporary("callbacks")
            first_item = emission_names.temporary("first_callback_item")
            second_item = emission_names.temporary("second_callback_item")
            callback = emission_names.temporary("callback")
            return (
                f"{{ let {callbacks}: Vec<Box<dyn Fn(u64) -> u64>> = "
                f"vec![Box::new(|{first_item}| {first_item} + 1), "
                f"Box::new(|{second_item}| {second_item} * 2)]; "
                f"{callbacks}.iter().map(|{callback}| {callback}({value}))"
                ".sum::<u64>() }"
            )
        if expression.constructor == "TcpListener":
            address = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            return f"std::net::TcpListener::bind({address}).unwrap()"
        if expression.constructor == "TcpStream":
            port = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            return (
                "std::net::TcpStream::connect("
                f'format!("127.0.0.1:{{}}", {port})).unwrap()'
            )
        if expression.constructor == "ThreadPool":
            size = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            return f"__CwThreadPool::new({size})"
        if expression.constructor == "FileOpen":
            path = _render_expression(
                expression.arguments[0], boundary_names, emission_names
            )
            return f"std::fs::File::open({path})"
    if isinstance(expression, StructConstructorIR):
        fields = ", ".join(
            f"{name}: {_render_expression(value, boundary_names, emission_names)}"
            for name, value in expression.arguments
        )
        return f"{expression.struct_symbol} {{ {fields} }}"
    if isinstance(expression, EnumConstructorIR):
        values = ", ".join(
            _render_expression(value, boundary_names, emission_names)
            for _, value in expression.arguments
        )
        if not expression.arguments:
            return f"{expression.enum_symbol}::{expression.variant}"
        if expression.tuple_style:
            return f"{expression.enum_symbol}::{expression.variant}({values})"
        fields = ", ".join(
            f"{name}: {_render_expression(value, boundary_names, emission_names)}"
            for name, value in expression.arguments
        )
        return f"{expression.enum_symbol}::{expression.variant} {{ {fields} }}"
    if isinstance(expression, FieldAccessIR):
        rendered = (
            f"{_render_expression(expression.receiver, boundary_names, emission_names)}."
            f"{expression.field}"
        )
        return rendered if _is_copy_type(expression.type_ref) else f"{rendered}.clone()"
    if isinstance(expression, MethodCallIR):
        rendered_receiver = _render_method_receiver(
            expression.receiver,
            boundary_names,
            emission_names,
        )
        rendered_arguments = [
            _render_expression(value, boundary_names, emission_names)
            for value in expression.arguments
        ]
        semantic_receiver = expression.receiver.type_ref.underlying
        if semantic_receiver.rust_name in {"String", "Str"}:
            if expression.method == "parse":
                target = expression.type_ref.arguments[0].render()
                parse_error = emission_names.temporary("parse_error")
                return (
                    f"{rendered_receiver}.parse::<{target}>()"
                    f".map_err(|{parse_error}| {parse_error}.to_string())"
                )
            if expression.method == "join":
                separator = (
                    f"{rendered_receiver}.as_str()"
                    if semantic_receiver.rust_name == "String"
                    else rendered_receiver
                )
                return f"{rendered_arguments[0]}.join({separator})"
        if expression.receiver.type_ref.rust_name == "Arc":
            if expression.method == "strong_count":
                return f"std::sync::Arc::strong_count(&{rendered_receiver})"
            if expression.method == "add_locked":
                return (
                    f"{{ *{rendered_receiver}.lock().unwrap() += "
                    f"{rendered_arguments[0]}; }}"
                )
            if expression.method == "get_locked":
                return f"*{rendered_receiver}.lock().unwrap()"
        if expression.receiver.type_ref.rust_name == "Box":
            if expression.method == "deref_copy":
                return f"*{rendered_receiver}"
        if expression.receiver.type_ref.rust_name == "Rc":
            if expression.method == "strong_count":
                return f"std::rc::Rc::strong_count(&{rendered_receiver})"
            if expression.method == "deref_copy":
                return f"*{rendered_receiver}"
        if expression.receiver.type_ref.rust_name == "RefCell":
            if expression.method == "borrow_copy":
                return f"*{rendered_receiver}.borrow()"
        if expression.receiver.type_ref.rust_name == "Sender":
            if expression.method == "send":
                return f"{rendered_receiver}.send({rendered_arguments[0]}).unwrap()"
        if expression.receiver.type_ref.rust_name == "Receiver":
            if expression.method == "recv":
                return f"{rendered_receiver}.recv().unwrap()"
            if expression.method == "recv_async":
                return f"__cw_recv_async(&{rendered_receiver})"
        if expression.receiver.type_ref.rust_name == "ThreadHandle":
            if expression.method == "join":
                return f"{rendered_receiver}.join().unwrap()"
        if expression.receiver.type_ref.rust_name == "TcpListener":
            if expression.method == "local_port":
                return f"u64::from({rendered_receiver}.local_addr().unwrap().port())"
            if expression.method == "serve_http_once":
                hello, missing = rendered_arguments
                stream = emission_names.temporary("http_stream")
                request = emission_names.temporary("http_request")
                status = emission_names.temporary("http_status")
                body = emission_names.temporary("http_body")
                code = emission_names.temporary("http_code")
                response = emission_names.temporary("http_response")
                return (
                    f"{{ let (mut {stream}, _) = "
                    f"{rendered_receiver}.accept().unwrap(); "
                    f"let mut {request} = String::new(); "
                    f"std::io::Read::read_to_string(&mut {stream}, "
                    f"&mut {request}).unwrap(); "
                    f"let ({status}, {body}, {code}) = "
                    f'if {request}.starts_with("GET / HTTP/1.1\\r\\n") {{ '
                    f'("HTTP/1.1 200 OK", {hello}, 200u64) '
                    f'}} else if {request}.starts_with("GET /sleep HTTP/1.1\\r\\n") {{ '
                    "std::thread::sleep(std::time::Duration::from_millis(50)); "
                    f'("HTTP/1.1 200 OK", {hello}, 200u64) '
                    f'}} else {{ ("HTTP/1.1 404 NOT FOUND", {missing}, 404u64) }}; '
                    f"let {response} = format!("
                    '"{}\\r\\nContent-Length: {}\\r\\nConnection: close\\r\\n\\r\\n{}", '
                    f"{status}, {body}.len(), {body}); "
                    f"std::io::Write::write_all(&mut {stream}, "
                    f"{response}.as_bytes()).unwrap(); "
                    f"std::io::Write::flush(&mut {stream}).unwrap(); "
                    f"let _ = {stream}.shutdown(std::net::Shutdown::Both); "
                    f"{code} }}"
                )
        if expression.receiver.type_ref.rust_name == "TcpStream":
            if expression.method == "write_get":
                path = rendered_arguments[0]
                request = emission_names.temporary("http_request")
                return (
                    f"{{ let {request} = format!("
                    '"GET {} HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n", '
                    f"{path}); std::io::Write::write_all(&mut {rendered_receiver}, "
                    f"{request}.as_bytes()).unwrap(); }}"
                )
            if expression.method == "shutdown_write":
                return (
                    f"{rendered_receiver}.shutdown(std::net::Shutdown::Write).unwrap()"
                )
            if expression.method == "read_to_string":
                response = emission_names.temporary("http_response")
                return (
                    f"{{ let mut {response} = String::new(); "
                    f"std::io::Read::read_to_string(&mut {rendered_receiver}, "
                    f"&mut {response}).unwrap(); {response} }}"
                )
        if expression.receiver.type_ref.rust_name == "File":
            if expression.method == "read_to_string":
                contents = emission_names.temporary("file_contents")
                return (
                    f"{{ let mut {contents} = String::new(); "
                    f"std::io::Read::read_to_string(&mut {rendered_receiver}, "
                    f"&mut {contents}).map(|_| {contents}) }}"
                )
        if expression.receiver.type_ref.rust_name == "HashMap":
            if expression.method in {"contains_key", "remove", "get", "get_mut"}:
                lookup = (
                    rendered_arguments[0]
                    if expression.arguments[0].type_ref == STR
                    else f"&{rendered_arguments[0]}"
                )
                return f"{rendered_receiver}.{expression.method}({lookup})"
            if expression.method == "iter_ref":
                return f"{rendered_receiver}.iter()"
            if expression.method == "get_or":
                lookup = (
                    rendered_arguments[0]
                    if expression.arguments[0].type_ref == STR
                    else f"&{rendered_arguments[0]}"
                )
                return (
                    f"{rendered_receiver}.get({lookup})"
                    f".cloned().unwrap_or({rendered_arguments[1]})"
                )
            if expression.method == "entry_or_insert":
                return (
                    f"{rendered_receiver}.entry({rendered_arguments[0]})"
                    f".or_insert({rendered_arguments[1]}).clone()"
                )
            if expression.method == "add":
                value_type = expression.receiver.type_ref.underlying.arguments[1]
                return (
                    "{ *"
                    f"{rendered_receiver}.entry({rendered_arguments[0]})"
                    f".or_insert({_numeric_zero(value_type)}) "
                    f"+= {rendered_arguments[1]}; }}"
                )
        if (
            expression.receiver.type_ref.rust_name == "Vec"
            and expression.method == "iter"
        ):
            return f"{rendered_receiver}.iter().copied()"
        if (
            expression.receiver.type_ref.rust_name == "Vec"
            and expression.method == "iter_ref"
        ):
            return f"{rendered_receiver}.iter()"
        if (
            expression.receiver.type_ref.rust_name == "Vec"
            and expression.method == "split_at_mut_sum"
        ):
            midpoint = rendered_arguments[0]
            element = expression.receiver.type_ref.arguments[0].render()
            mid = emission_names.temporary("midpoint")
            length = emission_names.temporary("length")
            pointer = emission_names.temporary("pointer")
            left = emission_names.temporary("left_slice")
            right = emission_names.temporary("right_slice")
            return (
                f"{{ let {mid}: usize = {midpoint}; "
                f"let {length} = {rendered_receiver}.len(); "
                f'assert!({mid} <= {length}, "midpoint out of bounds"); '
                f"let {pointer} = {rendered_receiver}.as_mut_ptr(); "
                f"let ({left}, {right}) = unsafe {{ "
                f"(std::slice::from_raw_parts_mut({pointer}, {mid}), "
                f"std::slice::from_raw_parts_mut({pointer}.add({mid}), "
                f"{length} - {mid})) }}; "
                f"{left}.iter().copied().sum::<{element}>() + "
                f"{right}.iter().copied().sum::<{element}>() }}"
            )
        if expression.receiver.type_ref.rust_name in {
            "Iterator",
            "ParallelIterator",
            "ParallelIteratorRef",
        }:
            if expression.method == "collect_vec":
                return f"{rendered_receiver}.collect::<Vec<_>>()"
            if expression.method == "collect_map":
                return (
                    f"{rendered_receiver}.collect::<std::collections::HashMap<_, _>>()"
                )
            if (
                expression.method == "reduce"
                and expression.receiver.type_ref.rust_name != "Iterator"
            ):
                return f"{rendered_receiver}.reduce_with({rendered_arguments[0]})"
        arguments = ", ".join(rendered_arguments)
        return f"{rendered_receiver}.{expression.method}({arguments})"
    if isinstance(expression, TraitCallIR):
        receiver = _render_expression(
            expression.receiver, boundary_names, emission_names
        )
        return (
            f"<{expression.concrete_type.render()} as "
            f"{expression.trait_symbol}>::{expression.method}(&{receiver})"
        )
    if isinstance(expression, FunctionPointerTwiceIR):
        argument = _render_expression(
            expression.argument, boundary_names, emission_names
        )
        parameter = expression.parameter_type.render()
        result = expression.type_ref.render()
        operation = emission_names.temporary("operation")
        operation_argument = emission_names.temporary("operation_argument")
        return (
            f"{{ let {operation}: fn({parameter}) -> {result} = "
            f"__cw_native_{expression.target}; "
            f"let {operation_argument}: {parameter} = {argument}; "
            f"{operation}({operation_argument}) + "
            f"{operation}({operation_argument}) }}"
        )
    if isinstance(expression, NativePrintlnIR):
        return (
            'println!("{}", '
            f"{_render_expression(expression.value, boundary_names, emission_names)})"
        )
    if isinstance(expression, PythonPrintIR):
        value = _render_expression(expression.value, boundary_names, emission_names)
        if expression.value.type_ref.rust_name == "String":
            value = f"{value}.clone()"
        py = emission_names.temporary("attached_python")
        return (
            f"Python::attach(|{py}| -> PyResult<()> {{ "
            f'{py}.import("builtins")?.getattr("print")?.call1(('
            f"{value},))?; std::result::Result::Ok(()) }})?"
        )
    if isinstance(expression, TryIR):
        return (
            f"{_render_expression(expression.value, boundary_names, emission_names)}?"
        )
    if isinstance(expression, AwaitIR):
        return (
            f"{_render_expression(expression.value, boundary_names, emission_names)}"
            ".await"
        )
    if isinstance(expression, PanicIR):
        return (
            'panic!("{}", '
            f"{_render_expression(expression.message, boundary_names, emission_names)})"
        )
    if isinstance(expression, ClosureIR):
        body = _render_expression(expression.body, boundary_names, emission_names)
        if expression.parameter is None:
            return f"move || {body}"
        closure_parameter = expression.rust_parameter
        assert closure_parameter is not None
        second_parameter = expression.rust_second_parameter
        if second_parameter is not None:
            return f"|{closure_parameter}, {second_parameter}| {body}"
        if expression.borrowed_parameter:
            item = emission_names.temporary("closure_item")
            projection = (
                item if expression.parameter_projection == "borrow" else f"*{item}"
            )
            return f"|{item}| {{ let {closure_parameter} = {projection}; {body} }}"
        return f"|{closure_parameter}| {body}"
    raise AssertionError(f"unhandled expression IR: {type(expression).__name__}")


def _render_method_receiver(
    expression: ExpressionIR,
    boundary_names: set[str],
    emission_names: EmissionNames,
) -> str:
    """Render a borrowed method receiver without cloning an owned struct field."""

    if isinstance(expression, (FieldAccessIR, IndexIR)):
        return _render_place_expression(expression, boundary_names, emission_names)
    return _render_expression(expression, boundary_names, emission_names)


def _render_place_expression(
    expression: ExpressionIR,
    boundary_names: set[str],
    emission_names: EmissionNames,
) -> str:
    """Render a storage place without cloning an intermediate projection."""

    if isinstance(expression, NameIR):
        return expression.rust_name
    if isinstance(expression, FieldAccessIR):
        return (
            f"{_render_place_expression(expression.receiver, boundary_names, emission_names)}."
            f"{expression.field}"
        )
    if isinstance(expression, IndexIR):
        receiver = _render_place_expression(
            expression.receiver, boundary_names, emission_names
        )
        index = _render_expression(expression.index, boundary_names, emission_names)
        return f"{receiver}[{index}]"
    return _render_expression(expression, boundary_names, emission_names)


def _ends_with_return(statements: tuple[StatementIR, ...]) -> bool:
    return bool(statements) and isinstance(statements[-1], ReturnIR)


def _is_copy_type(type_ref: TypeRef) -> bool:
    return (
        type_ref.ownership == "Ref"
        or type_ref.is_numeric
        or type_ref.rust_name in {"bool", "char"}
        or type_ref.rust_name == "Unit"
        or (
            type_ref.rust_name in {"Tuple", "Array"}
            and all(_is_copy_type(value) for value in type_ref.arguments)
        )
    )


def _rust_string_literal(value: str) -> str:
    pieces = ['"']
    for character in value:
        code = ord(character)
        if character == '"':
            pieces.append('\\"')
        elif character == "\\":
            pieces.append("\\\\")
        elif character == "\n":
            pieces.append("\\n")
        elif character == "\r":
            pieces.append("\\r")
        elif character == "\t":
            pieces.append("\\t")
        elif code < 0x20 or code == 0x7F:
            pieces.append(f"\\u{{{code:x}}}")
        else:
            pieces.append(character)
    pieces.append('"')
    return "".join(pieces)


def _rust_char_literal(value: str) -> str:
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


def _numeric_zero(type_ref: TypeRef) -> str:
    """Render the additive identity with the map value's concrete Rust type."""

    prefix = "0.0" if type_ref.is_float else "0"
    return f"{prefix}{type_ref.render()}"
