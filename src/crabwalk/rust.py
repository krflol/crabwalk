"""The author-facing Rust semantic namespace.

Objects in this module are compiler markers. They are not Python
reimplementations of their Rust namesakes.
"""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from functools import update_wrapper
from typing import Callable, Literal, TypeVar, overload


@dataclass(frozen=True, slots=True)
class RustType:
    name: str
    arguments: tuple["RustType", ...] = ()
    python_name: str | None = None
    variants: tuple[str, ...] = ()
    const_value: int | None = None
    is_generic: bool = False
    is_lifetime: bool = False
    compilation_fingerprint: str | None = None
    is_error: bool = False

    def __repr__(self) -> str:
        if self.is_generic:
            return f"'{self.name}" if self.is_lifetime else self.name
        if self.python_name is not None:
            return self.python_name
        if not self.arguments:
            return f"rust.{self.name}"
        if self.name == "Array":
            return f"rust.Array[{self.arguments[0]!r}, {self.const_value}]"
        values = ", ".join(repr(value) for value in self.arguments)
        return f"rust.{self.name}[{values}]"

    def __call__(self, *values: object, **keywords: object) -> object:
        from .runtime import construct_rust_value

        return construct_rust_value(self, values, keywords)

    def __getattr__(self, name: str) -> "RustVariantConstructor":
        if name in self.variants:
            return RustVariantConstructor(self, name)
        raise AttributeError(name)

    def rust_key(self) -> str:
        if self.name == "TextColumn":
            return "__CwTextColumn"
        if self.name == "LifetimeRef":
            target = self.arguments[0]
            rendered = "str" if target.name == "Str" else target.rust_key()
            return f"&'{self.python_name} {rendered}"
        if self.name == "Str":
            return "&str"
        if self.name == "Tuple":
            values = ", ".join(value.rust_key() for value in self.arguments)
            return f"({values}{',' if len(self.arguments) == 1 else ''})"
        if self.name == "Array":
            return f"[{self.arguments[0].rust_key()}; {self.const_value}]"
        if not self.arguments:
            return self.name
        values = ", ".join(value.rust_key() for value in self.arguments)
        return f"{self.name}<{values}>"


@dataclass(frozen=True, slots=True)
class RustGeneric:
    name: str
    arity: int

    def __getitem__(self, values: RustType | tuple[RustType, ...]) -> RustType:
        arguments = values if isinstance(values, tuple) else (values,)
        if len(arguments) != self.arity or not all(
            isinstance(value, RustType) for value in arguments
        ):
            raise TypeError(
                f"rust.{self.name} expects {self.arity} Rust type argument(s)"
            )
        return RustType(self.name, arguments)

    def __call__(self, *values: object, **keywords: object) -> object:
        if self.name != "Vec":
            raise RuntimeError(
                f"rust.{self.name} is available only inside compiled @rust.fn code"
            )
        from .runtime import construct_inferred_vector

        return construct_inferred_vector(values, keywords)

    def __repr__(self) -> str:
        return f"rust.{self.name}"


@dataclass(frozen=True, slots=True)
class RustTupleGeneric:
    def __getitem__(self, values: RustType | tuple[RustType, ...]) -> RustType:
        arguments = values if isinstance(values, tuple) else (values,)
        if not arguments or not all(isinstance(value, RustType) for value in arguments):
            raise TypeError("rust.Tuple expects one or more Rust type arguments")
        return RustType("Tuple", arguments)

    def __repr__(self) -> str:
        return "rust.Tuple"


@dataclass(frozen=True, slots=True)
class RustArrayGeneric:
    def __getitem__(self, values: tuple[object, object]) -> RustType:
        if (
            not isinstance(values, tuple)
            or len(values) != 2
            or not isinstance(values[0], RustType)
            or type(values[1]) is not int
            or values[1] <= 0
        ):
            raise TypeError("rust.Array expects [RustType, positive_length]")
        return RustType("Array", (values[0],), const_value=values[1])

    def __repr__(self) -> str:
        return "rust.Array"


