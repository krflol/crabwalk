"""Tagged semantic type algebra for Crabwalk's compiler passes.

The public ``TypeRef(...)`` spelling remains as a compatibility factory for
tests and runtime helpers, but every value it creates is one concrete, validated
variant.  Downstream passes can therefore match on semantic variants instead of
inferring meaning from unrelated optional string fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class TypeKind(StrEnum):
    PRIMITIVE = "primitive"
    DOMAIN = "domain"
    ERROR_DOMAIN = "error_domain"
    EXTERNAL = "external"
    GENERIC = "generic"
    LIFETIME_REFERENCE = "lifetime_reference"
    OWNERSHIP = "ownership"
    TUPLE = "tuple"
    ARRAY = "array"
    CONTAINER = "container"
    ITERATOR = "iterator"
    DYNAMIC_TRAIT = "dynamic_trait"
    TRAIT_MARKER = "trait_marker"
    RUNTIME = "runtime"
    UNIT = "unit"
    INFERRED = "inferred"


_PRIMITIVE_NAMES = frozenset(
    {
        "i8",
        "i16",
        "i32",
        "i64",
        "i128",
        "isize",
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
        "Str",
    }
)
_CONTAINER_ARITY: dict[str, int] = {
    "Arc": 1,
    "Buffer": 1,
    "Box": 1,
    "Closure": 2,
    "Future": 1,
    "HashMap": 2,
    "HashSet": 1,
    "BTreeMap": 2,
    "BTreeSet": 1,
    "Slice": 1,
    "Mutex": 1,
    "Option": 1,
    "Rc": 1,
    "Receiver": 1,
    "RefCell": 1,
    "Result": 2,
    "Sender": 1,
    "ThreadHandle": 1,
    "Vec": 1,
}


class IteratorExecution(StrEnum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


class IteratorItemMode(StrEnum):
    OWNED = "owned"
    SHARED_REF = "shared_ref"
    MUTABLE_REF = "mutable_ref"


class IteratorIndexing(StrEnum):
    """Rayon capability retained by one parallel iterator adapter stack."""

    INDEXED = "indexed"
    UNINDEXED = "unindexed"


class _TypeRefMeta(type):
    def __call__(cls, *args: object, **kwargs: object) -> TypeRef:
        if cls is not TypeRef:
            return super().__call__(*args, **kwargs)
        names = (
            "rust_name",
            "arguments",
            "python_name",
            "const_value",
            "is_generic",
            "is_lifetime",
        )
        defaults: list[object] = [None, (), None, None, False, False]
        if len(args) > len(names):
            raise TypeError(f"TypeRef expected at most {len(names)} arguments")
        for index, value in enumerate(args):
            defaults[index] = value
        for name, value in kwargs.items():
            if name not in names:
                raise TypeError(f"TypeRef got an unexpected argument {name!r}")
            index = names.index(name)
            if index < len(args):
                raise TypeError(f"TypeRef got multiple values for {name!r}")
            defaults[index] = value
        rust_name, arguments, python_name, const_value, is_generic, is_lifetime = (
            defaults
        )
        if not isinstance(rust_name, str):
            raise TypeError("TypeRef requires a Rust type name")
        if not isinstance(arguments, tuple) or not all(
            isinstance(value, TypeRef) for value in arguments
        ):
            raise TypeError("TypeRef arguments must be a tuple of TypeRef values")
        if python_name is not None and not isinstance(python_name, str):
            raise TypeError("TypeRef python_name must be a string or None")
        if const_value is not None and not isinstance(const_value, int):
            raise TypeError("TypeRef const_value must be an integer or None")
        if not isinstance(is_generic, bool) or not isinstance(is_lifetime, bool):
            raise TypeError("TypeRef generic flags must be bool values")
        return _legacy_type_ref(
            rust_name,
            arguments,
            python_name,
            const_value,
            is_generic,
            is_lifetime,
        )


class TypeRef(metaclass=_TypeRefMeta):
    """Base class and compatibility factory for tagged semantic types."""

    __slots__ = ()
    kind: TypeKind

    def __init__(
        self,
        rust_name: str,
        arguments: tuple[TypeRef, ...] = (),
        python_name: str | None = None,
        const_value: int | None = None,
        is_generic: bool = False,
        is_lifetime: bool = False,
    ) -> None:
        """Describe the compatibility factory to static type checkers.

        ``_TypeRefMeta.__call__`` handles direct ``TypeRef(...)`` construction and
        returns one of the tagged variants before this initializer is reached.
        Concrete dataclass variants generate their own initializers. Keeping the
        public factory signature here makes that compatibility surface visible to
        PEP 561 consumers.
        """

        del rust_name, arguments, python_name, const_value, is_generic, is_lifetime

    @property
    def rust_name(self) -> str:
        raise NotImplementedError

    @property
    def arguments(self) -> tuple[TypeRef, ...]:
        return ()

    @property
    def python_name(self) -> str | None:
        return None

    @property
    def const_value(self) -> int | None:
        return None

    @property
    def is_generic(self) -> bool:
        return False

    @property
    def is_lifetime(self) -> bool:
        return False

    def with_arguments(self, arguments: tuple[TypeRef, ...]) -> TypeRef:
        """Rebuild one composite variant after recursive type substitution."""

        return _legacy_type_ref(
            self.rust_name,
            arguments,
            self.python_name,
            self.const_value,
            self.is_generic,
            self.is_lifetime,
        )

    def render(self) -> str:
        """Render through the Rust backend compatibility entry point."""

        from .type_rendering import render_rust_type

        return render_rust_type(self)

    def display(self) -> str:
        if isinstance(self, LifetimeReferenceType):
            return f"rust.Borrow[{self.lifetime_name}, {self.target.display()}]"
        if isinstance(self, GenericParameterType):
            return f"'{self.name}" if self.lifetime_parameter else self.name
        if self.python_name is not None:
            return self.python_name
        if isinstance(self, UnitType):
            return "None"
        if isinstance(self, TupleType):
            values = ", ".join(value.display() for value in self.items)
            return f"rust.Tuple[{values}]"
        if isinstance(self, ArrayType):
            return f"rust.Array[{self.item.display()}, {self.length}]"
        if isinstance(self, IteratorType):
            capabilities: str = self.item_mode
            if self.indexing is not None:
                capabilities = f"{capabilities},{self.indexing}"
            return (
                f"rust.{self.rust_name}[{self.exposed_item_type.display()}]"
                f"<{capabilities}>"
            )
        if not self.arguments:
            return f"rust.{self.rust_name}"
        values = ", ".join(value.display() for value in self.arguments)
        return f"rust.{self.rust_name}[{values}]"

    @property
    def ownership(self) -> str | None:
        return self.ownership_kind if isinstance(self, OwnershipType) else None

    @property
    def underlying(self) -> TypeRef:
        if isinstance(self, OwnershipType):
            return self.inner
        if isinstance(self, LifetimeReferenceType):
            return self.target
        return self

    @property
    def lifetime(self) -> str | None:
        return self.lifetime_name if isinstance(self, LifetimeReferenceType) else None

    @property
    def is_integer(self) -> bool:
        return self.rust_name in {
            "i8",
            "i16",
            "i32",
            "i64",
            "i128",
            "isize",
            "u8",
            "u16",
            "u32",
            "u64",
            "u128",
            "usize",
        }

    @property
    def is_signed_integer(self) -> bool:
        return self.rust_name.startswith("i")

    @property
    def is_float(self) -> bool:
        return self.rust_name in {"f32", "f64"}

    @property
    def is_numeric(self) -> bool:
        return self.is_integer or self.is_float


@dataclass(frozen=True, slots=True)
class PrimitiveType(TypeRef):
    name: str
    kind: TypeKind = TypeKind.PRIMITIVE

    def __post_init__(self) -> None:
        if self.name not in _PRIMITIVE_NAMES:
            raise ValueError(f"unknown primitive type: {self.name}")

    @property
    def rust_name(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class DomainType(TypeRef):
    symbol: str
    qualified_name: str
    kind: TypeKind = TypeKind.DOMAIN

    @property
    def rust_name(self) -> str:
        return self.symbol

    @property
    def python_name(self) -> str:
        return self.qualified_name

    def with_arguments(self, arguments: tuple[TypeRef, ...]) -> TypeRef:
        if arguments:
            raise ValueError("domain types cannot carry type arguments")
        return self


@dataclass(frozen=True, slots=True)
class ErrorDomainType(TypeRef):
    """A generated enum that implements Rust's structured error contract."""

    symbol: str
    qualified_name: str
    kind: TypeKind = TypeKind.ERROR_DOMAIN

    @property
    def rust_name(self) -> str:
        return self.symbol

    @property
    def python_name(self) -> str:
        return self.qualified_name

    def with_arguments(self, arguments: tuple[TypeRef, ...]) -> TypeRef:
        if arguments:
            raise ValueError("error domain types cannot carry type arguments")
        return self


