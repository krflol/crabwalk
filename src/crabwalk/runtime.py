"""Runtime decorator binding for compiled Rust functions."""

from __future__ import annotations

import inspect
import math
import struct as struct_module
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable

from crabwalk._version import RUNTIME_ABI_VERSION, __version__
from crabwalk.build.cache import read_json, sha256_file
from crabwalk.build.loader import load_extension
from crabwalk.compiler.codegen import function_releases_gil
from crabwalk.compiler.naming import owned_class_names
from crabwalk.compiler.frontend import (
    analyze_project_path,
    project_source_anchor,
)
from crabwalk.diagnostics import (
    CrabwalkCompilationError,
    CrabwalkBorrowError,
    CrabwalkMoveError,
    CrabwalkPanicError,
    CrabwalkRustError,
    CrabwalkThreadError,
    Diagnostic,
)
from crabwalk.progress import ImplicitBuildProgress
from crabwalk.service import CompilationResult, default_service

_compile_lock = threading.RLock()
_results: dict[tuple[str, str], CompilationResult] = {}
_owned_registry_lock = threading.RLock()
_owned_types_by_module: dict[tuple[str, str], type[Any]] = {}
_owned_type_fields: dict[str, tuple[str, ...]] = {}
_owned_enum_variants: dict[str, dict[str, tuple[str, ...]]] = {}

_MOVE_ERROR_PREFIX = "CrabwalkMoveError:"
_PANIC_ERROR_PREFIX = "CrabwalkPanicError:"
_RUST_ERROR_PREFIX = "CrabwalkRustError:"
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


