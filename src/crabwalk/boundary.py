"""One explicit Python/native conversion contract for every Crabwalk boundary."""

from __future__ import annotations

import math
import struct as struct_module
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, cast

from crabwalk.compiler.abi import BUFFER_ELEMENTS, BoundaryPosition, boundary_shape
from crabwalk.compiler.ir import TypeRef


class InputPolicy(StrEnum):
    EXACT_INT = "ExactInt"
    EXACT_BOOL = "ExactBool"
    NUMBER = "Number"
    STRING = "String"
    CHAR = "Char"
    NONE = "None"
    OPTION = "Option"
    TUPLE = "Tuple"
    SEQUENCE = "Sequence"
    MAPPING = "Mapping"
    RUST_HANDLE = "RustHandle"
    BUFFER = "Buffer"
    UNSUPPORTED = "Unsupported"


class OutputPolicy(StrEnum):
    SCALAR = "Scalar"
    NONE = "None"
    OPTION = "Option"
    TUPLE = "Tuple"
    LIST = "List"
    BYTES = "Bytes"
    DICT = "Dict"
    RESULT = "Result"
    RUST_HANDLE = "RustHandle"
    UNSUPPORTED = "Unsupported"


class AllocationKind(StrEnum):
    NONE = "None"
    PYTHON_CONTAINER = "PythonContainer"
    NATIVE_CONTAINER = "NativeContainer"
    OWNED_HANDLE = "OwnedHandle"
    BORROWED = "Borrowed"
    BORROWED_BUFFER = "BorrowedBuffer"


class OwnershipPolicy(StrEnum):
    COPY = "Copy"
    CLONE = "Clone"
    MOVE = "Move"
    BORROW = "Borrow"
    SHARED_BORROW = "SharedBorrow"
    MUTABLE_BORROW = "MutableBorrow"


@dataclass(frozen=True, slots=True)
class BoundaryCodec:
    """The declared Python representation and ownership policy for one type."""

    type_ref: TypeRef
    input_policy: InputPolicy
    output_policy: OutputPolicy
    allocation: AllocationKind
    ownership: OwnershipPolicy
    children: tuple["BoundaryCodec", ...] = ()


_INTEGER_RANGES = {
    "i8": (-(1 << 7), (1 << 7) - 1),
    "i16": (-(1 << 15), (1 << 15) - 1),
    "i32": (-(1 << 31), (1 << 31) - 1),
    "i64": (-(1 << 63), (1 << 63) - 1),
    "i128": (-(1 << 127), (1 << 127) - 1),
    "isize": (
        -(1 << (struct_module.calcsize("P") * 8 - 1)),
        (1 << (struct_module.calcsize("P") * 8 - 1)) - 1,
    ),
    "u8": (0, (1 << 8) - 1),
    "u16": (0, (1 << 16) - 1),
    "u32": (0, (1 << 32) - 1),
    "u64": (0, (1 << 64) - 1),
    "u128": (0, (1 << 128) - 1),
    "usize": (0, (1 << (struct_module.calcsize("P") * 8)) - 1),
}


