"""Structural names for compiler-owned Rust and Cargo identifiers."""

from __future__ import annotations

import hashlib
import json
import re

from .ir import TypeRef

PYO3_CARGO_ALIAS = "cw_runtime_pyo3"
RUST_PORTABLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Rust Reference: https://doc.rust-lang.org/reference/keywords.html
#
# Generated crates use Edition 2024. Strict and reserved keywords have the same
# identifier restrictions in every emitted position Crabwalk currently exposes.
# Weak keywords are contextual and remain valid in those positions; in
# particular, rustc accepts ``union`` as a variable, field, variant, method,
# type parameter, and lifetime parameter name outside its union-declaration
# context.
RUST_2024_STRICT_KEYWORDS = frozenset(
    {
        "_",
        "as",
        "async",
        "await",
        "break",
        "const",
        "continue",
        "crate",
        "dyn",
        "else",
        "enum",
        "extern",
        "false",
        "fn",
        "for",
        "if",
        "impl",
        "in",
        "let",
        "loop",
        "match",
        "mod",
        "move",
        "mut",
        "pub",
        "ref",
        "return",
        "self",
        "Self",
        "static",
        "struct",
        "super",
        "trait",
        "true",
        "type",
        "unsafe",
        "use",
        "where",
        "while",
    }
)
RUST_2024_RESERVED_KEYWORDS = frozenset(
    {
        "abstract",
        "become",
        "box",
        "do",
        "final",
        "gen",
        "macro",
        "override",
        "priv",
        "try",
        "typeof",
        "unsized",
        "virtual",
        "yield",
    }
)
RUST_2024_WEAK_KEYWORDS = frozenset({"macro_rules", "raw", "safe", "union"})
RUST_2024_FORBIDDEN_BINDINGS = RUST_2024_STRICT_KEYWORDS | RUST_2024_RESERVED_KEYWORDS


def is_rust_2024_identifier(value: str) -> bool:
    """Return whether ``value`` is safe in Crabwalk's emitted name positions.

    Crabwalk intentionally keeps its portable ASCII identifier subset. Raw
    identifier lowering is not yet part of the source-to-IR contract.
    """

    return bool(RUST_PORTABLE_IDENTIFIER.fullmatch(value)) and (
        value not in RUST_2024_FORBIDDEN_BINDINGS
    )


def mangle_item(module_name: str, source_name: str, *, namespace: str) -> str:
    """Return a deterministic component-aware Rust identifier.

    Each Python module component is encoded separately, so an underscore in a
    component can never be confused with a package separator. UTF-8 is rendered
    as hexadecimal to keep the result inside Rust's portable identifier subset.
    """

    components = (*module_name.split("."), source_name)
    encoded = "_".join(_encode_component(value) for value in components)
    return f"cw_{namespace}_{encoded}"


def mangle_dependency(module_name: str, source_name: str) -> str:
    """Return an internal Cargo/Rust binding for one source dependency name."""

    return mangle_item(module_name, source_name, namespace="dep")


def dependency_crate_alias(package: str) -> str | None:
    """Return Cargo's ordinary Rust crate spelling for a package name."""

    alias = package.replace("-", "_")
    return alias if is_rust_2024_identifier(alias) else None


def cargo_dependency_key(package: str, internal_binding: str) -> str:
    """Select the Cargo key while keeping mandatory PyO3's alias private."""

    alias = dependency_crate_alias(package)
    if alias is None or alias in {"pyo3", PYO3_CARGO_ALIAS}:
        return internal_binding
    return alias


def owned_class_names(type_ref: TypeRef) -> tuple[str, str]:
    """Return collision-resistant Python and Rust names for an owned wrapper."""

    identity = _type_identity(type_ref)
    digest = hashlib.sha256(identity).hexdigest()
    return f"_Crabwalk_{digest}", f"__CwOwned_{digest}"


def _encode_component(value: str) -> str:
    encoded = value.encode("utf-8")
    return f"{len(encoded)}_{encoded.hex()}"


def _type_identity(type_ref: TypeRef) -> bytes:
    def value(item: TypeRef) -> dict[str, object]:
        return {
            "rust_name": item.rust_name,
            "arguments": [value(argument) for argument in item.arguments],
            "python_name": item.python_name,
            "const_value": item.const_value,
            "is_generic": item.is_generic,
            "is_lifetime": item.is_lifetime,
        }

    return json.dumps(
        value(type_ref),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