class _RustOwnedValue:
    """A Python handle to one move-aware value stored by generated Rust."""

    __slots__ = (
        "_native",
        "_type_key",
        "_move_site",
        "_field_names",
        "_enum_variants",
        "_thread_id",
        "_definition_site",
        "_borrow_contexts",
    )

    def __init__(
        self,
        native: object,
        type_key: str,
        field_names: tuple[str, ...] = (),
        enum_variants: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        object.__setattr__(self, "_native", native)
        object.__setattr__(self, "_type_key", type_key)
        object.__setattr__(self, "_move_site", None)
        object.__setattr__(self, "_field_names", field_names)
        object.__setattr__(self, "_enum_variants", enum_variants or {})
        object.__setattr__(self, "_thread_id", threading.get_ident())
        object.__setattr__(self, "_definition_site", _call_location())
        object.__setattr__(self, "_borrow_contexts", ())

    @property
    def rust_type(self) -> str:
        self._check_thread()
        return self._type_key

    @property
    def moved(self) -> bool:
        self._check_thread()
        return bool(self._native.is_moved())

    def to_python(self) -> object:
        self._check_thread()
        if self._enum_variants:
            try:
                variant = self._native.variant()
                result = {"variant": variant}
                for field_name in self._enum_variants[variant]:
                    result[field_name] = getattr(self._native, field_name)
                return result
            except RuntimeError as error:
                _raise_translated_runtime_error(error, self)
        try:
            value = self._native.to_python()
        except RuntimeError as error:
            _raise_translated_runtime_error(error, self)
        if self._field_names:
            return dict(zip(self._field_names, value))
        return value

    def __len__(self) -> int:
        self._check_thread()
        try:
            return int(len(self._native))
        except RuntimeError as error:
            _raise_translated_runtime_error(error, self)

    def __repr__(self) -> str:
        self._check_thread()
        return repr(self._native)

    def __getattr__(self, name: str) -> object:
        self._check_thread()
        if name not in self._field_names:
            raise AttributeError(name)
        try:
            return getattr(self._native, name)
        except RuntimeError as error:
            _raise_translated_runtime_error(error, self)

    def __setattr__(self, name: str, value: object) -> None:
        self._check_thread()
        if name in self._field_names:
            _validate_unicode_value_tree(value)
            try:
                setattr(self._native, name, value)
            except RuntimeError as error:
                _raise_translated_runtime_error(error, self)
            return
        object.__setattr__(self, name, value)

    def __copy__(self) -> "_RustOwnedValue":
        # Copying a Python handle aliases the one Rust ownership state.
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> "_RustOwnedValue":
        memo[id(self)] = self
        return self

    def _record_move(
        self,
        function_name: str,
        location: str,
        parameter_site: str,
    ) -> None:
        self._check_thread()
        if self._move_site is None:
            self._move_site = (
                f"moved into {function_name} at {location}; "
                f"consuming parameter defined at {parameter_site}"
            )

    def _check_thread(self) -> None:
        current = threading.get_ident()
        if current != self._thread_id:
            raise CrabwalkThreadError(
                "Rust-owned Crabwalk handles are thread-affine until an explicit "
                "Send/Sync policy is exposed; reconstruct the value in the target thread"
            )


def _resolve_owned_native_type(
    rust_type: object,
    type_key: str,
    *,
    for_context: object | None = None,
) -> type[Any] | None:
    """Resolve one wrapper without load-order-dependent ambient fallback."""

    if for_context is not None and isinstance(for_context, RustFunction):
        module = for_context._compilation.module
        if module is None:
            return None
        type_ref = _runtime_type_ref(rust_type)
        python_name, _ = owned_class_names(type_ref)
        candidate = getattr(module, python_name, None)
        if isinstance(candidate, type):
            return candidate

    context_module = (
        getattr(for_context, "__module__", "")
        if for_context is not None
        else _calling_module_name()
    )
    if not isinstance(context_module, str):
        context_module = ""
    with _owned_registry_lock:
        exact = _owned_types_by_module.get((context_module, type_key))
        if exact is not None:
            return exact
        candidates = {
            native_type
            for (registered_module, registered_key), native_type in (
                _owned_types_by_module.items()
            )
            if registered_key == type_key
        }
    if len(candidates) == 1:
        return next(iter(candidates))
    if len(candidates) > 1:
        raise RuntimeError(
            f"Multiple generated wrappers for {rust_type!r} are loaded. "
            "Construct inside the target module or use "
            "rust.from_python(value, type, for_=compiled_function)."
        )
    return None


def _runtime_type_ref(rust_type: object) -> object:
    """Translate a runtime marker only far enough to derive its owned class name."""

    from crabwalk.compiler.ir import TypeRef
    from crabwalk.rust import RustType

    if not isinstance(rust_type, RustType):
        raise TypeError("expected a Crabwalk Rust type")
    return TypeRef(
        rust_type.name,
        tuple(_runtime_type_ref(value) for value in rust_type.arguments),
        python_name=rust_type.python_name,
        const_value=rust_type.const_value,
        is_generic=rust_type.is_generic,
        is_lifetime=rust_type.is_lifetime,
    )


def construct_rust_value(
    rust_type: object,
    values: tuple[object, ...],
    keywords: dict[str, object],
    *,
    for_context: object | None = None,
) -> object:
    """Construct an explicitly typed, generated Rust-owned value."""

    from crabwalk.rust import RustType

    if not isinstance(rust_type, RustType):
        raise TypeError("expected a Crabwalk Rust type")
    type_key = rust_type.rust_key()
    native_type = _resolve_owned_native_type(
        rust_type,
        type_key,
        for_context=for_context,
    )
    if native_type is None:
        raise RuntimeError(
            f"No generated wrapper for {rust_type!r} is loaded. Define an "
            "@rust.fn ownership parameter or @rust.struct declaration for this "
            "concrete type before constructing it."
        )
    try:
        for value in values:
            _validate_unicode_value_tree(value)
        for value in keywords.values():
            _validate_unicode_value_tree(value)
        if rust_type.name == "Vec" and len(rust_type.arguments) == 1:
            if keywords:
                names = ", ".join(sorted(keywords))
                raise TypeError(
                    f"{rust_type!r} does not accept keyword arguments: {names}"
                )
            if len(values) != 1:
                raise TypeError(
                    f"{rust_type!r} expects one Python sequence; got "
                    f"{len(values)} arguments"
                )
            native = native_type(
                _validated_vector_values(values[0], rust_type.arguments[0])
            )
        else:
            native = native_type(*values, **keywords)
    except (OverflowError, TypeError, ValueError) as error:
        raise type(error)(f"cannot construct {rust_type!r}: {error}") from error
    return _RustOwnedValue(
        native,
        type_key,
        _owned_type_fields.get(type_key, ()),
        _owned_enum_variants.get(type_key),
    )


def _validated_vector_values(value: object, element_type: object) -> list[object]:
    from crabwalk.rust import RustType

    if not isinstance(value, Sequence):
        raise TypeError(f"expected a Python sequence, found {type(value).__name__}")
    if not isinstance(element_type, RustType) or element_type.arguments:
        raise TypeError("expected a supported concrete Vec element type")
    result: list[object] = []
    for index, item in enumerate(value):
        try:
            result.append(_validated_primitive(item, element_type.name))
        except (OverflowError, TypeError, ValueError) as error:
            raise type(error)(f"element {index}: {error}") from error
    return result


def _validated_primitive(value: object, rust_name: str) -> object:
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
        _validate_unicode_value_tree(value)
        return value
    if rust_name in {"String", "Str"}:
        if type(value) is not str:
            raise TypeError(
                f"expected str for rust.{rust_name}, found {type(value).__name__}"
            )
        _validate_unicode_value_tree(value)
        return value
    if rust_name in {"f32", "f64"}:
        if type(value) not in {int, float}:
            raise TypeError(
                f"expected int or float for rust.{rust_name}, "
                f"found {type(value).__name__}"
            )
        converted = float(value)
        if (
            rust_name == "f32"
            and math.isfinite(converted)
            and abs(converted) > 3.4028235e38
        ):
            raise OverflowError(f"{value} is outside the finite rust.f32 range")
        return converted
    raise TypeError(f"rust.{rust_name} is not a supported Vec boundary element")


def construct_rust_variant(
    rust_type: object,
    variant: str,
    values: tuple[object, ...],
    keywords: dict[str, object],
) -> object:
    from crabwalk.rust import RustType

    if not isinstance(rust_type, RustType) or variant not in rust_type.variants:
        raise TypeError("expected a generated Crabwalk enum variant")
    type_key = rust_type.rust_key()
    native_type = _resolve_owned_native_type(rust_type, type_key)
    if native_type is None:
        raise RuntimeError(f"No generated wrapper for {rust_type!r} is loaded.")
    try:
        for value in values:
            _validate_unicode_value_tree(value)
        for value in keywords.values():
            _validate_unicode_value_tree(value)
        constructor = getattr(native_type, variant)
        native = constructor(*values, **keywords)
    except (AttributeError, OverflowError, TypeError, ValueError) as error:
        raise type(error)(
            f"cannot construct {rust_type!r}.{variant}: {error}"
        ) from error
    return _RustOwnedValue(
        native,
        type_key,
        _owned_type_fields.get(type_key, ()),
        _owned_enum_variants.get(type_key),
    )


def _validate_unicode_value_tree(value: object) -> None:
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
            _validate_unicode_value_tree(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_unicode_value_tree(key)
            _validate_unicode_value_tree(item)


def construct_inferred_vector(
    values: tuple[object, ...],
    keywords: dict[str, object],
) -> object:
    """Construct rust.Vec([...]) using Crabwalk's documented default types."""

    from crabwalk.rust import RustType

    if keywords:
        names = ", ".join(sorted(keywords))
        raise TypeError(f"rust.Vec does not accept keyword arguments: {names}")
    if len(values) != 1 or not isinstance(values[0], (list, tuple)):
        raise TypeError("rust.Vec expects one list or tuple for inferred construction")
    sequence = values[0]
    if not sequence:
        raise TypeError("cannot infer the element type of an empty rust.Vec")
    element_type = _inferred_rust_type(sequence[0], RustType)
    for index, value in enumerate(sequence[1:], start=1):
        candidate = _inferred_rust_type(value, RustType)
        if candidate != element_type:
            raise TypeError(
                "rust.Vec inference requires homogeneous values; "
                f"element 0 is {element_type!r}, element {index} is {candidate!r}"
            )
    return construct_rust_value(
        RustType("Vec", (element_type,)),
        (sequence,),
        {},
    )


def to_python_value(value: object) -> object:
    if not isinstance(value, _RustOwnedValue):
        raise TypeError("rust.to_python expects a Rust-owned Crabwalk value")
    return value.to_python()


def _inferred_rust_type(value: object, rust_type_class: type[Any]) -> Any:
    if type(value) is bool:
        return rust_type_class("bool")
    if type(value) is int:
        if not -(1 << 63) <= value < (1 << 63):
            raise OverflowError(
                "an inferred rust.Vec integer must fit rust.i64; use rust.Vec[T](...) "
                "to select another integer type"
            )
        return rust_type_class("i64")
    if type(value) is float:
        return rust_type_class("f64")
    if type(value) is str:
        return rust_type_class("String")
    raise TypeError(
        "rust.Vec inference supports homogeneous bool, int, float, or str values; "
        f"found {type(value).__name__}"
    )


class RustFunction:
    """A Python callable backed only by a generated native symbol."""

    def __init__(
        self,
        original: Callable[..., object],
        native: Callable[..., object],
        compilation: CompilationResult,
    ) -> None:
        self.__name__ = original.__name__
        self.__qualname__ = original.__qualname__
        self.__module__ = original.__module__
        self.__doc__ = original.__doc__
        self.__annotations__ = dict(getattr(original, "__annotations__", {}))
        self.__signature__ = inspect.signature(original)
        self._native = native
        self._compilation = compilation
        function_ir = next(
            value
            for value in compilation.ir.functions
            if value.name == original.__name__
            and (not value.module_name or value.module_name == original.__module__)
        )
        self._rust_symbol = function_ir.rust_symbol
        self._parameters = function_ir.parameters
        self._releases_gil = function_releases_gil(function_ir)
        self._effects = function_ir.effects

    def __call__(self, *args: object, **kwargs: object) -> object:
        if kwargs:
            names = ", ".join(sorted(kwargs))
            raise TypeError(
                f"{self.__qualname__} accepts positional arguments only; got {names}"
            )
        if len(args) != len(self._parameters):
            raise TypeError(
                f"{self.__qualname__} expects {len(self._parameters)} positional "
                f"argument(s); got {len(args)}"
            )
        native_args = list(args)
        owned_arguments: list[tuple[object, _RustOwnedValue]] = []
        for index, parameter in enumerate(self._parameters):
            if parameter.type_ref.ownership is None:
                try:
                    native_args[index] = _validated_boundary_input(
                        native_args[index], parameter.type_ref
                    )
                except (OverflowError, TypeError, ValueError) as error:
                    raise type(error)(
                        f"argument '{parameter.name}' to {self.__qualname__}: {error}"
                    ) from error
                continue
            value = native_args[index]
            if not isinstance(value, _RustOwnedValue):
                raise TypeError(
                    f"argument '{parameter.name}' to {self.__qualname__} must be "
                    f"a Rust-owned {parameter.type_ref.underlying.display()} value; "
                    "construct it with its generated Rust type marker"
                )
            value._check_thread()
            expected_key = parameter.type_ref.underlying.render()
            if value._type_key != expected_key:
                raise TypeError(
                    f"argument '{parameter.name}' to {self.__qualname__} expects "
                    f"{expected_key}, found {value._type_key}"
                )
            python_name, _ = owned_class_names(parameter.type_ref.underlying)
            module = self._compilation.module
            expected_native_type = getattr(module, python_name) if module else None
            if expected_native_type is None or not isinstance(
                value._native, expected_native_type
            ):
                raise TypeError(
                    f"argument '{parameter.name}' was created for a different "
                    "compiled Crabwalk module identity; reconstruct it explicitly "
                    "from value.to_python() for this module"
                )
            native_args[index] = value._native
            owned_arguments.append((parameter, value))

        call_location = _call_location() if owned_arguments else ""
        prior_borrow_contexts: dict[int, tuple[_RustOwnedValue, tuple[str, ...]]] = {}
        for parameter, value in owned_arguments:
            if parameter.type_ref.ownership not in {"Ref", "Mut"}:
                continue
            identity = id(value)
            if identity not in prior_borrow_contexts:
                prior_borrow_contexts[identity] = (value, value._borrow_contexts)
            context = (
                f"{parameter.type_ref.ownership} parameter '{parameter.name}' "
                f"defined at {_span_location(parameter.span)}; call at {call_location}"
            )
            object.__setattr__(
                value,
                "_borrow_contexts",
                (*value._borrow_contexts, context),
            )
        try:
            return self._native(*native_args)
        except RuntimeError as error:
            source_value = next(
                (value for _, value in owned_arguments if value.moved),
                None,
            )
            if source_value is None and owned_arguments:
                source_value = owned_arguments[0][1]
            _raise_translated_runtime_error(error, source_value)
        finally:
            for value, prior in prior_borrow_contexts.values():
                object.__setattr__(value, "_borrow_contexts", prior)
            for parameter, value in owned_arguments:
                if parameter.type_ref.ownership == "Owned" and value.moved:
                    value._record_move(
                        f"{self.__qualname__}()",
                        call_location,
                        _span_location(parameter.span),
                    )

    def __repr__(self) -> str:
        fingerprint = self._compilation.fingerprint[:12]
        return (
            f"<crabwalk RustFunction {self.__module__}.{self.__qualname__} "
            f"[{fingerprint}]>"
        )

    @property
    def __crabwalk__(self) -> dict[str, object]:
        return {
            "fingerprint": self._compilation.fingerprint,
            "extension_name": self._compilation.extension_name,
            "artifact": (
                str(self._compilation.artifact)
                if self._compilation.artifact is not None
                else None
            ),
            "generated_dir": str(self._compilation.generated_dir),
            "cache_hit": self._compilation.cache_hit,
            "native_symbol": self._rust_symbol,
            "gil_released": self._releases_gil,
            "async_eligible": self._releases_gil,
            "effects": self._effects,
        }


async def call_rust_async(
    function: object,
    arguments: tuple[object, ...],
) -> object:
    """Await a primitive-only native call on Python's default thread executor.

    Cancelling the await does not stop Rust code that has already begun executing.
    """

    import asyncio

    if not isinstance(function, RustFunction):
        raise TypeError("rust.async_call expects a compiled @rust.fn function")
    if not function._releases_gil:
        raise TypeError(
            "rust.async_call supports native-only primitive signatures that release "
            "the GIL; ownership handles and Python runtime boundaries are unsupported"
        )
    return await asyncio.to_thread(function, *arguments)


def _validated_boundary_input(value: object, type_ref: object) -> object:
    from crabwalk.compiler.ir import TypeRef

    if not isinstance(type_ref, TypeRef):
        raise TypeError("invalid compiled boundary type")
    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        if value is None:
            return None
        return _validated_boundary_input(value, type_ref.arguments[0])
    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        if type(value) is not tuple:
            raise TypeError(f"expected tuple, found {type(value).__name__}")
        if len(value) != len(type_ref.arguments):
            raise ValueError(
                f"expected a {len(type_ref.arguments)}-item tuple, found {len(value)}"
            )
        converted: list[object] = []
        for index, (item, item_type) in enumerate(zip(value, type_ref.arguments)):
            try:
                converted.append(_validated_boundary_input(item, item_type))
            except (OverflowError, TypeError, ValueError) as error:
                raise type(error)(f"tuple item {index}: {error}") from error
        return tuple(converted)
    return _validated_primitive(value, type_ref.rust_name)


def compile_function(function: Callable[..., object]) -> RustFunction:
    if not inspect.isfunction(function):
        raise TypeError("@rust.fn supports module-level Python functions only")
    source = inspect.getsourcefile(function) or function.__code__.co_filename
    if not source or source.startswith("<"):
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB005",
                "Rust function has no source file",
                "@rust.fn requires a function defined in a UTF-8 Python source file.",
            )
        )
    path = Path(source).resolve()
    with _compile_lock:
        cached = _compilation_for(path, function.__module__)
        module = cached.module
        if module is None:
            raise AssertionError("loaded compilation has no extension module")
        try:
            function_ir = next(
                value
                for value in cached.ir.functions
                if value.name == function.__name__
                and (not value.module_name or value.module_name == function.__module__)
            )
            native = getattr(module, function_ir.rust_symbol)
        except AttributeError as error:
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB402",
                    "Native symbol is missing",
                    f"The generated extension does not export {function.__name__}.",
                    cached.ir.functions[0].span,
                )
            ) from error
    return RustFunction(function, native, cached)