def boundary_codec(type_ref: TypeRef) -> BoundaryCodec:
    """Return the single conversion policy used by runtime and generated ABI code."""

    ownership = type_ref.ownership
    if ownership is not None:
        ownership_policy = {
            "Owned": OwnershipPolicy.MOVE,
            "Ref": OwnershipPolicy.SHARED_BORROW,
            "Mut": OwnershipPolicy.MUTABLE_BORROW,
            "Shared": OwnershipPolicy.SHARED_BORROW,
        }[ownership]
        return BoundaryCodec(
            type_ref,
            InputPolicy.RUST_HANDLE,
            OutputPolicy.RUST_HANDLE,
            AllocationKind.OWNED_HANDLE,
            ownership_policy,
            (boundary_codec(type_ref.underlying),),
        )
    if type_ref.is_integer:
        return BoundaryCodec(
            type_ref,
            InputPolicy.EXACT_INT,
            OutputPolicy.SCALAR,
            AllocationKind.NONE,
            OwnershipPolicy.COPY,
        )
    if type_ref.is_float:
        return BoundaryCodec(
            type_ref,
            InputPolicy.NUMBER,
            OutputPolicy.SCALAR,
            AllocationKind.NONE,
            OwnershipPolicy.COPY,
        )
    if type_ref.rust_name == "bool":
        return BoundaryCodec(
            type_ref,
            InputPolicy.EXACT_BOOL,
            OutputPolicy.SCALAR,
            AllocationKind.NONE,
            OwnershipPolicy.COPY,
        )
    if type_ref.rust_name == "String":
        return BoundaryCodec(
            type_ref,
            InputPolicy.STRING,
            OutputPolicy.SCALAR,
            AllocationKind.NATIVE_CONTAINER,
            OwnershipPolicy.CLONE,
        )
    if type_ref.rust_name == "Str":
        return BoundaryCodec(
            type_ref,
            InputPolicy.STRING,
            OutputPolicy.UNSUPPORTED,
            AllocationKind.BORROWED,
            OwnershipPolicy.BORROW,
        )
    if type_ref.rust_name == "char":
        return BoundaryCodec(
            type_ref,
            InputPolicy.CHAR,
            OutputPolicy.SCALAR,
            AllocationKind.NONE,
            OwnershipPolicy.COPY,
        )
    if type_ref.rust_name == "Unit":
        return BoundaryCodec(
            type_ref,
            InputPolicy.NONE,
            OutputPolicy.NONE,
            AllocationKind.NONE,
            OwnershipPolicy.COPY,
        )
    if not type_ref.arguments and type_ref.python_name is not None:
        return BoundaryCodec(
            type_ref,
            InputPolicy.RUST_HANDLE,
            OutputPolicy.RUST_HANDLE,
            AllocationKind.OWNED_HANDLE,
            OwnershipPolicy.CLONE,
        )
    if type_ref.rust_name == "Buffer" and len(type_ref.arguments) == 1:
        element = type_ref.arguments[0]
        supported = element.rust_name in BUFFER_ELEMENTS and not element.arguments
        return BoundaryCodec(
            type_ref,
            InputPolicy.BUFFER if supported else InputPolicy.UNSUPPORTED,
            OutputPolicy.UNSUPPORTED,
            AllocationKind.BORROWED_BUFFER,
            OwnershipPolicy.SHARED_BORROW,
            (boundary_codec(element),),
        )
    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        shape = boundary_shape(type_ref, position=BoundaryPosition.NESTED)
        return BoundaryCodec(
            type_ref,
            InputPolicy.OPTION if shape.input_supported else InputPolicy.UNSUPPORTED,
            OutputPolicy.OPTION if shape.output_supported else OutputPolicy.UNSUPPORTED,
            AllocationKind.NONE,
            OwnershipPolicy.CLONE,
            (boundary_codec(type_ref.arguments[0]),),
        )
    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        shape = boundary_shape(type_ref, position=BoundaryPosition.NESTED)
        return BoundaryCodec(
            type_ref,
            InputPolicy.TUPLE if shape.input_supported else InputPolicy.UNSUPPORTED,
            OutputPolicy.TUPLE if shape.output_supported else OutputPolicy.UNSUPPORTED,
            AllocationKind.PYTHON_CONTAINER,
            OwnershipPolicy.CLONE,
            tuple(boundary_codec(value) for value in type_ref.arguments),
        )
    if type_ref.rust_name in {"Vec", "Array"} and type_ref.arguments:
        shape = boundary_shape(type_ref, position=BoundaryPosition.NESTED)
        byte_vector = (
            type_ref.rust_name == "Vec" and type_ref.arguments[0].rust_name == "u8"
        )
        return BoundaryCodec(
            type_ref,
            InputPolicy.SEQUENCE if shape.input_supported else InputPolicy.UNSUPPORTED,
            (OutputPolicy.BYTES if byte_vector else OutputPolicy.LIST)
            if shape.output_supported
            else OutputPolicy.UNSUPPORTED,
            AllocationKind.PYTHON_CONTAINER,
            OwnershipPolicy.CLONE,
            (boundary_codec(type_ref.arguments[0]),),
        )
    if type_ref.rust_name == "HashMap" and len(type_ref.arguments) == 2:
        shape = boundary_shape(type_ref, position=BoundaryPosition.NESTED)
        return BoundaryCodec(
            type_ref,
            InputPolicy.MAPPING if shape.input_supported else InputPolicy.UNSUPPORTED,
            OutputPolicy.DICT if shape.output_supported else OutputPolicy.UNSUPPORTED,
            AllocationKind.PYTHON_CONTAINER,
            OwnershipPolicy.CLONE,
            tuple(boundary_codec(value) for value in type_ref.arguments),
        )
    if type_ref.rust_name == "Result" and len(type_ref.arguments) == 2:
        shape = boundary_shape(type_ref, position=BoundaryPosition.TOP_LEVEL)
        return BoundaryCodec(
            type_ref,
            InputPolicy.UNSUPPORTED,
            OutputPolicy.RESULT if shape.output_supported else OutputPolicy.UNSUPPORTED,
            AllocationKind.NONE,
            OwnershipPolicy.CLONE,
            tuple(boundary_codec(value) for value in type_ref.arguments),
        )
    return BoundaryCodec(
        type_ref,
        InputPolicy.UNSUPPORTED,
        OutputPolicy.UNSUPPORTED,
        AllocationKind.NONE,
        OwnershipPolicy.CLONE,
    )


