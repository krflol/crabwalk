"""The author-facing Rust semantic namespace.

Objects in this module are compiler markers. They are not Python
reimplementations of their Rust namesakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar, overload


@dataclass(frozen=True, slots=True)
class RustType:
    name: str
    arguments: tuple["RustType", ...] = ()
    python_name: str | None = None
    variants: tuple[str, ...] = ()
    const_value: int | None = None
    is_generic: bool = False
    is_lifetime: bool = False

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


@dataclass(frozen=True, slots=True)
class RustTrait:
    """A marker for a Rust trait used in a native generic bound."""

    name: str
    methods: tuple[tuple[str, RustType], ...] = ()

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
HashMap = RustGeneric("HashMap", 2)
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
Tuple = RustTupleGeneric()
Array = RustArrayGeneric()
Borrow = RustBorrowGeneric()
Dyn = RustDynGeneric()
Option = RustGeneric("Option", 1)
Result = RustGeneric("Result", 2)
Owned = RustGeneric("Owned", 1)
Ref = RustGeneric("Ref", 1)
Mut = RustGeneric("Mut", 1)

_F = TypeVar("_F", bound=Callable[..., object])

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


def generic(
    *type_parameters: RustType,
    bounds: list[RustTrait] | tuple[RustTrait, ...] = (),
) -> Callable[[_F], _F]:
    """Mark a function as a native-only generic Rust helper.

    A concrete ``@rust.fn`` function calls the helper, allowing rustc to
    monomorphize it without pretending that Python's ABI is itself generic.
    """

    if not type_parameters or not all(
        isinstance(value, RustType) and value.is_generic for value in type_parameters
    ):
        raise TypeError("rust.generic expects one or more rust.typevar values")
    if not all(isinstance(value, RustTrait) for value in bounds):
        raise TypeError("rust.generic bounds must be Rust trait markers")

    def decorate(function: _F) -> _F:
        if not callable(function):
            raise TypeError("@rust.generic expects a function")
        return function

    return decorate


def trait(name: str, **methods: RustType) -> RustTrait:
    """Declare an object-safe Rust trait with shared, no-argument methods."""

    if not isinstance(name, str) or not name.isidentifier():
        raise TypeError("rust.trait expects a valid identifier string")
    if not methods or not all(
        key.isidentifier() and isinstance(value, RustType)
        for key, value in methods.items()
    ):
        raise TypeError("rust.trait methods must map names to Rust return types")
    return RustTrait(name, tuple(methods.items()))


def method(
    type_value: object,
    *,
    name: str | None = None,
) -> Callable[[_F], _F]:
    """Attach a native-only helper as an inherent method on a Rust domain type."""

    del type_value
    if name is not None and (not isinstance(name, str) or not name.isidentifier()):
        raise TypeError("rust.method name must be a valid identifier string")

    def decorate(function: _F) -> _F:
        if not callable(function):
            raise TypeError("@rust.method expects a function")
        return function

    return decorate


def impl(
    trait_value: object,
    type_value: object,
    *,
    name: str | None = None,
) -> Callable[[_F], _F]:
    """Implement one declared trait method for a concrete Rust domain type."""

    del trait_value, type_value
    if name is not None and (not isinstance(name, str) or not name.isidentifier()):
        raise TypeError("rust.impl name must be a valid identifier string")

    def decorate(function: _F) -> _F:
        if not callable(function):
            raise TypeError("@rust.impl expects a function")
        return function

    return decorate


def operator(
    type_value: object,
    *,
    name: str,
) -> Callable[[_F], _F]:
    """Implement a supported Rust operator for one generated domain type."""

    del type_value
    if name != "add":
        raise TypeError("rust.operator currently supports name='add'")

    def decorate(function: _F) -> _F:
        if not callable(function):
            raise TypeError("@rust.operator expects a function")
        return function

    return decorate


def async_fn(function: _F) -> _F:
    """Mark an ``async def`` as a native-only Rust ``async fn`` helper.

    The helper is discovered statically and is not exported through Python's ABI.
    Call it from compiled code with ``await`` or enter it from an exported
    ``@rust.fn`` wrapper with ``rust.block_on(...)``.
    """

    if not callable(function):
        raise TypeError("@rust.async_fn expects an async function")
    return function


@overload
def fn(function: _F) -> object: ...


@overload
def fn(function: None = None) -> Callable[[_F], object]: ...


def fn(function: _F | None = None) -> object:
    """Compile a module-level function as Rust and return its native wrapper."""

    if function is None:
        return fn
    if not callable(function):
        raise TypeError("@rust.fn expects a function")
    from .runtime import compile_function

    return compile_function(function)


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


def variant(*fields: object, **named_fields: object) -> VariantDeclaration:
    """Declare one @rust.enum variant while its ordinary Python class body runs."""

    if fields and named_fields:
        raise TypeError("rust.variant uses positional or named fields, not both")
    return VariantDeclaration(tuple(fields), tuple(named_fields.items()))


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


def from_python(value: object, rust_type: RustType) -> object:
    """Explicitly copy a supported Python value into generated Rust storage."""

    if not isinstance(rust_type, RustType):
        raise TypeError("rust.from_python expects a concrete RustType as argument two")
    return rust_type(value)


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


__all__ = [
    "Crate",
    "Array",
    "Arc",
    "Borrow",
    "Box",
    "Clone",
    "Copy",
    "Debug",
    "Display",
    "Dyn",
    "Err",
    "HashMap",
    "Ok",
    "Option",
    "Ord",
    "Owned",
    "PartialOrd",
    "Ref",
    "Rc",
    "Range",
    "RefCell",
    "Mut",
    "Mutex",
    "Result",
    "Receiver",
    "RustGeneric",
    "RustPath",
    "RustTrait",
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
    "Vec",
    "bool",
    "char",
    "channel",
    "call_twice",
    "c_abs",
    "async_call",
    "async_fn",
    "block_on",
    "boxed_closure_call",
    "crate",
    "const",
    "closure_vector_total",
    "f32",
    "f64",
    "enum",
    "drop",
    "dyn_box",
    "fn",
    "from_python",
    "generic",
    "impl",
    "i8",
    "i16",
    "i32",
    "i64",
    "i128",
    "println",
    "lifetime",
    "join",
    "method",
    "operator",
    "panic",
    "repeat",
    "select",
    "shadow",
    "sleep_millis",
    "spawn",
    "struct",
    "to_python",
    "trait",
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