@dataclass(frozen=True, slots=True)
class ExternalType(TypeRef):
    """One crate-owned Rust type declared through a static adapter."""

    crate_binding: str
    path: tuple[str, ...]
    source_name: str
    kind: TypeKind = TypeKind.EXTERNAL

    def __post_init__(self) -> None:
        if not self.crate_binding or not self.path:
            raise ValueError("external types require a crate binding and path")

    @property
    def rust_name(self) -> str:
        return "::".join((self.crate_binding, *self.path))

    def render(self) -> str:
        return self.rust_name

    def display(self) -> str:
        return self.source_name


@dataclass(frozen=True, slots=True)
class GenericParameterType(TypeRef):
    name: str
    lifetime_parameter: bool = False
    emitted_name: str | None = None
    kind: TypeKind = TypeKind.GENERIC

    @property
    def rust_name(self) -> str:
        return self.emitted_name or self.name

    @property
    def is_generic(self) -> bool:
        return True

    @property
    def is_lifetime(self) -> bool:
        return self.lifetime_parameter


@dataclass(frozen=True, slots=True)
class LifetimeReferenceType(TypeRef):
    lifetime_name: str
    target: TypeRef
    emitted_lifetime: str | None = None
    kind: TypeKind = TypeKind.LIFETIME_REFERENCE

    @property
    def rust_name(self) -> str:
        return "LifetimeRef"

    @property
    def arguments(self) -> tuple[TypeRef, ...]:
        return (self.target,)

    @property
    def python_name(self) -> str:
        return self.lifetime_name

    @property
    def rendered_lifetime(self) -> str:
        return self.emitted_lifetime or self.lifetime_name

    def with_arguments(self, arguments: tuple[TypeRef, ...]) -> TypeRef:
        if len(arguments) != 1:
            raise ValueError("LifetimeRef requires exactly one target")
        return LifetimeReferenceType(
            self.lifetime_name,
            arguments[0],
            self.emitted_lifetime,
        )