def validate_boundary_input(value: object, type_ref: TypeRef) -> object:
    """Validate and normalize one Python value before PyO3 sees it."""

    codec = boundary_codec(type_ref)
    if codec.input_policy == InputPolicy.UNSUPPORTED:
        raise TypeError(
            f"{type_ref.display()} has no lossless supported Python input representation"
        )
    if codec.input_policy == InputPolicy.OPTION:
        if value is None:
            return None
        return validate_boundary_input(value, codec.children[0].type_ref)
    if codec.input_policy == InputPolicy.TUPLE:
        if type(value) is not tuple:
            raise TypeError(f"expected tuple, found {type(value).__name__}")
        if len(value) != len(codec.children):
            raise ValueError(
                f"expected a {len(codec.children)}-item tuple, found {len(value)}"
            )
        converted: list[object] = []
        for index, (item, child) in enumerate(zip(value, codec.children)):
            try:
                converted.append(validate_boundary_input(item, child.type_ref))
            except (OverflowError, TypeError, ValueError) as error:
                raise type(error)(f"tuple item {index}: {error}") from error
        return tuple(converted)
    if codec.input_policy == InputPolicy.SEQUENCE:
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise TypeError(f"expected a Python sequence, found {type(value).__name__}")
        if type_ref.rust_name == "Array" and len(value) != type_ref.const_value:
            raise ValueError(
                f"expected {type_ref.const_value} items, found {len(value)}"
            )
        converted = []
        for index, item in enumerate(value):
            try:
                converted.append(
                    validate_boundary_input(item, codec.children[0].type_ref)
                )
            except (OverflowError, TypeError, ValueError) as error:
                raise type(error)(f"element {index}: {error}") from error
        return converted
    if codec.input_policy == InputPolicy.MAPPING:
        if not isinstance(value, Mapping):
            raise TypeError(f"expected a Python mapping, found {type(value).__name__}")
        converted_mapping: dict[object, object] = {}
        key_codec, value_codec = codec.children
        for index, (key, item) in enumerate(value.items()):
            try:
                converted_key = validate_boundary_input(key, key_codec.type_ref)
            except (OverflowError, TypeError, ValueError) as error:
                raise type(error)(f"mapping key {index}: {error}") from error
            if key_codec.output_policy == OutputPolicy.BYTES:
                converted_key = bytes(cast(list[int], converted_key))
            try:
                converted_value = validate_boundary_input(item, value_codec.type_ref)
            except (OverflowError, TypeError, ValueError) as error:
                raise type(error)(f"mapping value for key {key!r}: {error}") from error
            if converted_key in converted_mapping:
                raise ValueError(
                    f"mapping key {key!r} collides after Rust boundary conversion"
                )
            converted_mapping[converted_key] = converted_value
        return converted_mapping
    if codec.input_policy == InputPolicy.BUFFER:
        _validate_readonly_buffer(value, codec.children[0].type_ref)
        # Keep the original exporter/view intact.  The generated PyO3 wrapper
        # acquires the authoritative buffer lease for the complete native call.
        return value
    if codec.input_policy == InputPolicy.NONE:
        if value is not None:
            raise TypeError(f"expected None, found {type(value).__name__}")
        return None
    return validate_primitive(value, type_ref.rust_name)