def compile_struct(original: type[object]) -> object:
    """Compile a @rust.struct class and return its runtime Rust type marker."""

    from crabwalk.rust import RustType

    source = inspect.getsourcefile(original)
    if not source or source.startswith("<"):
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB005",
                "Rust struct has no source file",
                "@rust.struct requires a class in a UTF-8 Python source file.",
            )
        )
    path = Path(source).resolve()
    with _compile_lock:
        cached = _compilation_for(path, original.__module__)
        if cached.module is None:
            raise AssertionError("loaded struct compilation has no extension module")
        try:
            struct_ir = next(
                value
                for value in cached.ir.structs
                if value.name == original.__name__
                and value.module_name == original.__module__
            )
        except StopIteration as error:
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB403",
                    "Native struct symbol is missing",
                    f"The generated extension does not define {original.__qualname__}.",
                    cached.ir.structs[0].span if cached.ir.structs else None,
                )
            ) from error
    return RustType(
        struct_ir.symbol,
        python_name=f"{original.__module__}.{original.__qualname__}",
    )


def compile_enum(original: type[object]) -> object:
    """Compile a @rust.enum class and return its variant-aware type marker."""

    from crabwalk.rust import RustType

    source = inspect.getsourcefile(original)
    if not source or source.startswith("<"):
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB005",
                "Rust enum has no source file",
                "@rust.enum requires a class in a UTF-8 Python source file.",
            )
        )
    path = Path(source).resolve()
    with _compile_lock:
        cached = _compilation_for(path, original.__module__)
        if cached.module is None:
            raise AssertionError("loaded enum compilation has no extension module")
        try:
            enum_ir = next(
                value
                for value in cached.ir.enums
                if value.name == original.__name__
                and value.module_name == original.__module__
            )
        except StopIteration as error:
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB404",
                    "Native enum symbol is missing",
                    f"The generated extension does not define {original.__qualname__}.",
                    cached.ir.enums[0].span if cached.ir.enums else None,
                )
            ) from error
    return RustType(
        enum_ir.symbol,
        python_name=f"{original.__module__}.{original.__qualname__}",
        variants=tuple(value.name for value in enum_ir.variants),
    )