@dataclass(frozen=True, slots=True)
class OwnershipType(TypeRef):
    ownership_kind: Literal["Owned", "Ref", "Mut", "Shared"]
    inner: TypeRef
    kind: TypeKind = TypeKind.OWNERSHIP

    @property
    def rust_name(self) -> str:
        return self.ownership_kind

    @property
    def arguments(self) -> tuple[TypeRef, ...]:
        return (self.inner,)


@dataclass(frozen=True, slots=True)
class TupleType(TypeRef):
    items: tuple[TypeRef, ...]
    kind: TypeKind = TypeKind.TUPLE

    @property
    def rust_name(self) -> str:
        return "Tuple"

    @property
    def arguments(self) -> tuple[TypeRef, ...]:
        return self.items


@dataclass(frozen=True, slots=True)
class ArrayType(TypeRef):
    item: TypeRef
    length: int
    kind: TypeKind = TypeKind.ARRAY

    def __post_init__(self) -> None:
        if self.length < 0:
            raise ValueError("array length must be non-negative")

    @property
    def rust_name(self) -> str:
        return "Array"

    @property
    def arguments(self) -> tuple[TypeRef, ...]:
        return (self.item,)

    @property
    def const_value(self) -> int:
        return self.length


@dataclass(frozen=True, slots=True)
class ContainerType(TypeRef):
    constructor: str
    items: tuple[TypeRef, ...]
    kind: TypeKind = TypeKind.CONTAINER

    def __post_init__(self) -> None:
        expected = _CONTAINER_ARITY.get(self.constructor)
        if expected is None:
            raise ValueError(f"unknown semantic container: {self.constructor}")
        if len(self.items) != expected:
            raise ValueError(
                f"{self.constructor} expects {expected} type argument(s), "
                f"found {len(self.items)}"
            )

    @property
    def rust_name(self) -> str:
        return self.constructor

    @property
    def arguments(self) -> tuple[TypeRef, ...]:
        return self.items