_BUFFER_ELEMENT_LAYOUT: dict[str, tuple[str, int]] = {
    "i8": ("signed", 1),
    "i16": ("signed", 2),
    "i32": ("signed", 4),
    "i64": ("signed", 8),
    "u8": ("unsigned", 1),
    "u16": ("unsigned", 2),
    "u32": ("unsigned", 4),
    "u64": ("unsigned", 8),
    "usize": ("unsigned", struct_module.calcsize("P")),
    "isize": ("signed", struct_module.calcsize("P")),
    "f32": ("float", 4),
    "f64": ("float", 8),
}
_BUFFER_FORMAT_KINDS = {
    "b": "signed",
    "h": "signed",
    "i": "signed",
    "l": "signed",
    "q": "signed",
    "n": "signed",
    "B": "unsigned",
    "c": "unsigned",
    "H": "unsigned",
    "I": "unsigned",
    "L": "unsigned",
    "Q": "unsigned",
    "N": "unsigned",
    "f": "float",
    "d": "float",
}


def _validate_readonly_buffer(value: object, element_type: TypeRef) -> None:
    """Preflight the bounded buffer contract without copying any elements."""

    try:
        view = memoryview(cast(Any, value))
    except TypeError as error:
        raise TypeError(
            "expected an object exporting the Python buffer protocol"
        ) from error
    try:
        if view.ndim != 1:
            raise ValueError(
                f"expected a one-dimensional buffer, found {view.ndim} dimensions"
            )
        if not view.c_contiguous:
            raise ValueError("expected a C-contiguous buffer")
        if not view.readonly:
            raise ValueError(
                "expected a read-only buffer; use memoryview(value).toreadonly() "
                "or mark the array non-writeable"
            )
        expected_kind, expected_size = _BUFFER_ELEMENT_LAYOUT[element_type.rust_name]
        format_value = view.format or "B"
        prefix = format_value[0] if format_value[:1] in "@=<>!" else ""
        code = format_value[1:] if prefix else format_value
        actual_kind = _BUFFER_FORMAT_KINDS.get(code)
        if actual_kind != expected_kind or view.itemsize != expected_size:
            raise TypeError(
                f"buffer format {format_value!r} with item size {view.itemsize} "
                f"is incompatible with {element_type.display()}"
            )
        if prefix in {"<", ">", "!"}:
            import sys

            expected_prefix = "<" if sys.byteorder == "little" else ">"
            normalized_prefix = ">" if prefix == "!" else prefix
            if normalized_prefix != expected_prefix:
                raise TypeError(f"buffer format {format_value!r} is not native-endian")
    finally:
        view.release()