def _compilation_for(path: Path, module_name: str) -> CompilationResult:
    """Resolve one loaded compilation for all decorators in a source package."""

    anchor = project_source_anchor(path)
    label = anchor.parent.name if anchor.name == "__init__.py" else anchor.stem
    progress = ImplicitBuildProgress(label)
    progress.start()
    try:
        # Always enter the service so native dependency, toolchain, Cargo config,
        # environment, and lock inputs participate in the complete fingerprint.
        # A source-only memo here would bypass those stronger checks on reload.
        result = _load_prebuilt_compilation(path, module_name)
        if result is None:
            result = default_service.compile_path(
                path,
                module_name=module_name,
                mode="build",
                load=True,
                progress=progress.update,
            )
    except BaseException:
        progress.fail()
        raise
    else:
        progress.finish(
            cache_hit=result.cache_hit,
            prebuilt=result.cache_status == "prebuilt",
        )
    key = (str(anchor), result.fingerprint)
    cached = _results.setdefault(key, result)
    if cached.module is None:
        raise AssertionError("loaded compilation has no extension module")
    _register_owned_types(cached)
    return cached


def _load_prebuilt_compilation(
    path: Path,
    module_name: str,
) -> CompilationResult | None:
    anchor = project_source_anchor(path)
    if anchor.name != "__init__.py":
        return None
    package_root = anchor.parent
    manifest_path = package_root / "_crabwalk_prebuilt.json"
    if not manifest_path.is_file():
        return None

    manifest = read_json(manifest_path)
    ir = analyze_project_path(path, module_name)
    if manifest is None:
        _invalid_prebuilt(ir, "The embedded manifest is not valid JSON.")
    assert manifest is not None
    expected_fields = {
        "fingerprint": str,
        "extension_name": str,
        "artifact": str,
        "artifact_sha256": str,
        "source_hash": str,
        "crabwalk_version": str,
        "runtime_abi_version": int,
    }
    if manifest.get("schema_version") != 2 or any(
        not isinstance(manifest.get(name), expected_type)
        for name, expected_type in expected_fields.items()
    ):
        _invalid_prebuilt(ir, "The embedded manifest has an unsupported schema.")
    if manifest["runtime_abi_version"] != RUNTIME_ABI_VERSION:
        _invalid_prebuilt(
            ir,
            "The embedded native artifact uses a different Crabwalk runtime ABI.",
        )
    if manifest["crabwalk_version"] != __version__:
        _invalid_prebuilt(
            ir,
            "The embedded native artifact was generated by a different Crabwalk version.",
        )
    if manifest["source_hash"] != ir.source_hash:
        _invalid_prebuilt(
            ir,
            "The installed Python sources do not match the embedded native artifact.",
        )
    if manifest.get("module_name") != ir.module_name:
        _invalid_prebuilt(
            ir,
            "The embedded native artifact belongs to a different Python package.",
        )

    artifact_relative = Path(str(manifest["artifact"]))
    if artifact_relative.is_absolute() or ".." in artifact_relative.parts:
        _invalid_prebuilt(ir, "The embedded artifact path is unsafe.")
    artifact = (package_root / artifact_relative).resolve()
    if not artifact.is_relative_to(package_root.resolve()):
        _invalid_prebuilt(ir, "The embedded artifact escapes the installed package.")
    if not artifact.is_file():
        _invalid_prebuilt(ir, f"The embedded artifact is missing: {artifact_relative}.")
    if sha256_file(artifact) != manifest["artifact_sha256"]:
        _invalid_prebuilt(ir, "The embedded native artifact failed hash verification.")

    extension_name = str(manifest["extension_name"])
    try:
        module = load_extension(extension_name, artifact)
    except (ImportError, OSError) as error:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB401",
                "Native extension load failed",
                str(error),
                _ir_primary_span(ir),
                "Install a wheel matching this Python interpreter and platform.",
            )
        ) from error
    return CompilationResult(
        ir=ir,
        fingerprint=str(manifest["fingerprint"]),
        extension_name=extension_name,
        project_root=package_root,
        generated_dir=artifact.parent,
        artifact=artifact,
        cache_hit=True,
        module=module,
        command=None,
        cache_status="prebuilt",
        cached_artifact=artifact,
    )