@dataclass(frozen=True, slots=True)
class RustBorrowGeneric:
    def __getitem__(self, values: tuple[object, object]) -> RustType:
        if (
            not isinstance(values, tuple)
            or len(values) != 2
            or not isinstance(values[0], RustType)
            or not values[0].is_lifetime
            or not isinstance(values[1], RustType)
        ):
            raise TypeError("rust.Borrow expects [rust lifetime, RustType]")
        return RustType(
            "LifetimeRef",
            (values[1],),
            python_name=values[0].name,
        )

    def __repr__(self) -> str:
        return "rust.Borrow"


@dataclass(frozen=True, slots=True)
class RustVariantConstructor:
    enum_type: RustType
    name: str

    def __call__(self, *values: object, **keywords: object) -> object:
        from .runtime import construct_rust_variant

        return construct_rust_variant(self.enum_type, self.name, values, keywords)


@dataclass(frozen=True, slots=True)
class VariantDeclaration:
    positional: tuple[object, ...]
    named: tuple[tuple[str, object], ...]
    from_source: object | None = None


@dataclass(frozen=True, slots=True)
class RustTraitMethod:
    """Static signature for one Crabwalk-declared Rust trait method."""

    return_type: RustType
    parameters: tuple[RustType, ...] = ()
    receiver: Literal["ref", "mut", "owned"] = "ref"
    type_parameters: tuple[RustType, ...] = ()
    bounds: tuple[tuple[RustType, tuple["RustTrait", ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class RustTrait:
    """A marker for a Rust trait used in a native generic bound."""

    name: str
    methods: tuple[tuple[str, RustTraitMethod], ...] = ()
    crate: "Crate | None" = None
    path: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return f"rust.{self.name}"


@dataclass(frozen=True, slots=True)
class RustPath:
    crate_name: str
    path: tuple[str, ...]

    def __getattr__(self, name: str) -> "RustPath":
        return RustPath(self.crate_name, (*self.path, name))

    def __call__(self, *values: object, **keywords: object) -> object:
        del values, keywords
        qualified = ".".join((self.crate_name, *self.path))
        raise RuntimeError(
            f"{qualified} is available only inside compiled @rust.fn code"
        )


@dataclass(frozen=True, slots=True)
class Crate:
    package: str
    binding: str
    version: str | None
    features: tuple[str, ...]
    path: str | None
    git: str | None
    rev: str | None

    def __getattr__(self, name: str) -> RustPath:
        return RustPath(self.binding, (name,))


@dataclass(frozen=True, slots=True)
class RustEffect:
    """A reviewable effect promise attached to one typed crate adapter."""

    name: str


Pure = RustEffect("Pure")
PythonRuntime = RustEffect("PythonRuntime")
Blocking = RustEffect("Blocking")
ThreadSpawn = RustEffect("ThreadSpawn")
GlobalMutation = RustEffect("GlobalMutation")
UnsafeMemory = RustEffect("UnsafeMemory")
UnsafeFfi = RustEffect("UnsafeFfi")
MayPanic = RustEffect("MayPanic")
OpaqueCrateCall = RustEffect("OpaqueCrateCall")


@dataclass(frozen=True, slots=True)
class RustDynGeneric:
    def __getitem__(self, trait_value: RustTrait) -> RustType:
        if not isinstance(trait_value, RustTrait) or not trait_value.methods:
            raise TypeError("rust.Dyn expects a trait declared with rust.trait")
        return RustType("Dyn", python_name=trait_value.name)

    def __repr__(self) -> str:
        return "rust.Dyn"


i8 = RustType("i8")
i16 = RustType("i16")
i32 = RustType("i32")
i64 = RustType("i64")
i128 = RustType("i128")
isize = RustType("isize")
u8 = RustType("u8")
u16 = RustType("u16")
u32 = RustType("u32")
u64 = RustType("u64")
u128 = RustType("u128")
usize = RustType("usize")
f32 = RustType("f32")
f64 = RustType("f64")
bool = RustType("bool")
char = RustType("char")
String = RustType("String")
Str = RustType("Str")
Vec = RustGeneric("Vec", 1)
Buffer = RustGeneric("Buffer", 1)
TextColumn = RustType("TextColumn")
HashMap = RustGeneric("HashMap", 2)
HashSet = RustGeneric("HashSet", 1)
BTreeMap = RustGeneric("BTreeMap", 2)
BTreeSet = RustGeneric("BTreeSet", 1)
Slice = RustGeneric("Slice", 1)
Box = RustGeneric("Box", 1)
Rc = RustGeneric("Rc", 1)
RefCell = RustGeneric("RefCell", 1)
Arc = RustGeneric("Arc", 1)
Mutex = RustGeneric("Mutex", 1)
Sender = RustGeneric("Sender", 1)
Receiver = RustGeneric("Receiver", 1)
ThreadHandle = RustGeneric("ThreadHandle", 1)
TcpListener = RustType("TcpListener")
TcpStream = RustType("TcpStream")
ThreadPool = RustType("ThreadPool")
File = RustType("File")
IoError = RustType("IoError")
PathBuf = RustType("PathBuf")
Tuple = RustTupleGeneric()
Array = RustArrayGeneric()
Borrow = RustBorrowGeneric()
Dyn = RustDynGeneric()
Option = RustGeneric("Option", 1)
Result = RustGeneric("Result", 2)
Owned = RustGeneric("Owned", 1)
Ref = RustGeneric("Ref", 1)
Mut = RustGeneric("Mut", 1)
Shared = RustGeneric("Shared", 1)
Closure = RustGeneric("Closure", 2)

_F = TypeVar("_F", bound=Callable[..., object])


class NativeOnlyFunction:
    """Metadata-bearing declaration that cannot fall back to Python execution."""

    __name__: str
    __qualname__: str
    __module__: str
    __doc__: str | None

    def __init__(
        self,
        function: Callable[..., object],
        kind: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.__crabwalk_declaration__ = {
            "kind": kind,
            **(metadata or {}),
        }
        update_wrapper(self, function)

    def __call__(self, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError(
            f"{self.__qualname__} is a native-only Crabwalk {self.__crabwalk_declaration__['kind']} "
            "and may be called only from compiled @rust.fn code"
        )

    def __repr__(self) -> str:
        return f"<crabwalk native-only {self.__qualname__}>"


def _native_only_function(
    function: _F,
    kind: str,
    metadata: dict[str, object] | None = None,
) -> NativeOnlyFunction:
    if not callable(function):
        raise TypeError(f"@rust.{kind} expects a function")
    return NativeOnlyFunction(function, kind, metadata)


PartialOrd = RustTrait("PartialOrd")
Ord = RustTrait("Ord")
Copy = RustTrait("Copy")
Clone = RustTrait("Clone")
Display = RustTrait("Display")
Debug = RustTrait("Debug")


def typevar(name: str) -> RustType:
    """Declare a Rust generic type parameter for a native-only helper."""

    if not isinstance(name, str) or not name.isidentifier():
        raise TypeError("rust.typevar expects a valid identifier string")
    return RustType(name, is_generic=True)


def lifetime(name: str) -> RustType:
    """Declare a named Rust lifetime for a native-only helper."""

    if not isinstance(name, str) or not name.isidentifier():
        raise TypeError("rust.lifetime expects a valid identifier string")
    return RustType(name, is_generic=True, is_lifetime=True)


def associated_type(name: str) -> RustType:
    """Name one trait-associated type within a ``rust.trait_method`` signature."""

    if not isinstance(name, str) or not name.isidentifier():
        raise TypeError("rust.associated_type expects a valid identifier string")
    return RustType("Associated", python_name=name)


def generic(
    *type_parameters: RustType,
    bounds: (
        list[RustTrait]
        | tuple[RustTrait, ...]
        | dict[RustType, list[RustTrait] | tuple[RustTrait, ...]]
    ) = (),
) -> Callable[[_F], NativeOnlyFunction]:
    """Mark a function as a native-only generic Rust helper.

    A concrete ``@rust.fn`` function calls the helper, allowing rustc to
    monomorphize it without pretending that Python's ABI is itself generic.
    """

    if not type_parameters or not all(
        isinstance(value, RustType) and value.is_generic for value in type_parameters
    ):
        raise TypeError("rust.generic expects one or more rust.typevar values")
    if isinstance(bounds, dict):
        if not all(
            key in type_parameters
            and all(isinstance(value, RustTrait) for value in values)
            for key, values in bounds.items()
        ):
            raise TypeError(
                "rust.generic bound maps must map declared type parameters to traits"
            )
    elif not all(isinstance(value, RustTrait) for value in bounds):
        raise TypeError("rust.generic bounds must be Rust trait markers")

    def decorate(function: _F) -> NativeOnlyFunction:
        return _native_only_function(
            function,
            "generic",
            {"type_parameters": type_parameters, "bounds": bounds},
        )

    return decorate


def trait_method(
    return_type: RustType | None,
    *parameters: RustType,
    receiver: Literal["ref", "mut", "owned"] = "ref",
    type_parameters: tuple[RustType, ...] | list[RustType] = (),
    bounds: (
        tuple[RustTrait, ...]
        | list[RustTrait]
        | dict[RustType, tuple[RustTrait, ...] | list[RustTrait]]
    ) = (),
) -> RustTraitMethod:
    """Describe one typed trait method, including receiver and tail arguments."""

    if return_type is None:
        return_type = RustType("Unit")
    if not isinstance(return_type, RustType) or not all(
        isinstance(value, RustType) for value in parameters
    ):
        raise TypeError("rust.trait_method expects Rust parameter and return types")
    if receiver not in {"ref", "mut", "owned"}:
        raise TypeError("rust.trait_method receiver must be 'ref', 'mut', or 'owned'")
    if not all(
        isinstance(value, RustType) and value.is_generic for value in type_parameters
    ):
        raise TypeError("rust.trait_method type_parameters must be rust.typevar values")
    if isinstance(bounds, dict):
        normalized_bounds = tuple(
            (key, tuple(values)) for key, values in bounds.items()
        )
    else:
        normalized_bounds = tuple(
            (parameter, tuple(bounds)) for parameter in type_parameters
        )
    if not all(
        key in type_parameters and all(isinstance(value, RustTrait) for value in values)
        for key, values in normalized_bounds
    ):
        raise TypeError("rust.trait_method bounds must target declared type parameters")
    return RustTraitMethod(
        return_type,
        tuple(parameters),
        receiver,
        tuple(type_parameters),
        normalized_bounds,
    )


def trait(name: str, **methods: RustType | RustTraitMethod) -> RustTrait:
    """Declare a typed Rust trait.

    A bare return type retains the original shared/no-argument shorthand. Use
    :func:`trait_method` for arguments or mutable/owned receivers.
    """

    if not isinstance(name, str) or not name.isidentifier():
        raise TypeError("rust.trait expects a valid identifier string")
    if not methods or not all(key.isidentifier() for key in methods):
        raise TypeError("rust.trait methods must use valid identifiers")
    normalized: list[tuple[str, RustTraitMethod]] = []
    for method_name, value in methods.items():
        if isinstance(value, RustType):
            value = RustTraitMethod(value)
        if not isinstance(value, RustTraitMethod):
            raise TypeError(
                "rust.trait methods must map names to Rust return types or "
                "rust.trait_method declarations"
            )
        normalized.append((method_name, value))
    return RustTrait(name, tuple(normalized))


def extern_trait(
    crate_value: Crate,
    *,
    path: str,
    **methods: RustType | RustTraitMethod,
) -> RustTrait:
    """Declare the typed surface of an existing trait from a Cargo dependency."""

    if not isinstance(crate_value, Crate):
        raise TypeError("rust.extern_trait expects a value returned by rust.crate")
    parts = tuple(path.split("::")) if isinstance(path, str) else ()
    if not parts or any(not part.isidentifier() for part in parts):
        raise TypeError("rust.extern_trait path must be a static Rust path")
    if not methods or not all(key.isidentifier() for key in methods):
        raise TypeError("rust.extern_trait methods must use valid identifiers")
    normalized: list[tuple[str, RustTraitMethod]] = []
    for method_name, value in methods.items():
        if isinstance(value, RustType):
            value = RustTraitMethod(value)
        if not isinstance(value, RustTraitMethod):
            raise TypeError(
                "rust.extern_trait methods must map names to Rust return types or "
                "rust.trait_method declarations"
            )
        normalized.append((method_name, value))
    return RustTrait(
        parts[-1],
        tuple(normalized),
        crate=crate_value,
        path=parts,
    )


def method(
    type_value: object,
    *,
    name: str | None = None,
    type_parameters: tuple[RustType, ...] | list[RustType] = (),
    bounds: object = (),
) -> Callable[[_F], NativeOnlyFunction]:
    """Attach a native-only helper as an inherent method on a Rust domain type."""

    if name is not None and (not isinstance(name, str) or not name.isidentifier()):
        raise TypeError("rust.method name must be a valid identifier string")

    def decorate(function: _F) -> NativeOnlyFunction:
        return _native_only_function(
            function,
            "method",
            {
                "type": type_value,
                "name": name,
                "type_parameters": tuple(type_parameters),
                "bounds": bounds,
            },
        )

    return decorate


def impl(
    trait_value: object,
    type_value: object,
    *,
    name: str | None = None,
    type_parameters: tuple[RustType, ...] | list[RustType] = (),
    bounds: object = (),
) -> Callable[[_F], NativeOnlyFunction]:
    """Implement one declared trait method for a concrete Rust domain type."""

    if name is not None and (not isinstance(name, str) or not name.isidentifier()):
        raise TypeError("rust.impl name must be a valid identifier string")

    def decorate(function: _F) -> NativeOnlyFunction:
        return _native_only_function(
            function,
            "impl",
            {
                "trait": trait_value,
                "type": type_value,
                "name": name,
                "type_parameters": tuple(type_parameters),
                "bounds": bounds,
            },
        )

    return decorate


def operator(
    type_value: object,
    *,
    name: str,
) -> Callable[[_F], NativeOnlyFunction]:
    """Implement a supported Rust operator for one generated domain type."""

    if name not in {"add", "subtract", "multiply", "divide", "remainder"}:
        raise TypeError(
            "rust.operator name must be add, subtract, multiply, divide, or remainder"
        )

    def decorate(function: _F) -> NativeOnlyFunction:
        return _native_only_function(
            function,
            "operator",
            {"type": type_value, "name": name},
        )

    return decorate


def async_fn(function: _F) -> NativeOnlyFunction:
    """Mark an ``async def`` as a native-only Rust ``async fn`` helper.

    The helper is discovered statically and is not exported through Python's ABI.
    Call it from compiled code with ``await`` or enter it from an exported
    ``@rust.fn`` wrapper with ``rust.block_on(...)``.
    """

    return _native_only_function(function, "async_fn")


@overload
def fn(function: _F, *, release_gil: builtins.bool = False) -> object: ...


@overload
def fn(
    function: None = None,
    *,
    release_gil: builtins.bool = False,
) -> Callable[[_F], object]: ...


def fn(function: _F | None = None, *, release_gil: builtins.bool = False) -> object:
    """Compile a module-level function as Rust and return its native wrapper."""

    if not isinstance(release_gil, builtins.bool):
        raise TypeError("rust.fn release_gil must be bool")

    def decorate(value: _F) -> object:
        if not callable(value):
            raise TypeError("@rust.fn expects a function")
        from .runtime import compile_function

        return compile_function(value)

    return decorate if function is None else decorate(function)


def struct(
    class_: type[object] | None = None,
    *,
    derive: list[object] | tuple[object, ...] = (),
) -> object:
    """Compile a valid-Python class declaration into a generated Rust struct."""

    del derive

    def decorate(value: type[object]) -> object:
        if not isinstance(value, type):
            raise TypeError("@rust.struct expects a class")
        from .runtime import compile_struct

        return compile_struct(value)

    return decorate if class_ is None else decorate(class_)


def enum(
    class_: type[object] | None = None,
    *,
    derive: list[object] | tuple[object, ...] = (),
) -> object:
    """Compile a valid-Python class declaration into a generated Rust enum."""

    del derive

    def decorate(value: type[object]) -> object:
        if not isinstance(value, type):
            raise TypeError("@rust.enum expects a class")
        from .runtime import compile_enum

        return compile_enum(value)

    return decorate if class_ is None else decorate(class_)


def error(
    class_: type[object] | None = None,
    *,
    derive: list[object] | tuple[object, ...] = (),
) -> object:
    """Compile a native-only enum implementing ``Display`` and ``Error``.

    Use :func:`from_error` for variants that declare a Rust ``From`` conversion
    consumed by ``rust.try_``. Error enums cross an exported ``Result`` as a
    structured :class:`CrabwalkRustError`; they are not Python-owned values.
    """

    del derive

    def decorate(value: type[object]) -> object:
        if not isinstance(value, type):
            raise TypeError("@rust.error expects a class")
        from .runtime import compile_enum

        return compile_enum(value)

    return decorate if class_ is None else decorate(class_)


def variant(*fields: object, **named_fields: object) -> VariantDeclaration:
    """Declare one @rust.enum variant while its ordinary Python class body runs."""

    if fields and named_fields:
        raise TypeError("rust.variant uses positional or named fields, not both")
    return VariantDeclaration(tuple(fields), tuple(named_fields.items()))


def from_error(source_type: RustType) -> VariantDeclaration:
    """Declare a one-field error variant and ``From[source_type]`` conversion."""

    if not isinstance(source_type, RustType):
        raise TypeError("rust.from_error expects one Rust error type")
    return VariantDeclaration((source_type,), (), source_type)


def crate(
    package: str,
    *,
    version: str | None = None,
    features: list[str] | tuple[str, ...] = (),
    path: str | None = None,
    git: str | None = None,
    rev: str | None = None,
) -> Crate:
    """Declare a Cargo dependency for static Crabwalk analysis."""

    if not isinstance(package, str) or not package:
        raise TypeError("rust.crate package must be a non-empty string")
    if sum(value is not None for value in (version, path, git)) != 1:
        raise TypeError("rust.crate requires exactly one of version, path, or git")
    if rev is not None and git is None:
        raise TypeError("rust.crate rev requires git")
    if not all(isinstance(value, str) for value in features):
        raise TypeError("rust.crate features must be strings")
    return Crate(package, package, version, tuple(features), path, git, rev)


def extern_type(crate_value: Crate, *, path: str) -> RustType:
    """Declare a crate-owned type for native-only adapter signatures."""

    if not isinstance(crate_value, Crate):
        raise TypeError("rust.extern_type expects a value returned by rust.crate")
    parts = tuple(path.split("::")) if isinstance(path, str) else ()
    if not parts or any(not part.isidentifier() for part in parts):
        raise TypeError("rust.extern_type path must be a static Rust path")
    return RustType(
        "External",
        python_name="::".join((crate_value.binding, *parts)),
    )


def extern(
    crate_value: Crate,
    *,
    path: str,
    effects: list[RustEffect] | tuple[RustEffect, ...] | None = None,
) -> Callable[[_F], NativeOnlyFunction]:
    """Declare a typed, native-only function adapter for one crate API."""

    if not isinstance(crate_value, Crate):
        raise TypeError("rust.extern expects a value returned by rust.crate")
    parts = tuple(path.split("::")) if isinstance(path, str) else ()
    if not parts or any(not part.isidentifier() for part in parts):
        raise TypeError("rust.extern path must be a static Rust path")
    if effects is not None and (
        not effects or not all(isinstance(value, RustEffect) for value in effects)
    ):
        raise TypeError("rust.extern effects must be a non-empty RustEffect sequence")
    if effects is not None and Pure in effects and len(effects) != 1:
        raise TypeError("rust.Pure cannot be combined with another effect")

    def decorate(function: _F) -> NativeOnlyFunction:
        return _native_only_function(
            function,
            "extern",
            {
                "crate": crate_value,
                "path": parts,
                "effects": None if effects is None else tuple(effects),
            },
        )

    return decorate


def extern_method(
    crate_value: Crate,
    type_value: RustType,
    *,
    path: str,
    name: str | None = None,
    effects: list[RustEffect] | tuple[RustEffect, ...] | None = None,
) -> Callable[[_F], NativeOnlyFunction]:
    """Declare a typed crate function as a method on an external type."""

    if not isinstance(crate_value, Crate):
        raise TypeError("rust.extern_method expects a value returned by rust.crate")
    if not isinstance(type_value, RustType) or type_value.name != "External":
        raise TypeError("rust.extern_method expects a rust.extern_type target")
    parts = tuple(path.split("::")) if isinstance(path, str) else ()
    if not parts or any(not part.isidentifier() for part in parts):
        raise TypeError("rust.extern_method path must be a static Rust path")
    if name is not None and (not isinstance(name, str) or not name.isidentifier()):
        raise TypeError("rust.extern_method name must be an identifier")
    if effects is not None and (
        not effects or not all(isinstance(value, RustEffect) for value in effects)
    ):
        raise TypeError("rust.extern_method effects must be RustEffect values")

    def decorate(function: _F) -> NativeOnlyFunction:
        return _native_only_function(
            function,
            "extern_method",
            {
                "crate": crate_value,
                "type": type_value,
                "path": parts,
                "name": name or function.__name__,
                "effects": None if effects is None else tuple(effects),
            },
        )

    return decorate


def python_adapter(
    function: _F | None = None,
    *,
    effects: list[RustEffect] | tuple[RustEffect, ...] = (),
    module: str | None = None,
    name: str | None = None,
) -> _F | Callable[[_F], _F]:
    """Declare an ordinary Python callable available to compiled Rust code.

    The Python function remains directly callable. Static Crabwalk calls use its
    annotated signature, reacquire the GIL, validate the returned value through
    PyO3, and propagate Python exceptions without an interpreted fallback.
    """

    if not all(isinstance(value, RustEffect) for value in effects):
        raise TypeError("rust.python_adapter effects must be RustEffect values")
    if module is not None and (
        not isinstance(module, str)
        or not module
        or any(not part.isidentifier() for part in module.split("."))
    ):
        raise TypeError("rust.python_adapter module must be a dotted identifier")
    if name is not None and (
        not isinstance(name, str) or not name or not name.isidentifier()
    ):
        raise TypeError("rust.python_adapter name must be an identifier")
    if Pure in effects or PythonRuntime in effects:
        raise TypeError(
            "rust.python_adapter always has PythonRuntime semantics; declare only "
            "additional effects such as rust.Blocking"
        )

    def decorate(value: _F) -> _F:
        if not callable(value):
            raise TypeError("@rust.python_adapter expects a callable")
        setattr(
            value,
            "__crabwalk_declaration__",
            {
                "kind": "python_adapter",
                "effects": (PythonRuntime, MayPanic, *effects),
                "module": module,
                "name": name or value.__name__,
            },
        )
        return value

    return decorate if function is None else decorate(function)


def from_python(
    value: object,
    rust_type: RustType,
    *,
    for_: object | None = None,
) -> object:
    """Copy a Python value into an explicitly selected generated Rust wrapper.

    ``for_`` may be a compiled function from the target module. It is required
    when more than one loaded compilation exposes the same owned Rust type and
    the calling module itself does not identify the intended wrapper.
    """

    if not isinstance(rust_type, RustType):
        raise TypeError("rust.from_python expects a concrete RustType as argument two")
    from .runtime import construct_rust_value

    return construct_rust_value(
        rust_type,
        (value,),
        {},
        for_context=for_,
    )


def to_python(value: object) -> object:
    """Explicitly copy a supported Rust-owned value into an ordinary Python value."""

    from .runtime import to_python_value

    return to_python_value(value)


async def async_call(function: object, *arguments: object) -> object:
    """Await an eligible native function through an explicit Python async boundary.

    This uses Python's worker-thread executor; it is not a Tokio coroutine. Cancelling
    the Python await cannot preempt Rust code that has already started.
    """

    from .runtime import call_rust_async

    return await call_rust_async(function, arguments)


def _compiler_only(name: str) -> Callable[..., object]:
    def operation(*values: object) -> object:
        del values
        raise RuntimeError(
            f"rust.{name} is available only inside compiled @rust.fn code"
        )

    operation.__name__ = name
    return operation


Some = _compiler_only("Some")
Range = _compiler_only("Range")
Ok = _compiler_only("Ok")
Err = _compiler_only("Err")
println = _compiler_only("println")
panic = _compiler_only("panic")
try_ = _compiler_only("try_")
const = _compiler_only("const")
shadow = _compiler_only("shadow")
repeat = _compiler_only("repeat")
drop = _compiler_only("drop")
spawn = _compiler_only("spawn")
channel = _compiler_only("channel")
block_on = _compiler_only("block_on")
join = _compiler_only("join")
select = _compiler_only("select")
yield_now = _compiler_only("yield_now")
sleep_millis = _compiler_only("sleep_millis")
dyn_box = _compiler_only("dyn_box")
trait_call = _compiler_only("trait_call")
call_twice = _compiler_only("call_twice")
unsafe_read = _compiler_only("unsafe_read")
unsafe_write = _compiler_only("unsafe_write")
c_abs = _compiler_only("c_abs")
unsafe_static_increment = _compiler_only("unsafe_static_increment")
type_alias_identity = _compiler_only("type_alias_identity")
boxed_closure_call = _compiler_only("boxed_closure_call")
closure_vector_total = _compiler_only("closure_vector_total")
closure = _compiler_only("closure")
checked_cast = _compiler_only("checked_cast")


__all__ = [
    "Crate",
    "Array",
    "Arc",
    "Borrow",
    "Buffer",
    "TextColumn",
    "Box",
    "Clone",
    "Copy",
    "Debug",
    "Display",
    "Dyn",
    "Err",
    "HashMap",
    "HashSet",
    "BTreeMap",
    "BTreeSet",
    "Ok",
    "OpaqueCrateCall",
    "Option",
    "Ord",
    "Owned",
    "PartialOrd",
    "Ref",
    "Rc",
    "Range",
    "RefCell",
    "Mut",
    "Shared",
    "Mutex",
    "NativeOnlyFunction",
    "Result",
    "Receiver",
    "RustGeneric",
    "RustPath",
    "RustTrait",
    "RustTraitMethod",
    "RustType",
    "RustVariantConstructor",
    "Sender",
    "Some",
    "Str",
    "String",
    "Tuple",
    "ThreadHandle",
    "TcpListener",
    "TcpStream",
    "ThreadPool",
    "File",
    "IoError",
    "PathBuf",
    "Slice",
    "Vec",
    "bool",
    "char",
    "channel",
    "call_twice",
    "c_abs",
    "async_call",
    "async_fn",
    "associated_type",
    "block_on",
    "boxed_closure_call",
    "crate",
    "const",
    "closure_vector_total",
    "closure",
    "checked_cast",
    "f32",
    "f64",
    "error",
    "enum",
    "extern",
    "extern_method",
    "extern_trait",
    "extern_type",
    "drop",
    "dyn_box",
    "fn",
    "from_error",
    "from_python",
    "generic",
    "impl",
    "i8",
    "i16",
    "i32",
    "i64",
    "i128",
    "isize",
    "println",
    "lifetime",
    "join",
    "method",
    "operator",
    "python_adapter",
    "panic",
    "repeat",
    "select",
    "shadow",
    "sleep_millis",
    "spawn",
    "struct",
    "to_python",
    "trait",
    "trait_method",
    "trait_call",
    "type_alias_identity",
    "typevar",
    "try_",
    "u8",
    "u16",
    "u32",
    "u64",
    "u128",
    "unsafe_read",
    "unsafe_static_increment",
    "unsafe_write",
    "usize",
    "variant",
    "yield_now",
]
