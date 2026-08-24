from __future__ import annotations

import pytest

from crabwalk.boundary import (
    AllocationKind,
    InputPolicy,
    OutputPolicy,
    OwnershipPolicy,
    boundary_codec,
    normalize_boundary_output,
    validate_boundary_input,
)
from crabwalk.compiler.ir import TypeRef


def test_vec_u8_has_one_deliberate_bytes_codec() -> None:
    type_ref = TypeRef("Vec", (TypeRef("u8"),))

    codec = boundary_codec(type_ref)

    assert codec.input_policy == InputPolicy.SEQUENCE
    assert codec.output_policy == OutputPolicy.BYTES
    assert codec.allocation == AllocationKind.PYTHON_CONTAINER
    assert codec.ownership == OwnershipPolicy.CLONE
    assert validate_boundary_input(b"\x00\xff", type_ref) == [0, 255]
    assert normalize_boundary_output([0, 255], type_ref) == b"\x00\xff"


def test_other_vectors_normalize_to_new_python_lists() -> None:
    type_ref = TypeRef("Vec", (TypeRef("u64"),))

    codec = boundary_codec(type_ref)

    assert codec.output_policy == OutputPolicy.LIST
    source = (1, 2, 3)
    converted = normalize_boundary_output(source, type_ref)
    assert converted == [1, 2, 3]
    assert converted is not source


@pytest.mark.parametrize("value", [True, False])
def test_integer_codec_rejects_bool_consistently(value: bool) -> None:
    with pytest.raises(TypeError, match="expected int for rust.u64"):
        validate_boundary_input(value, TypeRef("u64"))


def test_nested_tuple_and_option_use_the_same_recursive_codec() -> None:
    type_ref = TypeRef(
        "Tuple",
        (TypeRef("u64"), TypeRef("Option", (TypeRef("Vec", (TypeRef("u8"),)),))),
    )

    assert validate_boundary_input((7, b"abc"), type_ref) == (7, [97, 98, 99])
    assert normalize_boundary_output((7, [97, 98, 99]), type_ref) == (7, b"abc")
