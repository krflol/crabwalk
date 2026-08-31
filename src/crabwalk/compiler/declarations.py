"""Static classification of module-level Crabwalk declarations."""

from __future__ import annotations

import ast
from dataclasses import dataclass


def is_rust_attribute(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "rust"
    )


def is_rust_call_named(node: ast.AST | None, name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and is_rust_attribute(node.func)
        and node.func.attr == name
    )


def has_rust_fn_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        (
            isinstance(item, ast.Attribute)
            and is_rust_attribute(item)
            and item.attr in {"fn", "async_fn", "python_adapter"}
        )
        or (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and is_rust_attribute(item.func)
            and item.func.attr
            in {
                "fn",
                "generic",
                "method",
                "impl",
                "operator",
                "extern",
                "extern_method",
                "python_adapter",
            }
        )
        for item in node.decorator_list
    )


def has_rust_async_fn_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return any(
        isinstance(item, ast.Attribute)
        and is_rust_attribute(item)
        and item.attr == "async_fn"
        for item in node.decorator_list
    )


def is_extern_declaration(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return bool(
        len(node.decorator_list) == 1
        and isinstance(node.decorator_list[0], ast.Call)
        and isinstance(node.decorator_list[0].func, ast.Attribute)
        and is_rust_attribute(node.decorator_list[0].func)
        and node.decorator_list[0].func.attr in {"extern", "extern_method"}
    )


def is_python_adapter_declaration(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    if len(node.decorator_list) != 1:
        return False
    decorator = node.decorator_list[0]
    if isinstance(decorator, ast.Attribute):
        return is_rust_attribute(decorator) and decorator.attr == "python_adapter"
    return bool(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and is_rust_attribute(decorator.func)
        and decorator.func.attr == "python_adapter"
    )


def has_rust_struct_decorator(node: ast.ClassDef) -> bool:
    return any(
        (
            isinstance(item, ast.Attribute)
            and is_rust_attribute(item)
            and item.attr == "struct"
        )
        or (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and is_rust_attribute(item.func)
            and item.func.attr == "struct"
        )
        for item in node.decorator_list
    )


def has_rust_enum_decorator(node: ast.ClassDef) -> bool:
    return any(
        (
            isinstance(item, ast.Attribute)
            and is_rust_attribute(item)
            and item.attr in {"enum", "error"}
        )
        or (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and is_rust_attribute(item.func)
            and item.func.attr in {"enum", "error"}
        )
        for item in node.decorator_list
    )


@dataclass(frozen=True, slots=True)
class DeclarationIndex:
    functions: tuple[ast.FunctionDef | ast.AsyncFunctionDef, ...]
    structs: tuple[ast.ClassDef, ...]
    enums: tuple[ast.ClassDef, ...]

    @classmethod
    def discover(cls, tree: ast.Module) -> "DeclarationIndex":
        functions = tuple(
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and has_rust_fn_decorator(node)
        )
        structs = tuple(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and has_rust_struct_decorator(node)
        )
        enums = tuple(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and has_rust_enum_decorator(node)
        )
        return cls(functions, structs, enums)