def validate_primitive(value: object, rust_name: str) -> object:
    bounds = _INTEGER_RANGES.get(rust_name)
    if bounds is not None:
        if type(value) is not int:
            raise TypeError(
                f"expected int for rust.{rust_name}, found {type(value).__name__}"
            )
        if not bounds[0] <= value <= bounds[1]:
            raise OverflowError(f"{value} is outside the rust.{rust_name} range")
        return value
    if rust_name == "bool":
        if type(value) is not bool:
            raise TypeError(f"expected bool, found {type(value).__name__}")
        return value
    if rust_name == "char":
        if type(value) is not str or len(value) != 1:
            raise TypeError("expected a one-character str for rust.char")
        validate_unicode_value_tree(value)
        return value
    if rust_name in {"String", "Str"}:
        if type(value) is not str:
            raise TypeError(
                f"expected str for rust.{rust_name}, found {type(value).__name__}"
            )
        validate_unicode_value_tree(value)
        return value
    if rust_name in {"f32", "f64"}:
        if type(value) not in {int, float}:
            raise TypeError(
                f"expected int or float for rust.{rust_name}, "
                f"found {type(value).__name__}"
            )
        converted = float(cast(int | float, value))
        if (
            rust_name == "f32"
            and math.isfinite(converted)
            and abs(converted) > 3.4028235e38
        ):
            raise OverflowError(f"{value} is outside the finite rust.f32 range")
        return converted
    raise TypeError(f"rust.{rust_name} is not a supported Python boundary type")


def normalize_boundary_output(value: object, type_ref: TypeRef) -> object:
    """Normalize PyO3 output to Crabwalk's documented Python representation."""

    return _normalize_boundary_output(value, boundary_codec(type_ref))


def _normalize_boundary_output(value: object, codec: BoundaryCodec) -> object:
    """Normalize with one precomputed codec tree.

    Recursive container outputs can contain hundreds of thousands of scalar
    values. Rebuilding the same immutable child codec for every element made the
    Python-side contract check dominate otherwise-small native kernels.
    """

    type_ref = codec.type_ref
    if codec.output_policy == OutputPolicy.UNSUPPORTED:
        raise TypeError(
            f"{type_ref.display()} has no lossless supported Python output representation"
        )
    if codec.output_policy == OutputPolicy.RESULT:
        # The generated ABI wrapper has already translated Err into
        # CrabwalkRustError, so only the successful child reaches Python.
        return _normalize_boundary_output(value, codec.children[0])
    if codec.output_policy == OutputPolicy.NONE:
        return None
    if codec.output_policy == OutputPolicy.OPTION:
        if value is None:
            return None
        return _normalize_boundary_output(value, codec.children[0])
    if codec.output_policy == OutputPolicy.TUPLE:
        if type(value) is not tuple or len(value) != len(codec.children):
            raise TypeError("native tuple output did not match its boundary codec")
        return tuple(
            _normalize_boundary_output(item, child)
            for item, child in zip(value, codec.children)
        )
    if codec.output_policy == OutputPolicy.BYTES:
        if not isinstance(value, (bytes, bytearray, memoryview, list, tuple)):
            raise TypeError("native Vec<u8> output did not produce byte values")
        return bytes(value)
    if codec.output_policy == OutputPolicy.LIST:
        if not isinstance(value, (list, tuple)):
            raise TypeError("native vector output did not produce a sequence")
        child = codec.children[0]
        if child.output_policy == OutputPolicy.SCALAR:
            # PyO3 has already converted each value from one concrete Rust
            # scalar type. Its Vec conversion also created the promised fresh
            # Python list, so another element-by-element codec pass and list
            # allocation would only duplicate trusted ABI work.
            return value if type(value) is list else list(value)
        return [_normalize_boundary_output(item, child) for item in value]
    if codec.output_policy == OutputPolicy.DICT:
        if not isinstance(value, Mapping):
            raise TypeError("native HashMap output did not produce a mapping")
        key_codec, value_codec = codec.children
        return {
            _normalize_boundary_output(key, key_codec): _normalize_boundary_output(
                item, value_codec
            )
            for key, item in value.items()
        }
    if codec.output_policy == OutputPolicy.SCALAR:
        # PyO3 has already converted the native scalar. Reuse the exact input
        # validator so output drift is detected at this shared contract too.
        return validate_primitive(value, type_ref.rust_name)
    return value


def validate_unicode_value_tree(value: object) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ValueError(
                "Rust strings and chars cannot contain an escaped lone surrogate"
            ) from error
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            validate_unicode_value_tree(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            validate_unicode_value_tree(key)
            validate_unicode_value_tree(item)
