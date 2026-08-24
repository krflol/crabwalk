"""Python ABI and recursively structured ownership policy."""

from __future__ import annotations

from .ir import TypeRef

OWNED_VECTOR_ELEMENTS = frozenset(
    {
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
        "u8",
        "u16",
        "u32",
        "u64",
        "u128",
        "usize",
        "f32",
        "f64",
        "bool",
        "char",
        "String",
    }
)


def struct_field_type_supported(
    type_ref: TypeRef,
    visible_domain_symbols: set[str] | None = None,
) -> bool:
    visible_domain_symbols = visible_domain_symbols or set()
    if type_ref.rust_name in OWNED_VECTOR_ELEMENTS:
        return True
    if type_ref.rust_name in visible_domain_symbols and not type_ref.arguments:
        return True
    if type_ref.rust_name in {"Vec", "Option"} and len(type_ref.arguments) == 1:
        return struct_field_type_supported(type_ref.arguments[0], set())
    return False


def enum_field_type_supported(
    type_ref: TypeRef,
    visible_domain_symbols: set[str],
) -> bool:
    return struct_field_type_supported(type_ref, visible_domain_symbols)


def owned_vector_element_supported(
    type_ref: TypeRef,
    domain_symbols: set[str],
    *,
    allow_domain: bool,
) -> bool:
    if type_ref.rust_name in OWNED_VECTOR_ELEMENTS and not type_ref.arguments:
        return True
    if allow_domain and type_ref.rust_name in domain_symbols and not type_ref.arguments:
        return True
    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        return owned_vector_element_supported(
            type_ref.arguments[0], domain_symbols, allow_domain=False
        )
    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        return all(
            owned_vector_element_supported(value, domain_symbols, allow_domain=False)
            for value in type_ref.arguments
        )
    if type_ref.rust_name == "Vec" and len(type_ref.arguments) == 1:
        return owned_vector_element_supported(
            type_ref.arguments[0], domain_symbols, allow_domain=False
        )
    return False


def python_parameter_boundary_supported(type_ref: TypeRef) -> bool:
    if type_ref.rust_name in {*OWNED_VECTOR_ELEMENTS, "Str"}:
        return not type_ref.arguments
    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        return python_parameter_boundary_supported(type_ref.arguments[0])
    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        return all(
            python_parameter_boundary_supported(value) for value in type_ref.arguments
        )
    return False


def python_return_boundary_supported(type_ref: TypeRef) -> bool:
    if type_ref.rust_name in {*OWNED_VECTOR_ELEMENTS, "Unit"}:
        return not type_ref.arguments
    if type_ref.rust_name in {"Option", "Vec"} and len(type_ref.arguments) == 1:
        return python_return_boundary_supported(type_ref.arguments[0])
    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        return all(
            python_return_boundary_supported(value) for value in type_ref.arguments
        )
    if type_ref.rust_name == "HashMap" and len(type_ref.arguments) == 2:
        return all(
            python_return_boundary_supported(value) for value in type_ref.arguments
        )
    if type_ref.rust_name == "Result" and len(type_ref.arguments) == 2:
        success, error = type_ref.arguments
        return python_return_boundary_supported(
            success
        ) and rust_error_display_supported(error)
    return False


def rust_error_display_supported(type_ref: TypeRef) -> bool:
    return (
        type_ref.rust_name in {*OWNED_VECTOR_ELEMENTS, "Str"} and not type_ref.arguments
    )
