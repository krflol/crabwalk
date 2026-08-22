from __future__ import annotations

import pytest

from crabwalk import rust


def test_native_only_decorators_preserve_metadata_and_reject_python_calls() -> None:
    item = rust.typevar("Item")

    @rust.generic(item, bounds=[rust.Copy])
    def generic_identity(value: object) -> object:
        """Native helper documentation."""

        return value

    @rust.method(rust.u64, name="value")
    def inherent_method(value: object) -> object:
        return value

    @rust.impl(rust.Display, rust.u64, name="display")
    def trait_impl(value: object) -> object:
        return value

    @rust.operator(rust.u64, name="add")
    def operator_impl(left: object, right: object) -> object:
        return left

    @rust.async_fn
    async def async_helper() -> int:
        return 1

    declarations = (
        generic_identity,
        inherent_method,
        trait_impl,
        operator_impl,
        async_helper,
    )
    assert all(isinstance(value, rust.NativeOnlyFunction) for value in declarations)
    assert generic_identity.__name__ == "generic_identity"
    assert generic_identity.__doc__ == "Native helper documentation."
    assert generic_identity.__crabwalk_declaration__["kind"] == "generic"
    assert generic_identity.__crabwalk_declaration__["type_parameters"] == (item,)

    for declaration in declarations:
        with pytest.raises(RuntimeError, match="native-only Crabwalk"):
            declaration()