def _invalid_prebuilt(ir: object, message: str) -> Any:
    from crabwalk.compiler.ir import PackageIR

    span = _ir_primary_span(ir) if isinstance(ir, PackageIR) else None
    raise CrabwalkCompilationError(
        Diagnostic(
            "CRAB405",
            "Embedded native artifact is invalid",
            message,
            span,
            "Reinstall or rebuild the package wheel for this interpreter and platform.",
        )
    )


def _ir_primary_span(ir: object) -> object:
    from crabwalk.compiler.ir import PackageIR

    if not isinstance(ir, PackageIR):
        return None
    if ir.functions:
        return ir.functions[0].span
    if ir.structs:
        return ir.structs[0].span
    if ir.enums:
        return ir.enums[0].span
    return None


def _register_owned_types(compilation: CompilationResult) -> None:
    module = compilation.module
    if module is None:
        return
    concrete_types = {
        (
            function.module_name or compilation.ir.module_name,
            parameter.type_ref.underlying,
        )
        for function in compilation.ir.functions
        if function.exported
        for parameter in function.parameters
        if parameter.type_ref.ownership is not None
    }
    concrete_types.update(
        (struct.module_name, struct.type_ref) for struct in compilation.ir.structs
    )
    concrete_types.update(
        (enum.module_name, enum.type_ref) for enum in compilation.ir.enums
    )
    with _owned_registry_lock:
        for module_name, type_ref in concrete_types:
            python_name, _ = owned_class_names(type_ref)
            native_type = getattr(module, python_name)
            type_key = type_ref.render()
            _owned_types_by_module[(module_name, type_key)] = native_type
    for struct in compilation.ir.structs:
        _owned_type_fields[struct.type_ref.render()] = tuple(
            field.name for field in struct.fields
        )
    for enum in compilation.ir.enums:
        type_key = enum.type_ref.render()
        variants = {
            variant.name: tuple(field.name for field in variant.fields)
            for variant in enum.variants
        }
        _owned_enum_variants[type_key] = variants
        _owned_type_fields[type_key] = tuple(
            sorted(
                {field.name for variant in enum.variants for field in variant.fields}
            )
        )


