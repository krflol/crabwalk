"""Semantic Rust places and receiver capability rules."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal, TypeAlias

from .ir import TypeRef

ReceiverAccess: TypeAlias = Literal["shared", "mutable", "owned", "interior"]


@dataclass(frozen=True, slots=True)
class Place:
    root: str
    projections: tuple[str, ...] = ()


def place_from_ast(node: ast.expr) -> Place | None:
    if isinstance(node, ast.Name):
        return Place(node.id)
    if isinstance(node, ast.Attribute):
        base = place_from_ast(node.value)
        return (
            None
            if base is None
            else Place(base.root, (*base.projections, f"field:{node.attr}"))
        )
    if isinstance(node, ast.Subscript):
        base = place_from_ast(node.value)
        return None if base is None else Place(base.root, (*base.projections, "index"))
    return None


def receiver_access_for_ownership(ownership: str | None) -> ReceiverAccess:
    if ownership == "Mut":
        return "mutable"
    if ownership == "Owned":
        return "owned"
    return "shared"


def builtin_receiver_access(type_ref: TypeRef, method: str) -> ReceiverAccess:
    receiver = type_ref.underlying.rust_name
    if receiver == "Vec" and method in {"push", "pop", "split_at_mut_sum"}:
        return "mutable"
    if receiver == "HashMap" and method in {
        "insert",
        "remove",
        "get_mut",
        "entry_or_insert",
        "add",
    }:
        return "mutable"
    if receiver == "String" and method == "push_str":
        return "mutable"
    if receiver == "TcpStream" and method in {"write_get", "read_to_string"}:
        return "mutable"
    if receiver == "RefCell" and method == "replace":
        return "interior"
    if receiver == "Arc" and method in {"add_locked", "get_locked"}:
        return "interior"
    if receiver == "ThreadPool" and method == "finish":
        return "owned"
    if receiver == "ThreadHandle" and method == "join":
        return "owned"
    if receiver in {
        "Iterator",
        "ParallelIterator",
        "ParallelIteratorRef",
        "Option",
        "Result",
    } and method in {
        "map",
        "map_err",
        "and_then",
        "or_else",
        "filter",
        "filter_map",
        "copied",
        "cloned",
        "collect_vec",
        "collect_map",
        "sum",
        "count",
        "any",
        "all",
        "find",
        "find_any",
        "find_first",
        "find_last",
        "fold",
        "reduce",
        "enumerate",
        "zip",
        "unwrap",
        "expect",
        "unwrap_or",
        "ok",
        "err",
    }:
        return "owned"
    if receiver == "HashMap" and method == "into_iter":
        return "owned"
    return "shared"
