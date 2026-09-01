"""Semantic Rust places and receiver capability rules."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, TypeAlias

from crabwalk.diagnostics import SourceSpan

from .ir import TypeRef
from .types import IteratorType

ReceiverAccess: TypeAlias = Literal["shared", "mutable", "owned", "interior"]


@dataclass(frozen=True, slots=True)
class Place:
    root: str
    projections: tuple[str, ...] = ()


class LocalStorage(StrEnum):
    """Whether a semantic local can inhabit an ordinary named Rust slot."""

    NAMEABLE = "nameable"
    OPAQUE = "opaque"


@dataclass(slots=True)
class LocalState:
    semantic_type: TypeRef
    storage: LocalStorage
    moved_at: SourceSpan | None = None
    moved_by: str | None = None


def local_storage_for_type(type_ref: TypeRef) -> LocalStorage:
    """Classify concrete storage identity independently of semantic capability."""

    if isinstance(type_ref, IteratorType) or type_ref.rust_name in {
        "Future",
        "Closure",
    }:
        return LocalStorage.OPAQUE
    return LocalStorage.NAMEABLE


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
    if receiver == "Vec" and method in {
        "push",
        "pop",
        "reserve",
        "split_at_mut_sum",
        "sort",
        "sort_unstable",
        "sort_by_key",
        "sort_unstable_by_key",
        "dedup",
        "reverse",
        "truncate",
    }:
        return "mutable"
    if receiver in {"HashMap", "BTreeMap"} and method in {
        "insert",
        "remove",
        "get_mut",
        "entry_or_insert",
        "add",
    }:
        return "mutable"
    if receiver in {"HashSet", "BTreeSet"} and method in {
        "insert",
        "remove",
    }:
        return "mutable"
    if receiver == "String" and method == "push_str":
        return "mutable"
    if receiver == "Option" and method == "as_mut":
        return "mutable"
    if receiver == "String" and method == "into_bytes":
        return "owned"
    if receiver == "Vec" and method == "into_utf8":
        return "owned"
    if receiver == "TcpStream" and method in {"write_get", "read_to_string"}:
        return "mutable"
    if receiver == "File" and method == "read_to_string":
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
    if (
        receiver
        in {
            "HashMap",
            "BTreeMap",
            "HashSet",
            "BTreeSet",
            "Vec",
        }
        and method == "into_iter"
    ):
        return "owned"
    return "shared"