@dataclass(frozen=True, slots=True)
class IteratorType(TypeRef):
    execution: IteratorExecution
    item_type: TypeRef
    item_mode: IteratorItemMode = IteratorItemMode.OWNED
    indexing: IteratorIndexing | None = None
    kind: TypeKind = TypeKind.ITERATOR

    def __post_init__(self) -> None:
        if self.execution == IteratorExecution.SEQUENTIAL:
            if self.indexing is not None:
                raise ValueError("sequential iterators cannot carry Rayon indexing")
            return
        if self.indexing is None:
            raise ValueError("parallel iterators require an indexing capability")

    @property
    def rust_name(self) -> str:
        if self.execution == IteratorExecution.SEQUENTIAL:
            return "Iterator"
        if self.item_mode == IteratorItemMode.SHARED_REF:
            return "ParallelIteratorRef"
        return "ParallelIterator"

    @property
    def arguments(self) -> tuple[TypeRef, ...]:
        return (self.item_type,)

    @property
    def exposed_item_type(self) -> TypeRef:
        if self.item_mode == IteratorItemMode.SHARED_REF:
            return OwnershipType("Ref", self.item_type)
        if self.item_mode == IteratorItemMode.MUTABLE_REF:
            return OwnershipType("Mut", self.item_type)
        return self.item_type

    def with_arguments(self, arguments: tuple[TypeRef, ...]) -> TypeRef:
        if len(arguments) != 1:
            raise ValueError("iterator types require exactly one item type")
        return IteratorType(
            self.execution,
            arguments[0],
            self.item_mode,
            self.indexing,
        )


@dataclass(frozen=True, slots=True)
class DynamicTraitType(TypeRef):
    trait_symbol: str
    kind: TypeKind = TypeKind.DYNAMIC_TRAIT

    @property
    def rust_name(self) -> str:
        return "Dyn"

    @property
    def python_name(self) -> str:
        return self.trait_symbol


@dataclass(frozen=True, slots=True)
class TraitMarkerType(TypeRef):
    trait_symbol: str
    kind: TypeKind = TypeKind.TRAIT_MARKER

    @property
    def rust_name(self) -> str:
        return "Trait"

    @property
    def python_name(self) -> str:
        return self.trait_symbol


@dataclass(frozen=True, slots=True)
class RuntimeType(TypeRef):
    name: str
    items: tuple[TypeRef, ...] = ()
    kind: TypeKind = TypeKind.RUNTIME

    @property
    def rust_name(self) -> str:
        return self.name

    @property
    def arguments(self) -> tuple[TypeRef, ...]:
        return self.items


@dataclass(frozen=True, slots=True)
class UnitType(TypeRef):
    kind: TypeKind = TypeKind.UNIT

    @property
    def rust_name(self) -> str:
        return "Unit"


@dataclass(frozen=True, slots=True)
class InferredType(TypeRef):
    kind: TypeKind = TypeKind.INFERRED

    @property
    def rust_name(self) -> str:
        return "_"


