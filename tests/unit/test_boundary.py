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
from crabwalk.compiler.abi import (
    BoundaryPosition,
    boundary_shape,
    python_mapping_key_supported,
    python_return_boundary_supported,
)
from crabwalk.compiler.ir import TypeRef
from crabwalk.runtime import _boundary_metadata


def test_str_codec_reports_the_generated_call_scoped_borrow() -> None:
    type_ref = TypeRef("Str")

    codec = boundary_codec(type_ref)

    assert codec.input_policy == InputPolicy.STRING
    assert codec.output_policy == OutputPolicy.UNSUPPORTED
    assert codec.allocation == AllocationKind.BORROWED
    assert codec.ownership == OwnershipPolicy.BORROW
    assert _boundary_metadata(type_ref) == {
        "rust_type": "rust.Str",
        "input_policy": "String",
        "allocation": "Borrowed",
        "ownership": "Borrow",
        "borrowed": True,
        "copies_elements": False,
        "lifetime": "native call",
    }


def test_vec_u8_has_one_deliberate_bytes_codec() -> None:
    type_ref = TypeRef("Vec", (TypeRef("u8"),))

    codec = boundary_codec(type_ref)

    assert codec.input_policy == InputPolicy.SEQUENCE
    assert codec.output_policy == OutputPolicy.BYTES
    assert codec.allocation == AllocationKind.PYTHON_CONTAINER
    assert codec.ownership == OwnershipPolicy.CLONE
    assert validate_boundary_input(b"\x00\xff", type_ref) == [0, 255]
    assert normalize_boundary_output([0, 255], type_ref) == b"\x00\xff"


def test_other_vectors_reuse_pyo3_lists_or_normalize_other_sequences() -> None:
    type_ref = TypeRef("Vec", (TypeRef("u64"),))

    codec = boundary_codec(type_ref)

    assert codec.output_policy == OutputPolicy.LIST
    source = (1, 2, 3)
    converted = normalize_boundary_output(source, type_ref)
    assert converted == [1, 2, 3]
    assert converted is not source

    # PyO3 already allocated and typed this list while converting Vec<u64>.
    # The runtime does not duplicate that trusted native-boundary work.
    native_list = [1, 2, 3]
    assert normalize_boundary_output(native_list, type_ref) is native_list


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


def test_hashmap_input_validates_recursive_keys_values_and_paths() -> None:
    string_map = TypeRef("HashMap", (TypeRef("String"), TypeRef("u64")))
    bytes_map = TypeRef(
        "HashMap",
        (TypeRef("Vec", (TypeRef("u8"),)), TypeRef("u64")),
    )

    assert validate_boundary_input({"active": 3}, string_map) == {"active": 3}
    assert validate_boundary_input({b"active": 3}, bytes_map) == {b"active": 3}
    with pytest.raises(TypeError, match="mapping value for key 'active'"):
        validate_boundary_input({"active": True}, string_map)


@pytest.mark.parametrize(
    "type_ref",
    (
        TypeRef("Option", (TypeRef("Option", (TypeRef("String"),)),)),
        TypeRef("Option", (TypeRef("Unit"),)),
    ),
)
def test_non_injective_option_shapes_have_no_boundary_codec(
    type_ref: TypeRef,
) -> None:
    shape = boundary_shape(type_ref, position=BoundaryPosition.NESTED)

    assert not shape.input_supported
    assert not shape.output_supported
    assert not shape.injective
    assert shape.can_equal_none
    assert not python_mapping_key_supported(type_ref)
    with pytest.raises(TypeError, match="no lossless supported Python input"):
        validate_boundary_input(None, type_ref)
    with pytest.raises(TypeError, match="no lossless supported Python output"):
        normalize_boundary_output(None, type_ref)


def test_result_is_only_a_top_level_return_control_type() -> None:
    result = TypeRef("Result", (TypeRef("u64"), TypeRef("String")))
    nested = TypeRef("Option", (result,))
    nested_success = TypeRef("Result", (result, TypeRef("String")))

    assert python_return_boundary_supported(result)
    assert not python_return_boundary_supported(nested)
    assert not python_return_boundary_supported(nested_success)


def test_result_success_uses_the_child_output_codec() -> None:
    result = TypeRef(
        "Result",
        (TypeRef("Vec", (TypeRef("u8"),)), TypeRef("String")),
    )

    assert normalize_boundary_output([0, 255], result) == b"\x00\xff"
