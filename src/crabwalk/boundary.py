"""One explicit Python/native conversion contract for every Crabwalk boundary."""

from __future__ import annotations

import math
import struct as struct_module
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

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
    RUST_HANDLE = "RustHandle"
    UNSUPPORTED = "Unsupported"


class OutputPolicy(StrEnum):
    SCALAR = "Scalar"
    NONE = "None"
    OPTION = "Option"
    TUPLE = "Tuple"
    LIST = "List"
    BYTES = "Bytes"
    RUST_HANDLE = "RustHandle"
    UNSUPPORTED = "Unsupported"


class AllocationKind(StrEnum):
    NONE = "None"
    PYTHON_CONTAINER = "PythonContainer"
    NATIVE_CONTAINER = "NativeContainer"
    OWNED_HANDLE = "OwnedHandle"


class OwnershipPolicy(StrEnum):
    COPY = "Copy"
    CLONE = "Clone"
    MOVE = "Move"
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
    if type_ref.rust_name in {"String", "Str"}:
        return BoundaryCodec(
            type_ref,
            InputPolicy.STRING,
            OutputPolicy.SCALAR,
            AllocationKind.NATIVE_CONTAINER,
            OwnershipPolicy.CLONE,
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
    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        return BoundaryCodec(
            type_ref,
            InputPolicy.OPTION,
            OutputPolicy.OPTION,
            AllocationKind.NONE,
            OwnershipPolicy.CLONE,
            (boundary_codec(type_ref.arguments[0]),),
        )
    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        return BoundaryCodec(
            type_ref,
            InputPolicy.TUPLE,
            OutputPolicy.TUPLE,
            AllocationKind.PYTHON_CONTAINER,
            OwnershipPolicy.CLONE,
            tuple(boundary_codec(value) for value in type_ref.arguments),
        )
    if type_ref.rust_name in {"Vec", "Array"} and type_ref.arguments:
        byte_vector = (
            type_ref.rust_name == "Vec" and type_ref.arguments[0].rust_name == "u8"
        )
        return BoundaryCodec(
            type_ref,
            InputPolicy.SEQUENCE,
            OutputPolicy.BYTES if byte_vector else OutputPolicy.LIST,
            AllocationKind.PYTHON_CONTAINER,
            OwnershipPolicy.CLONE,
            (boundary_codec(type_ref.arguments[0]),),
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
        if not isinstance(value, Sequence):
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
    if codec.input_policy == InputPolicy.NONE:
        if value is not None:
            raise TypeError(f"expected None, found {type(value).__name__}")
        return None
    return validate_primitive(value, type_ref.rust_name)


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

    codec = boundary_codec(type_ref)
    if codec.output_policy == OutputPolicy.NONE:
        return None
    if codec.output_policy == OutputPolicy.OPTION:
        if value is None:
            return None
        return normalize_boundary_output(value, codec.children[0].type_ref)
    if codec.output_policy == OutputPolicy.TUPLE:
        if type(value) is not tuple or len(value) != len(codec.children):
            raise TypeError("native tuple output did not match its boundary codec")
        return tuple(
            normalize_boundary_output(item, child.type_ref)
            for item, child in zip(value, codec.children)
        )
    if codec.output_policy == OutputPolicy.BYTES:
        if not isinstance(value, (bytes, bytearray, memoryview, list, tuple)):
            raise TypeError("native Vec<u8> output did not produce byte values")
        return bytes(value)
    if codec.output_policy == OutputPolicy.LIST:
        if not isinstance(value, (list, tuple)):
            raise TypeError("native vector output did not produce a sequence")
        return [
            normalize_boundary_output(item, codec.children[0].type_ref)
            for item in value
        ]
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