def _legacy_type_ref(
    rust_name: str,
    arguments: tuple[TypeRef, ...],
    python_name: str | None,
    const_value: int | None,
    is_generic: bool,
    is_lifetime: bool,
) -> TypeRef:
    if is_generic:
        if arguments or python_name is not None or const_value is not None:
            raise ValueError("generic parameters cannot carry type payload state")
        return GenericParameterType(rust_name, is_lifetime)
    if is_lifetime:
        raise ValueError("is_lifetime is valid only for generic parameters")
    if rust_name == "LifetimeRef":
        if len(arguments) != 1 or python_name is None or const_value is not None:
            raise ValueError("LifetimeRef requires one target and one lifetime name")
        return LifetimeReferenceType(python_name, arguments[0])
    if rust_name in {"Owned", "Ref", "Mut", "Shared"}:
        if len(arguments) != 1 or python_name is not None or const_value is not None:
            raise ValueError(f"{rust_name} requires exactly one inner type")
        return OwnershipType(rust_name, arguments[0])  # type: ignore[arg-type]
    if rust_name in _PRIMITIVE_NAMES:
        if arguments or python_name is not None or const_value is not None:
            raise ValueError(f"primitive {rust_name} cannot carry type payload state")
        return PrimitiveType(rust_name)
    if rust_name == "Unit":
        if arguments or python_name is not None or const_value is not None:
            raise ValueError("Unit cannot carry type payload state")
        return UnitType()
    if rust_name == "_":
        if arguments or python_name is not None or const_value is not None:
            raise ValueError("inferred type cannot carry type payload state")
        return InferredType()
    if rust_name == "Tuple":
        if python_name is not None or const_value is not None:
            raise ValueError("Tuple carries only item types")
        return TupleType(arguments)
    if rust_name == "Array":
        if len(arguments) != 1 or const_value is None or python_name is not None:
            raise ValueError("Array requires one item type and a fixed length")
        return ArrayType(arguments[0], const_value)
    if rust_name == "Dyn":
        if arguments or python_name is None or const_value is not None:
            raise ValueError("Dyn requires one trait symbol")
        return DynamicTraitType(python_name)
    if rust_name in {"Iterator", "ParallelIterator", "ParallelIteratorRef"}:
        if len(arguments) != 1 or python_name is not None or const_value is not None:
            raise ValueError(f"{rust_name} requires exactly one item type")
        item = arguments[0]
        mode = IteratorItemMode.OWNED
        if rust_name == "Iterator" and isinstance(item, OwnershipType):
            mode = (
                IteratorItemMode.SHARED_REF
                if item.ownership_kind == "Ref"
                else IteratorItemMode.MUTABLE_REF
                if item.ownership_kind == "Mut"
                else IteratorItemMode.OWNED
            )
            item = item.inner
        elif rust_name == "ParallelIteratorRef":
            mode = IteratorItemMode.SHARED_REF
        execution = (
            IteratorExecution.SEQUENTIAL
            if rust_name == "Iterator"
            else IteratorExecution.PARALLEL
        )
        indexing = (
            None
            if execution == IteratorExecution.SEQUENTIAL
            else IteratorIndexing.UNINDEXED
        )
        return IteratorType(execution, item, mode, indexing)
    if rust_name == "Trait":
        if arguments or python_name is None or const_value is not None:
            raise ValueError("Trait marker requires one trait symbol")
        return TraitMarkerType(python_name)
    if rust_name in _CONTAINER_ARITY:
        if python_name is not None or const_value is not None:
            raise ValueError(f"{rust_name} carries only type arguments")
        return ContainerType(rust_name, arguments)
    if python_name is not None:
        if arguments or const_value is not None:
            raise ValueError("domain types cannot carry legacy payload state")
        return DomainType(rust_name, python_name)
    if const_value is not None:
        raise ValueError(f"{rust_name} cannot carry a const value")
    return RuntimeType(rust_name, arguments)


I64 = PrimitiveType("i64")
U64 = PrimitiveType("u64")
USIZE = PrimitiveType("usize")
F64 = PrimitiveType("f64")
BOOL = PrimitiveType("bool")
CHAR = PrimitiveType("char")
STRING = PrimitiveType("String")
STR = PrimitiveType("Str")
UNIT = UnitType()
INFERRED = InferredType()
