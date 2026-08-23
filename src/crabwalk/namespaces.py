"""Shared Python and generated-pyclass namespace contracts.

The compiler imports these constants without importing the runtime. Runtime
tests compare them with the concrete wrapper/marker objects so adding a Python
member cannot silently make a domain field or enum variant unreachable.
"""

from __future__ import annotations

PYTHON_OBJECT_INSTANCE_NAMES = frozenset(dir(object()))
# Keep one conservative cross-version contract for every supported CPython lane.
# Python 3.12-3.14 added several introspection members to user-defined classes;
# reserving them on older lanes avoids a field changing meaning after a Python
# upgrade. See https://docs.python.org/3/reference/datamodel.html#custom-classes.
PYTHON_USER_CLASS_RESERVED_NAMES = frozenset(
    {
        "__annotate__",
        "__annotations__",
        "__base__",
        "__bases__",
        "__dict__",
        "__doc__",
        "__firstlineno__",
        "__module__",
        "__mro__",
        "__name__",
        "__qualname__",
        "__replace__",
        "__static_attributes__",
        "__type_params__",
    }
)
PYTHON_INSTANCE_RESERVED_NAMES = (
    PYTHON_OBJECT_INSTANCE_NAMES | PYTHON_USER_CLASS_RESERVED_NAMES
)

GENERATED_STRUCT_PYCLASS_MEMBERS = frozenset(
    {"new", "to_python", "is_moved", "__repr__"}
)
GENERATED_ENUM_PYCLASS_MEMBERS = frozenset({"variant", "is_moved", "__repr__"})

OWNED_VALUE_RESERVED_NAMES = PYTHON_INSTANCE_RESERVED_NAMES | frozenset(
    {
        "__copy__",
        "__deepcopy__",
        "__getattr__",
        "__len__",
        "__module__",
        "__slots__",
        "_borrow_contexts",
        "_check_thread",
        "_definition_site",
        "_enum_variants",
        "_field_names",
        "_move_site",
        "_native",
        "_record_move",
        "_thread_id",
        "_type_key",
        "moved",
        "rust_type",
        "to_python",
    }
)

ENUM_MARKER_RESERVED_NAMES = PYTHON_INSTANCE_RESERVED_NAMES | frozenset(
    {
        "__annotations__",
        "__call__",
        "__dataclass_fields__",
        "__dataclass_params__",
        "__getattr__",
        "__match_args__",
        "__module__",
        "__setstate__",
        "__slots__",
        "arguments",
        "const_value",
        "is_generic",
        "is_lifetime",
        "name",
        "python_name",
        "rust_key",
        "variants",
    }
)

STRUCT_FIELD_RESERVED_NAMES = (
    GENERATED_STRUCT_PYCLASS_MEMBERS | OWNED_VALUE_RESERVED_NAMES
)
ENUM_FIELD_RESERVED_NAMES = GENERATED_ENUM_PYCLASS_MEMBERS | OWNED_VALUE_RESERVED_NAMES
ENUM_VARIANT_RESERVED_NAMES = (
    GENERATED_ENUM_PYCLASS_MEMBERS | ENUM_MARKER_RESERVED_NAMES
)