def _calling_module_name() -> str:
    frame = inspect.currentframe()
    try:
        candidate = frame.f_back if frame is not None else None
        while candidate is not None:
            value = candidate.f_globals.get("__name__", "")
            if (
                isinstance(value, str)
                and value
                and not (value == "crabwalk" or value.startswith("crabwalk."))
            ):
                return value
            candidate = candidate.f_back
        return ""
    finally:
        del frame


def _call_location() -> str:
    frame = inspect.currentframe()
    try:
        package_root = Path(__file__).resolve().parent
        candidate = frame.f_back if frame is not None else None
        while candidate is not None:
            filename = candidate.f_code.co_filename
            if not filename.startswith("<"):
                path = Path(filename).resolve()
                if not path.is_relative_to(package_root):
                    return f"{path}:{candidate.f_lineno}"
            candidate = candidate.f_back
        return "<unknown>"
    finally:
        del frame


def _span_location(span: object) -> str:
    path = getattr(span, "path", "<unknown>")
    line = getattr(span, "line", 1)
    column = getattr(span, "column", 1)
    return f"{path}:{line}:{column}"


def _raise_translated_runtime_error(
    error: RuntimeError,
    value: _RustOwnedValue | None = None,
) -> Any:
    message = str(error)
    if message in {"Already borrowed", "Already mutably borrowed"}:
        details = [f"conflicting call-scoped Rust borrow: {message.lower()}"]
        if value is not None:
            details.append(f"value created at {value._definition_site}")
            details.extend(value._borrow_contexts)
        details.append(
            "use separate values or change the signature so one alias is not "
            "borrowed as both rust.Ref and rust.Mut"
        )
        raise CrabwalkBorrowError("; ".join(details)) from error
    if message.startswith(_PANIC_ERROR_PREFIX):
        raise CrabwalkPanicError(message[len(_PANIC_ERROR_PREFIX) :].strip()) from error
    if message.startswith(_RUST_ERROR_PREFIX):
        detail = message[len(_RUST_ERROR_PREFIX) :].strip()
        rust_type, separator, rust_message = detail.partition(": ")
        if not separator:
            rust_type, rust_message = "unknown", detail
        raise CrabwalkRustError(rust_type, rust_message) from error
    if not message.startswith(_MOVE_ERROR_PREFIX):
        raise error
    detail = message[len(_MOVE_ERROR_PREFIX) :].strip()
    if value is not None:
        detail = f"{detail}; value created at {value._definition_site}"
        if value._move_site is not None:
            detail = f"{detail}; {value._move_site}"
        detail = (
            f"{detail}; pass rust.Ref or rust.Mut if the call should not consume it"
        )
    raise CrabwalkMoveError(detail) from error
