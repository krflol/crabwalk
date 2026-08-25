"""Python ABI and recursively structured ownership policy.

Boundary support is a property of the complete Python representation, not just
of each child type in isolation.  In particular, ``Result`` is a top-level
return control type and ``Option`` is only lossless when its child cannot also
normalize to Python ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

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

# PyO3's typed buffer API implements ``Element`` for these Crabwalk numeric
# types.  Deliberately exclude i128/u128, bool, char, and domain/container
# values: the first buffer milestone is a flat native-endian numeric view.
BUFFER_ELEMENTS = frozenset(
    {
        "i8",
        "i16",
        "i32",
        "i64",
        "u8",
        "u16",
        "u32",
        "u64",
        "usize",
        "f32",
        "f64",
    }
)


class BoundaryPosition(StrEnum):
    TOP_LEVEL = "top_level"
    NESTED = "nested"


class PythonKind(StrEnum):
    SCALAR = "scalar"
    NONE = "none"
    OPTION = "option"
    TUPLE = "tuple"
    LIST = "list"
    BYTES = "bytes"
    BUFFER = "buffer"
    DICT = "dict"
    CONTROL = "control"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class BoundaryShape:
    """Observable Python properties of one fully composed Rust type."""

    input_supported: bool
    output_supported: bool
    python_kind: PythonKind
    hashable: bool
    injective: bool
    can_equal_none: bool


_UNSUPPORTED_SHAPE = BoundaryShape(
    False,
    False,
    PythonKind.UNSUPPORTED,
    False,
    False,
    False,
)


def boundary_shape(
    type_ref: TypeRef,
    *,
    position: BoundaryPosition = BoundaryPosition.NESTED,
) -> BoundaryShape:
    """Describe whether one Rust value has a lossless Python representation."""

    if type_ref.arguments == () and type_ref.is_integer:
        return BoundaryShape(True, True, PythonKind.SCALAR, True, True, False)
    if type_ref.arguments == () and type_ref.is_float:
        # Python floats are hashable, but Rust f32/f64 do not satisfy Eq + Hash
        # and therefore cannot be emitted as std::collections::HashMap keys.
        return BoundaryShape(True, True, PythonKind.SCALAR, False, True, False)
    if type_ref.arguments == () and type_ref.rust_name == "bool":
        return BoundaryShape(True, True, PythonKind.SCALAR, True, True, False)
    if type_ref.arguments == () and type_ref.rust_name in {"char", "String"}:
        return BoundaryShape(True, True, PythonKind.SCALAR, True, True, False)
    if type_ref.arguments == () and type_ref.rust_name == "Str":
        return BoundaryShape(True, False, PythonKind.SCALAR, True, True, False)
    if type_ref.arguments == () and type_ref.rust_name == "Unit":
        return BoundaryShape(True, True, PythonKind.NONE, True, True, True)

    if type_ref.rust_name == "Buffer" and len(type_ref.arguments) == 1:
        element = type_ref.arguments[0]
        supported = (
            position == BoundaryPosition.TOP_LEVEL
            and element.rust_name in BUFFER_ELEMENTS
            and not element.arguments
        )
        return BoundaryShape(
            supported,
            False,
            PythonKind.BUFFER if supported else PythonKind.UNSUPPORTED,
            False,
            supported,
            False,
        )

    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        child = boundary_shape(
            type_ref.arguments[0],
            position=BoundaryPosition.NESTED,
        )
        lossless = child.injective and not child.can_equal_none
        return BoundaryShape(
            child.input_supported and lossless,
            child.output_supported and lossless,
            PythonKind.OPTION,
            child.hashable,
            lossless,
            True,
        )

    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        children = tuple(
            boundary_shape(value, position=BoundaryPosition.NESTED)
            for value in type_ref.arguments
        )
        return BoundaryShape(
            all(value.input_supported for value in children),
            all(value.output_supported for value in children),
            PythonKind.TUPLE,
            all(value.hashable for value in children),
            all(value.injective for value in children),
            False,
        )

    if type_ref.rust_name in {"Vec", "Array"} and len(type_ref.arguments) == 1:
        child = boundary_shape(
            type_ref.arguments[0],
            position=BoundaryPosition.NESTED,
        )
        byte_vector = (
            type_ref.rust_name == "Vec"
            and type_ref.arguments[0].rust_name == "u8"
            and not type_ref.arguments[0].arguments
        )
        return BoundaryShape(
            child.input_supported and child.injective,
            child.output_supported and child.injective,
            PythonKind.BYTES if byte_vector else PythonKind.LIST,
            byte_vector,
            child.injective,
            False,
        )

    if type_ref.rust_name == "HashMap" and len(type_ref.arguments) == 2:
        key = boundary_shape(
            type_ref.arguments[0],
            position=BoundaryPosition.NESTED,
        )
        value = boundary_shape(
            type_ref.arguments[1],
            position=BoundaryPosition.NESTED,
        )
        valid_key = key.hashable and key.injective
        return BoundaryShape(
            # Crabwalk does not currently expose an implicit Python-to-HashMap
            # boundary. In particular, normalizing byte-vector keys into lists
            # would make an intermediate Python mapping unrepresentable.
            False,
            key.output_supported and value.output_supported and valid_key,
            PythonKind.DICT,
            False,
            key.injective and value.injective,
            False,
        )

    if type_ref.rust_name == "Result" and len(type_ref.arguments) == 2:
        success, error = type_ref.arguments
        success_shape = boundary_shape(
            success,
            position=BoundaryPosition.NESTED,
        )
        output_supported = (
            position == BoundaryPosition.TOP_LEVEL
            and success_shape.output_supported
            and success_shape.injective
            and rust_error_display_supported(error)
        )
        return BoundaryShape(
            False,
            output_supported,
            PythonKind.CONTROL,
            False,
            False,
            False,
        )

    return _UNSUPPORTED_SHAPE


def _lossless_option_child(type_ref: TypeRef) -> bool:
    child = boundary_shape(type_ref, position=BoundaryPosition.NESTED)
    return child.injective and not child.can_equal_none


def struct_field_type_supported(
    type_ref: TypeRef,
    visible_domain_symbols: set[str] | None = None,
) -> bool:
    visible_domain_symbols = visible_domain_symbols or set()
    if type_ref.rust_name in OWNED_VECTOR_ELEMENTS and not type_ref.arguments:
        return True
    if type_ref.rust_name in visible_domain_symbols and not type_ref.arguments:
        return True
    if type_ref.rust_name == "Vec" and len(type_ref.arguments) == 1:
        return struct_field_type_supported(type_ref.arguments[0], set())
    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        child = type_ref.arguments[0]
        return _lossless_option_child(child) and struct_field_type_supported(
            child, set()
        )
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
        child = type_ref.arguments[0]
        return _lossless_option_child(child) and owned_vector_element_supported(
            child, domain_symbols, allow_domain=False
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


def python_parameter_boundary_supported(
    type_ref: TypeRef,
    *,
    position: BoundaryPosition = BoundaryPosition.TOP_LEVEL,
) -> bool:
    if type_ref.rust_name == "Buffer" and len(type_ref.arguments) == 1:
        element = type_ref.arguments[0]
        return (
            position == BoundaryPosition.TOP_LEVEL
            and element.rust_name in BUFFER_ELEMENTS
            and not element.arguments
        )
    if type_ref.rust_name in {*OWNED_VECTOR_ELEMENTS, "Str"}:
        return not type_ref.arguments
    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        child = type_ref.arguments[0]
        return _lossless_option_child(child) and python_parameter_boundary_supported(
            child,
            position=BoundaryPosition.NESTED,
        )
    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        return all(
            python_parameter_boundary_supported(
                value,
                position=BoundaryPosition.NESTED,
            )
            for value in type_ref.arguments
        )
    return False


def python_return_boundary_supported(type_ref: TypeRef) -> bool:
    return boundary_shape(
        type_ref,
        position=BoundaryPosition.TOP_LEVEL,
    ).output_supported


def python_mapping_key_supported(type_ref: TypeRef) -> bool:
    """Whether a native value has a hashable, injective Python key form."""

    shape = boundary_shape(type_ref, position=BoundaryPosition.NESTED)
    return shape.output_supported and shape.hashable and shape.injective


def rust_error_display_supported(type_ref: TypeRef) -> bool:
    return (
        type_ref.rust_name in {*OWNED_VECTOR_ELEMENTS, "Str"} and not type_ref.arguments
    )
