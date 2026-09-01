"""Rust backend spelling for semantic Crabwalk types.

Semantic type variants intentionally do not decide how nested values are spelled
in generated Rust. ``TypeRef.render()`` remains a compatibility entry point for
existing passes and tests, but delegates here.
"""

from __future__ import annotations

from .types import (
    ArrayType,
    DynamicTraitType,
    IteratorExecution,
    IteratorType,
    LifetimeReferenceType,
    OwnershipType,
    PrimitiveType,
    TupleType,
    TypeRef,
    UnitType,
)


def render_rust_type(type_ref: TypeRef) -> str:
    """Render one semantic type for an ordinary Rust type position."""

    if type_ref.rust_name == "Associated":
        assert type_ref.python_name is not None
        return f"Self::{type_ref.python_name}"
    if isinstance(type_ref, OwnershipType):
        rendered = render_rust_type(type_ref.inner)
        if type_ref.ownership_kind == "Owned":
            return rendered
        if type_ref.ownership_kind == "Ref":
            return f"&{rendered}"
        if type_ref.ownership_kind == "Shared":
            return f"std::sync::Arc<{rendered}>"
        return f"&mut {rendered}"
    if isinstance(type_ref, LifetimeReferenceType):
        rendered = (
            "str"
            if type_ref.target.rust_name == "Str"
            else render_rust_type(type_ref.target)
        )
        return f"&'{type_ref.rendered_lifetime} {rendered}"
    if isinstance(type_ref, PrimitiveType) and type_ref.name == "Str":
        return "&str"
    if isinstance(type_ref, UnitType):
        return "()"
    if isinstance(type_ref, TupleType):
        values = ", ".join(render_rust_type(value) for value in type_ref.items)
        return f"({values}{',' if len(type_ref.items) == 1 else ''})"
    if isinstance(type_ref, ArrayType):
        return f"[{render_rust_type(type_ref.item)}; {type_ref.length}]"
    if isinstance(type_ref, DynamicTraitType):
        return f"dyn {type_ref.trait_symbol}"
    if isinstance(type_ref, IteratorType):
        item = render_rust_type(type_ref.exposed_item_type)
        family = (
            "ParallelIterator"
            if type_ref.execution == IteratorExecution.PARALLEL
            else "Iterator"
        )
        return f"{family}<Item = {item}>"

    concrete_paths = {
        "TcpListener": "std::net::TcpListener",
        "TcpStream": "std::net::TcpStream",
        "ThreadPool": "__CwThreadPool",
        "File": "std::fs::File",
        "IoError": "std::io::Error",
        "PathBuf": "std::path::PathBuf",
        "TextColumn": "__CwTextColumn",
    }
    if type_ref.rust_name == "Buffer":
        return f"__CwBuffer<'_, {render_rust_type(type_ref.arguments[0])}>"
    if type_ref.rust_name == "Slice":
        return f"&[{render_rust_type(type_ref.arguments[0])}]"
    if type_ref.rust_name in concrete_paths:
        return concrete_paths[type_ref.rust_name]

    standard_paths = {
        "Arc": "std::sync::Arc",
        "HashMap": "std::collections::HashMap",
        "HashSet": "std::collections::HashSet",
        "BTreeMap": "std::collections::BTreeMap",
        "BTreeSet": "std::collections::BTreeSet",
        "Mutex": "std::sync::Mutex",
        "Rc": "std::rc::Rc",
        "Receiver": "std::sync::mpsc::Receiver",
        "RefCell": "std::cell::RefCell",
        "Sender": "std::sync::mpsc::Sender",
        "SyncSender": "std::sync::mpsc::SyncSender",
        "ThreadHandle": "std::thread::JoinHandle",
    }
    name = standard_paths.get(type_ref.rust_name, type_ref.rust_name)
    if not type_ref.arguments:
        return name
    values = ", ".join(render_rust_type(value) for value in type_ref.arguments)
    return f"{name}<{values}>"
