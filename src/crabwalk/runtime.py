"""Runtime decorator binding for compiled Rust functions."""

from __future__ import annotations

import inspect
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, NoReturn

from crabwalk._version import (
    GENERATED_WRAPPER_ABI_VERSION,
    PREBUILT_MANIFEST_SCHEMA_VERSION,
    RUNTIME_ABI_VERSION,
)
from crabwalk.boundary import (
    AllocationKind,
    OwnershipPolicy,
    boundary_codec,
    normalize_boundary_output,
    validate_boundary_input,
    validate_primitive,
    validate_unicode_value_tree,
)
from crabwalk.build.cache import read_json, sha256_file
from crabwalk.build.loader import load_extension
from crabwalk.compiler.codegen import function_releases_gil
from crabwalk.compiler.ir import FunctionIR, ParameterIR, TypeRef
from crabwalk.compiler.naming import owned_class_names, shared_class_names
from crabwalk.compiler.frontend import (
    analyze_project_path,
    project_source_anchor,
    project_source_identity,
)
from crabwalk.config import discover_project_config
from crabwalk.diagnostics import (
    CrabwalkCompilationError,
    CrabwalkBorrowError,
    CrabwalkMoveError,
    CrabwalkPanicError,
    CrabwalkRustError,
    CrabwalkRustErrorSource,
    CrabwalkThreadError,
    Diagnostic,
    SourceSpan,
)
from crabwalk.progress import ImplicitBuildProgress
from crabwalk.service import CompilationResult, default_service
from crabwalk.telemetry import BoundaryTelemetry
from crabwalk.native_exceptions import (
    NATIVE_BORROW_ERROR,
    NATIVE_MOVE_ERROR,
    NATIVE_PANIC_ERROR,
    NATIVE_RUST_RESULT_ERROR,
)

_compile_lock = threading.RLock()
_results: dict[tuple[str, str], CompilationResult] = {}
_owned_registry_lock = threading.RLock()

_DecoratorBindingKey = tuple[str, str, str]


@dataclass(slots=True)
class _DecoratorBindingSession:
    """One already-validated compilation while its Python bindings execute.

    Static analysis compiles every exported declaration in a package at the first
    runtime decorator. Later decorators in that same package initialization only
    need to bind symbols from that loaded extension. Keeping this session separate
    from the general artifact memo is important: once a binding repeats (a reload),
    Crabwalk re-enters ``CompilationService`` so toolchain, Cargo, lock, environment,
    and dependency inputs are fingerprinted again.
    """

    result: CompilationResult
    expected: frozenset[_DecoratorBindingKey]
    seen: set[_DecoratorBindingKey]
    validated_modules: set[str]


_binding_sessions: dict[str, _DecoratorBindingSession] = {}


@dataclass(frozen=True, slots=True)
class _OwnedTypeRegistration:
    native_type: type[Any]
    native_module: object
    fingerprint: str
    type_ref: TypeRef
    fields: tuple[tuple[str, TypeRef], ...] = ()
    variants: tuple[tuple[str, tuple[tuple[str, TypeRef], ...]], ...] = ()


@dataclass(frozen=True, slots=True)
class _SharedTypeRegistration:
    native_type: type[Any]
    fingerprint: str
    type_ref: TypeRef
    owned: _OwnedTypeRegistration


@dataclass(frozen=True, slots=True)
class _BorrowContext:
    ownership: str
    parameter: str
    parameter_site: str
    call_site: str

    def render(self) -> str:
        return (
            f"{self.ownership} parameter '{self.parameter}' defined at "
            f"{self.parameter_site}; call at {self.call_site}"
        )


@dataclass(slots=True)
class _BoundaryCounts:
    values: int = 0
    python_container_allocations: int = 0
    native_container_allocations: int = 0
    native_domain_values: int = 0
    native_clones: int = 0
    bytes_copied: int = 0


_owned_types_by_module: dict[tuple[str, str], _OwnedTypeRegistration] = {}
_owned_types_by_compilation: dict[tuple[str, str], _OwnedTypeRegistration] = {}
_shared_types_by_compilation: dict[tuple[str, str], _SharedTypeRegistration] = {}


class _RustOwnedValue:
    """A Python handle to one move-aware value stored by generated Rust."""

    __slots__ = (
        "_native",
        "_registration",
        "_type_key",
        "_move_site",
        "_field_names",
        "_field_types",
        "_enum_variants",
        "_enum_variant_types",
        "_fingerprint",
        "_thread_id",
        "_definition_site",
        "_borrow_contexts",
        "_boundary_telemetry",
    )
    _native: Any
    _registration: _OwnedTypeRegistration
    _type_key: str
    _move_site: str | None
    _field_names: tuple[str, ...]
    _field_types: dict[str, TypeRef]
    _enum_variants: dict[str, tuple[str, ...]]
    _enum_variant_types: dict[str, dict[str, TypeRef]]
    _fingerprint: str
    _thread_id: int
    _definition_site: str
    _borrow_contexts: tuple[_BorrowContext, ...]
    _boundary_telemetry: BoundaryTelemetry | None

    def __init__(
        self,
        native: object,
        registration: _OwnedTypeRegistration,
        *,
        telemetry: BoundaryTelemetry | None = None,
    ) -> None:
        fields = dict(registration.fields)
        variants = {name: dict(values) for name, values in registration.variants}
        field_names = tuple(
            fields
            or sorted(
                {
                    field_name
                    for variant_fields in variants.values()
                    for field_name in variant_fields
                }
            )
        )
        object.__setattr__(self, "_native", native)
        object.__setattr__(self, "_registration", registration)
        object.__setattr__(self, "_type_key", registration.type_ref.render())
        object.__setattr__(self, "_move_site", None)
        object.__setattr__(self, "_field_names", field_names)
        object.__setattr__(self, "_field_types", fields)
        object.__setattr__(
            self,
            "_enum_variants",
            {name: tuple(values) for name, values in variants.items()},
        )
        object.__setattr__(self, "_enum_variant_types", variants)
        object.__setattr__(self, "_fingerprint", registration.fingerprint)
        object.__setattr__(self, "_thread_id", threading.get_ident())
        object.__setattr__(self, "_definition_site", _call_location())
        object.__setattr__(self, "_borrow_contexts", ())
        object.__setattr__(self, "_boundary_telemetry", telemetry)

    @property
    def rust_type(self) -> str:
        self._check_thread()
        self._check_borrow_access("shared")
        return self._type_key

    @property
    def moved(self) -> bool:
        self._check_thread()
        self._check_borrow_access("shared")
        return bool(self._native.is_moved())

    @property
    def boundary_telemetry(self) -> BoundaryTelemetry | None:
        """Report the explicit construction boundary that created this handle."""

        self._check_thread()
        return self._boundary_telemetry

    def freeze(self) -> "_RustSharedValue":
        """Consume this handle into an immutable, cross-thread ``Arc`` handle."""

        self._check_thread()
        self._check_borrow_access("mutable")
        if self.moved:
            _raise_move_error(
                "value",
                self,
                parameter_site=self._definition_site,
                call_site=_call_location(),
            )
        with _owned_registry_lock:
            registration = _shared_types_by_compilation.get(
                (self._fingerprint, self._type_key)
            )
        if registration is None:
            raise TypeError(
                f"{self._registration.type_ref.display()} has no generated shared "
                "wrapper in this compilation; declare a rust.Shared[...] parameter "
                "for the immutable target type"
            )
        try:
            native = registration.native_type(self._native)
        except RuntimeError as error:
            _raise_translated_runtime_error(error, self)
        self._record_move("freeze()", _call_location(), self._definition_site)
        return _RustSharedValue(native, registration.owned)

    def to_python(self) -> object:
        self._check_thread()
        self._check_borrow_access("shared")
        if self._enum_variants:
            try:
                variant = self._native.variant()
                result = {"variant": variant}
                for field_name, type_ref in self._enum_variant_types[variant].items():
                    result[field_name] = _normalize_compiled_boundary_output(
                        getattr(self._native, field_name),
                        type_ref,
                        self._fingerprint,
                        deep=True,
                    )
                return result
            except RuntimeError as error:
                _raise_translated_runtime_error(error, self)
        try:
            value = self._native.to_python()
        except RuntimeError as error:
            _raise_translated_runtime_error(error, self)
        if self._registration.type_ref.rust_name == "TextColumn":
            data, offsets = value
            return {"data": bytes(data), "offsets": list(offsets)}
        if (
            self._registration.type_ref.rust_name == "Vec"
            and _type_contains_compiled_domain(self._registration.type_ref.arguments[0])
        ):
            return _normalize_compiled_boundary_output(
                value,
                self._registration.type_ref,
                self._fingerprint,
                deep=True,
            )
        if self._field_names:
            return {
                name: _normalize_compiled_boundary_output(
                    item,
                    self._field_types[name],
                    self._fingerprint,
                    deep=True,
                )
                for name, item in zip(self._field_names, value)
            }
        return normalize_boundary_output(value, self._registration.type_ref)

    def __len__(self) -> int:
        self._check_thread()
        self._check_borrow_access("shared")
        try:
            return int(len(self._native))
        except RuntimeError as error:
            _raise_translated_runtime_error(error, self)

    def __repr__(self) -> str:
        self._check_thread()
        self._check_borrow_access("shared")
        return repr(self._native)

    def __getattr__(self, name: str) -> object:
        self._check_thread()
        self._check_borrow_access("shared")
        if name not in self._field_names:
            raise AttributeError(name)
        try:
            value = getattr(self._native, name)
            if self._enum_variant_types:
                variant = self._native.variant()
                type_ref = self._enum_variant_types[variant].get(name)
                if type_ref is None or value is None:
                    return None
            else:
                type_ref = self._field_types[name]
            return _normalize_compiled_boundary_output(
                value,
                type_ref,
                self._fingerprint,
            )
        except RuntimeError as error:
            _raise_translated_runtime_error(error, self)

    def __setattr__(self, name: str, value: object) -> None:
        self._check_thread()
        self._check_borrow_access("mutable")
        if name in self._field_names:
            if self._enum_variant_types:
                raise AttributeError("Crabwalk enum payloads are immutable")
            value = _validate_compiled_boundary_input(
                value,
                self._field_types[name],
                self._fingerprint,
                context=f"field '{name}'",
            )
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

    def _check_borrow_access(self, requested: str) -> None:
        conflicts = tuple(
            context
            for context in self._borrow_contexts
            if requested == "mutable" or context.ownership == "Mut"
        )
        if conflicts:
            _raise_borrow_error(conflicts, self)


class _RustSharedValue(_RustOwnedValue):
    """An immutable ``Arc<T>`` handle whose generated payload is Send + Sync."""

    def _check_thread(self) -> None:
        return

    @property
    def moved(self) -> bool:
        return False

    def freeze(self) -> "_RustSharedValue":
        return self

    def to_python(self) -> object:
        self._check_borrow_access("shared")
        try:
            snapshot = self._native.snapshot()
        except RuntimeError as error:
            _raise_translated_runtime_error(error, self)
        return _RustOwnedValue(snapshot, self._registration).to_python()

    def __getattr__(self, name: str) -> object:
        if name not in self._field_names:
            raise AttributeError(name)
        try:
            snapshot = self._native.snapshot()
        except RuntimeError as error:
            _raise_translated_runtime_error(error, self)
        return getattr(_RustOwnedValue(snapshot, self._registration), name)

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._field_names:
            raise AttributeError("shared Crabwalk values are immutable")
        object.__setattr__(self, name, value)


def _resolve_owned_registration(
    rust_type: object,
    type_key: str,
    *,
    for_context: object | None = None,
) -> _OwnedTypeRegistration | None:
    """Resolve one wrapper without load-order-dependent ambient fallback."""

    marker_fingerprint = getattr(rust_type, "compilation_fingerprint", None)
    if isinstance(marker_fingerprint, str):
        with _owned_registry_lock:
            return _owned_types_by_compilation.get((marker_fingerprint, type_key))

    if for_context is not None and isinstance(for_context, RustFunction):
        with _owned_registry_lock:
            candidate = _owned_types_by_compilation.get(
                (for_context._compilation.fingerprint, type_key)
            )
        if candidate is not None:
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
            (registration.fingerprint, registration.native_type): registration
            for (registered_module, registered_key), registration in (
                _owned_types_by_module.items()
            )
            if registered_key == type_key
        }
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    if len(candidates) > 1:
        raise RuntimeError(
            f"Multiple generated wrappers for {rust_type!r} are loaded. "
            "Construct inside the target module or use "
            "rust.from_python(value, type, for_=compiled_function)."
        )
    return None


def _runtime_type_ref(rust_type: object) -> TypeRef:
    """Translate a runtime marker only far enough to derive its owned class name."""

    from crabwalk.compiler.ir import TypeRef
    from crabwalk.compiler.types import ErrorDomainType
    from crabwalk.rust import RustType

    if not isinstance(rust_type, RustType):
        raise TypeError("expected a Crabwalk Rust type")
    if rust_type.is_error:
        if rust_type.arguments or rust_type.python_name is None:
            raise TypeError("compiled error markers require one qualified identity")
        return ErrorDomainType(rust_type.name, rust_type.python_name)
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
    registration = _resolve_owned_registration(
        rust_type,
        type_key,
        for_context=for_context,
    )
    if registration is None:
        raise RuntimeError(
            f"No generated wrapper for {rust_type!r} is loaded. Define an "
            "@rust.fn ownership parameter or @rust.struct declaration for this "
            "concrete type before constructing it."
        )
    validation_started = time.perf_counter_ns()
    try:
        if rust_type.name == "TextColumn":
            if keywords:
                names = ", ".join(sorted(keywords))
                raise TypeError(
                    f"{rust_type!r} does not accept keyword arguments: {names}"
                )
            if len(values) != 2:
                raise TypeError(
                    f"{rust_type!r} expects data and offsets; got {len(values)} arguments"
                )
            data, offsets = _validated_text_column_input(values[0], values[1])
            validation_finished = time.perf_counter_ns()
            native_started = validation_finished
            native = registration.native_type(data, offsets)
        elif rust_type.name == "Vec" and len(rust_type.arguments) == 1:
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
            converted = _validated_owned_vector_input(values[0], registration)
            validation_finished = time.perf_counter_ns()
            native_started = validation_finished
            native = registration.native_type(converted)
        else:
            converted_values, converted_keywords = _validated_domain_arguments(
                values,
                keywords,
                registration.fields,
                registration.fingerprint,
            )
            validation_finished = time.perf_counter_ns()
            native_started = validation_finished
            native = registration.native_type(
                *_ordered_domain_arguments(
                    converted_values,
                    converted_keywords,
                    registration.fields,
                )
            )
    except (OverflowError, TypeError, ValueError) as error:
        raise type(error)(f"cannot construct {rust_type!r}: {error}") from error
    native_finished = time.perf_counter_ns()
    telemetry_value: object
    if rust_type.name == "TextColumn":
        telemetry_value = {"data": values[0], "offsets": values[1]}
    elif rust_type.name == "Vec" and len(rust_type.arguments) == 1:
        telemetry_value = values[0]
    else:
        ordered_source = _ordered_domain_arguments(
            values,
            keywords,
            registration.fields,
        )
        telemetry_value = {
            name: item for (name, _), item in zip(registration.fields, ordered_source)
        }
    counts = _modeled_boundary_counts(
        telemetry_value,
        registration.type_ref,
        registration.fingerprint,
        direction="input",
    )
    telemetry = BoundaryTelemetry(
        operation=f"construct {registration.type_ref.display()}",
        input_validation_ns=validation_finished - validation_started,
        native_ns=native_finished - native_started,
        output_normalization_ns=0,
        input_values=counts.values,
        output_values=0,
        boundary_crossings=1,
        python_container_allocations=counts.python_container_allocations,
        native_container_allocations=counts.native_container_allocations,
        native_domain_values=counts.native_domain_values,
        native_clones=counts.native_clones,
        bytes_copied=counts.bytes_copied,
    )
    return _RustOwnedValue(native, registration, telemetry=telemetry)


def _validated_text_column_input(
    data_value: object,
    offsets_value: object,
) -> tuple[bytes, list[int]]:
    """Validate the public bytes+offsets representation before native copying."""

    if isinstance(data_value, bytes):
        data = data_value
    elif isinstance(data_value, (bytearray, memoryview)):
        data = bytes(data_value)
    else:
        raise TypeError(
            f"TextColumn data must be bytes-like, found {type(data_value).__name__}"
        )
    if not isinstance(offsets_value, Sequence) or isinstance(
        offsets_value, (str, bytes, bytearray)
    ):
        raise TypeError(
            "TextColumn offsets must be a sequence of exact non-negative integers"
        )
    offsets: list[int] = []
    for index, value in enumerate(offsets_value):
        try:
            offset = validate_primitive(value, "usize")
        except (OverflowError, TypeError, ValueError) as error:
            raise type(error)(f"offset {index}: {error}") from error
        assert isinstance(offset, int)
        offsets.append(offset)
    if not offsets or offsets[0] != 0:
        raise ValueError("TextColumn offsets must start at zero")
    if offsets[-1] != len(data):
        raise ValueError("TextColumn final offset must equal the byte length")
    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        if start > end:
            raise ValueError(f"TextColumn offsets are not monotonic at row {index}")
        try:
            data[start:end].decode("utf-8")
        except UnicodeDecodeError as error:
            raise UnicodeError(
                f"TextColumn row {index} is not valid UTF-8: {error}"
            ) from error
    return data, offsets


def _validated_owned_vector_input(
    value: object,
    registration: _OwnedTypeRegistration,
) -> list[object]:
    element_type = registration.type_ref.arguments[0]
    if not _type_contains_compiled_domain(element_type):
        converted = validate_boundary_input(value, registration.type_ref)
        assert isinstance(converted, list)
        return converted
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"expected a Python sequence, found {type(value).__name__}")
    converted_values: list[object] = []
    for index, item in enumerate(value):
        converted_values.append(
            _validate_compiled_boundary_input(
                item,
                element_type,
                registration.fingerprint,
                context=f"vector element {index}",
                materialize_domains=False,
            )
        )
    return converted_values


def _validated_primitive(value: object, rust_name: str) -> object:
    return validate_primitive(value, rust_name)


def _validated_domain_arguments(
    values: tuple[object, ...],
    keywords: dict[str, object],
    fields: tuple[tuple[str, TypeRef], ...],
    fingerprint: str,
    *,
    materialize_domains: bool = True,
) -> tuple[tuple[object, ...], dict[str, object]]:
    if len(values) > len(fields):
        raise TypeError(f"expected at most {len(fields)} positional arguments")
    field_types = dict(fields)
    positional_names = {name for name, _ in fields[: len(values)]}
    unknown = set(keywords) - set(field_types)
    if unknown:
        names = ", ".join(sorted(unknown))
        raise TypeError(f"unexpected field argument(s): {names}")
    duplicate = positional_names & set(keywords)
    if duplicate:
        names = ", ".join(sorted(duplicate))
        raise TypeError(f"multiple values for field(s): {names}")
    supplied = positional_names | set(keywords)
    missing = [name for name, _ in fields if name not in supplied]
    if missing:
        raise TypeError(f"missing required field(s): {', '.join(missing)}")
    converted_values = tuple(
        _validate_compiled_boundary_input(
            value,
            fields[index][1],
            fingerprint,
            context=f"field '{fields[index][0]}'",
            materialize_domains=materialize_domains,
        )
        for index, value in enumerate(values)
    )
    converted_keywords = {
        name: _validate_compiled_boundary_input(
            value,
            field_types[name],
            fingerprint,
            context=f"field '{name}'",
            materialize_domains=materialize_domains,
        )
        for name, value in keywords.items()
    }
    return converted_values, converted_keywords


def _ordered_domain_arguments(
    positional: tuple[object, ...],
    keywords: dict[str, object],
    fields: tuple[tuple[str, TypeRef], ...],
) -> tuple[object, ...]:
    """Order validated source arguments for compiler-private PyO3 callables."""

    trailing_names = tuple(name for name, _ in fields[len(positional) :])
    return (*positional, *(keywords[name] for name in trailing_names))


def _compiled_domain_registration(
    fingerprint: str,
    type_ref: TypeRef,
) -> _OwnedTypeRegistration | None:
    if type_ref.python_name is None:
        return None
    with _owned_registry_lock:
        return _owned_types_by_compilation.get((fingerprint, type_ref.render()))


def _modeled_boundary_counts(
    value: object,
    type_ref: TypeRef,
    fingerprint: str,
    *,
    direction: str,
    counts: _BoundaryCounts | None = None,
) -> _BoundaryCounts:
    """Count codec-defined work without pretending to sample the allocator."""

    result = counts or _BoundaryCounts()
    result.values += 1
    if type_ref.rust_name == "TextColumn":
        result.python_container_allocations += 1
        if direction == "input":
            result.native_container_allocations += 2
        if isinstance(value, Mapping):
            data = value.get("data")
            if isinstance(data, (bytes, bytearray, memoryview)):
                result.bytes_copied += len(data)
            offsets = value.get("offsets")
            if isinstance(offsets, Sequence):
                result.values += len(offsets)
        return result
    registration = _compiled_domain_registration(fingerprint, type_ref)
    if registration is not None:
        if direction == "input":
            if isinstance(value, _RustOwnedValue):
                result.native_clones += 1
                return result
            result.native_domain_values += 1
            result.python_container_allocations += 1
        elif isinstance(value, Mapping):
            result.python_container_allocations += 1
        if isinstance(value, Mapping):
            for name, child in registration.fields:
                if name in value:
                    _modeled_boundary_counts(
                        value[name],
                        child,
                        fingerprint,
                        direction=direction,
                        counts=result,
                    )
        return result

    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        if value is not None:
            _modeled_boundary_counts(
                value,
                type_ref.arguments[0],
                fingerprint,
                direction=direction,
                counts=result,
            )
        return result

    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        result.python_container_allocations += 1
        if isinstance(value, Sequence):
            for item, child in zip(value, type_ref.arguments):
                _modeled_boundary_counts(
                    item,
                    child,
                    fingerprint,
                    direction=direction,
                    counts=result,
                )
        return result

    if type_ref.rust_name in {"Vec", "Array"} and len(type_ref.arguments) == 1:
        result.python_container_allocations += 1
        if direction == "input":
            result.native_container_allocations += 1
        child = type_ref.arguments[0]
        if isinstance(value, Sequence) and not isinstance(value, str):
            for item in value:
                _modeled_boundary_counts(
                    item,
                    child,
                    fingerprint,
                    direction=direction,
                    counts=result,
                )
        if child.rust_name == "u8" and isinstance(value, (bytes, bytearray)):
            result.bytes_copied += len(value)
        return result

    if type_ref.rust_name == "HashMap" and len(type_ref.arguments) == 2:
        result.python_container_allocations += 1
        if direction == "input":
            result.native_container_allocations += 1
        if isinstance(value, Mapping):
            key_type, value_type = type_ref.arguments
            for key, item in value.items():
                _modeled_boundary_counts(
                    key,
                    key_type,
                    fingerprint,
                    direction=direction,
                    counts=result,
                )
                _modeled_boundary_counts(
                    item,
                    value_type,
                    fingerprint,
                    direction=direction,
                    counts=result,
                )
        return result

    if type_ref.rust_name in {"String", "Str"} and isinstance(value, str):
        result.bytes_copied += len(value.encode("utf-8"))
        if direction == "input" and type_ref.rust_name == "String":
            result.native_container_allocations += 1
    return result


def _validate_compiled_boundary_input(
    value: object,
    type_ref: TypeRef,
    fingerprint: str,
    *,
    context: str,
    materialize_domains: bool = True,
) -> object:
    """Validate one boundary value, including compilation-bound domain values."""

    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        if value is None:
            return None
        return _validate_compiled_boundary_input(
            value,
            type_ref.arguments[0],
            fingerprint,
            context=context,
            materialize_domains=materialize_domains,
        )
    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        if type(value) is not tuple:
            raise TypeError(f"{context}: expected tuple, found {type(value).__name__}")
        if len(value) != len(type_ref.arguments):
            raise ValueError(
                f"{context}: expected {len(type_ref.arguments)} tuple items, "
                f"found {len(value)}"
            )
        return tuple(
            _validate_compiled_boundary_input(
                item,
                child,
                fingerprint,
                context=f"{context} tuple item {index}",
                materialize_domains=materialize_domains,
            )
            for index, (item, child) in enumerate(zip(value, type_ref.arguments))
        )
    if type_ref.rust_name in {"Vec", "Array"} and len(type_ref.arguments) == 1:
        if not _type_contains_compiled_domain(type_ref.arguments[0]):
            return validate_boundary_input(value, type_ref)
        if not isinstance(value, Sequence) or isinstance(
            value, (str, bytes, bytearray)
        ):
            raise TypeError(
                f"{context}: expected a Python sequence, found {type(value).__name__}"
            )
        if type_ref.rust_name == "Array" and len(value) != type_ref.const_value:
            raise ValueError(
                f"{context}: expected {type_ref.const_value} items, found {len(value)}"
            )
        return [
            _validate_compiled_boundary_input(
                item,
                type_ref.arguments[0],
                fingerprint,
                context=f"{context} element {index}",
                materialize_domains=materialize_domains,
            )
            for index, item in enumerate(value)
        ]
    if type_ref.rust_name == "HashMap" and len(type_ref.arguments) == 2:
        if not isinstance(value, Mapping):
            raise TypeError(
                f"{context}: expected a Python mapping, found {type(value).__name__}"
            )
        key_type, value_type = type_ref.arguments
        converted: dict[object, object] = {}
        for index, (key, item) in enumerate(value.items()):
            converted_key = _validate_compiled_boundary_input(
                key,
                key_type,
                fingerprint,
                context=f"{context} mapping key {index}",
                materialize_domains=materialize_domains,
            )
            converted[converted_key] = _validate_compiled_boundary_input(
                item,
                value_type,
                fingerprint,
                context=f"{context} mapping value for key {key!r}",
                materialize_domains=materialize_domains,
            )
        return converted

    registration = _compiled_domain_registration(fingerprint, type_ref)
    if registration is None:
        if type_ref.python_name is not None:
            raise RuntimeError(
                f"missing compiled domain registration for {type_ref.display()}"
            )
        return validate_boundary_input(value, type_ref)

    if isinstance(value, _RustOwnedValue):
        value._check_thread()
        if value.moved:
            raise CrabwalkMoveError(f"{context} is an already-moved Rust value")
        if value._fingerprint != fingerprint or value._type_key != type_ref.render():
            raise TypeError(
                f"{context} belongs to a different compiled {type_ref.display()} type"
            )
        return value._native

    if isinstance(value, Mapping):
        positional, keywords = _validated_domain_arguments(
            (),
            dict(value),
            registration.fields,
            fingerprint,
            materialize_domains=materialize_domains,
        )
        if not materialize_domains:
            ordered = _ordered_domain_arguments(
                positional,
                keywords,
                registration.fields,
            )
            return {name: item for (name, _), item in zip(registration.fields, ordered)}
        return registration.native_type(
            *_ordered_domain_arguments(positional, keywords, registration.fields)
        )

    raise TypeError(
        f"{context}: expected {type_ref.display()} handle or mapping, "
        f"found {type(value).__name__}"
    )


def _normalize_compiled_boundary_output(
    value: object,
    type_ref: TypeRef,
    fingerprint: str,
    *,
    deep: bool = False,
) -> object:
    """Normalize native output while preserving compiled domain identity."""

    if type_ref.rust_name == "Option" and len(type_ref.arguments) == 1:
        if value is None:
            return None
        return _normalize_compiled_boundary_output(
            value,
            type_ref.arguments[0],
            fingerprint,
            deep=deep,
        )
    if type_ref.rust_name == "Tuple" and type_ref.arguments:
        if type(value) is not tuple or len(value) != len(type_ref.arguments):
            raise TypeError("native tuple output did not match its compiled codec")
        return tuple(
            _normalize_compiled_boundary_output(
                item,
                child,
                fingerprint,
                deep=deep,
            )
            for item, child in zip(value, type_ref.arguments)
        )
    if type_ref.rust_name in {"Vec", "Array"} and len(type_ref.arguments) == 1:
        if not _type_contains_compiled_domain(type_ref.arguments[0]):
            return normalize_boundary_output(value, type_ref)
        if not isinstance(value, (list, tuple)):
            raise TypeError("native vector output did not produce a sequence")
        return [
            _normalize_compiled_boundary_output(
                item,
                type_ref.arguments[0],
                fingerprint,
                deep=deep,
            )
            for item in value
        ]
    if type_ref.rust_name == "HashMap" and len(type_ref.arguments) == 2:
        if not isinstance(value, Mapping):
            raise TypeError("native map output did not produce a mapping")
        key_type, value_type = type_ref.arguments
        return {
            _normalize_compiled_boundary_output(
                key,
                key_type,
                fingerprint,
                deep=deep,
            ): _normalize_compiled_boundary_output(
                item,
                value_type,
                fingerprint,
                deep=deep,
            )
            for key, item in value.items()
        }

    registration = _compiled_domain_registration(fingerprint, type_ref)
    if registration is None:
        if type_ref.python_name is not None:
            raise RuntimeError(
                f"missing compiled domain registration for {type_ref.display()}"
            )
        return normalize_boundary_output(value, type_ref)
    wrapped = _RustOwnedValue(value, registration)
    return wrapped.to_python() if deep else wrapped


def _type_contains_compiled_domain(type_ref: TypeRef) -> bool:
    return type_ref.python_name is not None or any(
        _type_contains_compiled_domain(value) for value in type_ref.arguments
    )


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
    registration = _resolve_owned_registration(rust_type, type_key)
    if registration is None:
        raise RuntimeError(f"No generated wrapper for {rust_type!r} is loaded.")
    try:
        variant_fields = dict(registration.variants)[variant]
        converted_values, converted_keywords = _validated_domain_arguments(
            values,
            keywords,
            variant_fields,
            registration.fingerprint,
        )
        constructor = getattr(registration.native_type, variant)
        native = constructor(
            *_ordered_domain_arguments(
                converted_values,
                converted_keywords,
                variant_fields,
            )
        )
    except (AttributeError, OverflowError, TypeError, ValueError) as error:
        raise type(error)(
            f"cannot construct {rust_type!r}.{variant}: {error}"
        ) from error
    return _RustOwnedValue(native, registration)


def _validate_unicode_value_tree(value: object) -> None:
    validate_unicode_value_tree(value)


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
        original: Callable[..., object] | None,
        native: Callable[..., object],
        compilation: CompilationResult,
        *,
        function_ir: FunctionIR | None = None,
    ) -> None:
        self._native = native
        self._compilation = compilation
        if function_ir is None:
            if original is None:
                raise TypeError("a source declaration or FunctionIR is required")
            function_ir = next(
                value
                for value in compilation.ir.functions
                if value.name == original.__name__
                and (not value.module_name or value.module_name == original.__module__)
            )
        if original is None:
            self.__name__ = function_ir.name
            self.__qualname__ = function_ir.name
            self.__module__ = function_ir.module_name or compilation.ir.module_name
            self.__doc__ = None
            self.__annotations__ = {
                **{
                    parameter.name: parameter.type_ref.display()
                    for parameter in function_ir.parameters
                },
                "return": function_ir.return_type.display(),
            }
            self.__signature__ = inspect.Signature(
                tuple(
                    inspect.Parameter(
                        parameter.name,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        default=(
                            parameter.default_value
                            if parameter.has_default
                            else inspect.Parameter.empty
                        ),
                        annotation=parameter.type_ref.display(),
                    )
                    for parameter in function_ir.parameters
                ),
                return_annotation=function_ir.return_type.display(),
            )
        else:
            self.__name__ = original.__name__
            self.__qualname__ = original.__qualname__
            self.__module__ = original.__module__
            self.__doc__ = original.__doc__
            self.__annotations__ = dict(getattr(original, "__annotations__", {}))
            self.__signature__ = inspect.signature(original)
        self._rust_symbol = function_ir.rust_symbol
        self._parameters = function_ir.parameters
        self._return_type = (
            function_ir.return_type.arguments[0]
            if function_ir.return_type.rust_name == "Result"
            else function_ir.return_type
        )
        self._releases_gil = function_releases_gil(function_ir)
        self._release_gil_requested = function_ir.release_gil
        self._effects = function_ir.effects

    def __call__(self, *args: object, **kwargs: object) -> object:
        result, _ = self._invoke(args, kwargs, telemetry=False)
        return result

    def call_with_telemetry(
        self,
        *args: object,
        **kwargs: object,
    ) -> tuple[object, BoundaryTelemetry]:
        """Call native code and return phase/cardinality boundary evidence."""

        result, report = self._invoke(args, kwargs, telemetry=True)
        assert report is not None
        return result, report

    def _invoke(
        self,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        *,
        telemetry: bool,
    ) -> tuple[object, BoundaryTelemetry | None]:
        validation_started = time.perf_counter_ns()
        try:
            bound = self.__signature__.bind(*args, **kwargs)
        except TypeError as error:
            raise TypeError(f"{self.__qualname__}: {error}") from error
        bound.apply_defaults()
        bound_values = tuple(
            bound.arguments[parameter.name] for parameter in self._parameters
        )
        native_args = list(bound_values)
        owned_arguments: list[tuple[ParameterIR, _RustOwnedValue]] = []
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
            if parameter.type_ref.ownership == "Shared":
                if not isinstance(value, _RustSharedValue):
                    raise TypeError(
                        f"argument '{parameter.name}' to {self.__qualname__} requires "
                        "an immutable shared handle; call value.freeze() first"
                    )
            elif isinstance(value, _RustSharedValue):
                raise TypeError(
                    f"argument '{parameter.name}' to {self.__qualname__} requires "
                    f"rust.{parameter.type_ref.ownership}, not rust.Shared"
                )
            value._check_thread()
            expected_key = parameter.type_ref.underlying.render()
            if value._type_key != expected_key:
                raise TypeError(
                    f"argument '{parameter.name}' to {self.__qualname__} expects "
                    f"{expected_key}, found {value._type_key}"
                )
            class_names = (
                shared_class_names(parameter.type_ref.underlying)
                if parameter.type_ref.ownership == "Shared"
                else owned_class_names(parameter.type_ref.underlying)
            )
            python_name, _ = class_names
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

        # Check every ownership handle before the generated wrapper can take any
        # Owned value. The native wrapper repeats this preflight authoritatively;
        # doing it here preserves source-rich diagnostics for normal Python calls.
        call_location = _call_location() if owned_arguments else ""
        for parameter, value in owned_arguments:
            if value.moved:
                _raise_move_error(
                    parameter.name,
                    value,
                    parameter_site=_span_location(parameter.span),
                    call_site=call_location,
                )

        aliases: dict[int, list[tuple[ParameterIR, _RustOwnedValue]]] = {}
        for parameter, value in owned_arguments:
            aliases.setdefault(id(value), []).append((parameter, value))
        for alias_group in aliases.values():
            if len(alias_group) < 2 or not any(
                parameter.type_ref.ownership in {"Owned", "Mut"}
                for parameter, _ in alias_group
            ):
                continue
            contexts = tuple(
                _BorrowContext(
                    parameter.type_ref.ownership or "Owned",
                    parameter.name,
                    _span_location(parameter.span),
                    call_location,
                )
                for parameter, _ in alias_group
            )
            _raise_borrow_error(contexts, alias_group[0][1])

        prior_borrow_contexts: dict[
            int, tuple[_RustOwnedValue, tuple[_BorrowContext, ...]]
        ] = {}
        for parameter, value in owned_arguments:
            if parameter.type_ref.ownership not in {"Ref", "Mut"}:
                continue
            identity = id(value)
            if identity not in prior_borrow_contexts:
                prior_borrow_contexts[identity] = (value, value._borrow_contexts)
            context = _BorrowContext(
                parameter.type_ref.ownership,
                parameter.name,
                _span_location(parameter.span),
                call_location,
            )
            object.__setattr__(
                value,
                "_borrow_contexts",
                (*value._borrow_contexts, context),
            )
        validation_finished = time.perf_counter_ns()
        native_started = validation_finished
        try:
            result = self._native(*native_args)
        except RuntimeError as error:
            _raise_translated_runtime_error(
                error,
                owned_arguments=tuple(owned_arguments),
                native_module=self._compilation.module,
                call_site=call_location or _call_location(),
            )
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
        native_finished = time.perf_counter_ns()
        output_started = native_finished
        normalized: object
        if self._return_type.ownership == "Owned":
            underlying = self._return_type.underlying
            with _owned_registry_lock:
                registration = _owned_types_by_compilation.get(
                    (self._compilation.fingerprint, underlying.render())
                )
            if registration is None:
                raise RuntimeError(
                    f"missing owned return registration for {underlying.display()}"
                )
            normalized = _RustOwnedValue(result, registration)
        else:
            normalized = normalize_boundary_output(result, self._return_type)
        output_finished = time.perf_counter_ns()
        if not telemetry:
            return normalized, None

        counts = _BoundaryCounts()
        for argument, parameter in zip(bound_values, self._parameters):
            if parameter.type_ref.ownership is not None:
                counts.values += 1
                continue
            _modeled_boundary_counts(
                argument,
                parameter.type_ref,
                self._compilation.fingerprint,
                direction="input",
                counts=counts,
            )
        output_counts = _modeled_boundary_counts(
            normalized,
            self._return_type.underlying,
            self._compilation.fingerprint,
            direction="output",
        )
        report = BoundaryTelemetry(
            operation=f"call {self.__module__}.{self.__qualname__}",
            input_validation_ns=validation_finished - validation_started,
            native_ns=native_finished - native_started,
            output_normalization_ns=output_finished - output_started,
            input_values=counts.values,
            output_values=output_counts.values,
            boundary_crossings=1,
            python_container_allocations=(
                counts.python_container_allocations
                + output_counts.python_container_allocations
            ),
            native_container_allocations=counts.native_container_allocations,
            native_domain_values=counts.native_domain_values,
            native_clones=counts.native_clones,
            bytes_copied=counts.bytes_copied + output_counts.bytes_copied,
        )
        return normalized, report

    def __repr__(self) -> str:
        fingerprint = self._compilation.fingerprint[:12]
        return (
            f"<crabwalk RustFunction {self.__module__}.{self.__qualname__} "
            f"[{fingerprint}]>"
        )

    @property
    def __crabwalk__(self) -> dict[str, object]:
        parameter_boundaries = {
            parameter.name: _boundary_metadata(parameter.type_ref)
            for parameter in self._parameters
        }
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
            "gil_policy": (
                "explicit audited release" if self._release_gil_requested else "auto"
            ),
            "async_eligible": self._releases_gil,
            "effects": self._effects,
            "parameter_boundaries": parameter_boundaries,
            "boundary_telemetry": {
                "call_api": "call_with_telemetry",
                "timing_unit": "nanoseconds",
                "counts": "codec-modeled",
                "phases": (
                    "input_validation",
                    "native",
                    "output_normalization",
                ),
            },
            "cargo_policy": _cargo_policy_metadata(self._compilation),
            "dependency_lock_hash": _dependency_lock_hash_metadata(self._compilation),
        }


def _boundary_metadata(type_ref: TypeRef) -> dict[str, object]:
    codec = boundary_codec(type_ref)
    borrowed = codec.ownership in {
        OwnershipPolicy.BORROW,
        OwnershipPolicy.SHARED_BORROW,
        OwnershipPolicy.MUTABLE_BORROW,
    }
    return {
        "rust_type": type_ref.display(),
        "input_policy": codec.input_policy.value,
        "allocation": codec.allocation.value,
        "ownership": codec.ownership.value,
        "borrowed": borrowed,
        "copies_elements": not borrowed
        and codec.allocation
        in {AllocationKind.NATIVE_CONTAINER, AllocationKind.PYTHON_CONTAINER},
        "lifetime": "native call" if borrowed else None,
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
    if not isinstance(type_ref, TypeRef):
        raise TypeError("invalid compiled boundary type")
    return validate_boundary_input(value, type_ref)


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
        cached = _compilation_for(
            path,
            function.__module__,
            ("function", function.__module__, function.__name__),
        )
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


def _bind_compilation_function(
    compilation: CompilationResult,
    function_ir: FunctionIR,
) -> RustFunction:
    """Bind an exported IR function without executing its Python declaration."""

    if not function_ir.exported:
        raise ValueError(f"{function_ir.qualified_name} is native-only")
    module = compilation.module
    if module is None:
        raise AssertionError("loaded compilation has no extension module")
    _register_owned_types(compilation)
    try:
        native = getattr(module, function_ir.rust_symbol)
    except AttributeError as error:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB402",
                "Native symbol is missing",
                f"The generated extension does not export {function_ir.name}.",
                function_ir.span,
            )
        ) from error
    return RustFunction(
        None,
        native,
        compilation,
        function_ir=function_ir,
    )


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
        cached = _compilation_for(
            path,
            original.__module__,
            ("struct", original.__module__, original.__name__),
        )
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
        compilation_fingerprint=cached.fingerprint,
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
        cached = _compilation_for(
            path,
            original.__module__,
            ("enum", original.__module__, original.__name__),
        )
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
        compilation_fingerprint=cached.fingerprint,
        is_error=enum_ir.is_error,
    )


def _compilation_for(
    path: Path,
    module_name: str,
    binding_key: _DecoratorBindingKey,
) -> CompilationResult:
    """Resolve one loaded compilation for all decorators in a source package."""

    anchor = project_source_anchor(path)
    session_key = str(anchor)
    session = _binding_sessions.get(session_key)
    if session is not None:
        reusable = binding_key in session.expected and binding_key not in session.seen
        if reusable and module_name not in session.validated_modules:
            # A package may import compiler-visible submodules lazily. Validate the
            # package source identity once when each such module first binds so an
            # edit made after the initial package import cannot select stale native
            # symbols. Repeated bindings in one module do not rehash the package.
            reusable = (
                project_source_identity(path) == session.result.ir.compiler_input_hash
            )
            if reusable:
                session.validated_modules.add(module_name)
        if reusable:
            session.seen.add(binding_key)
            if session.seen == session.expected:
                _binding_sessions.pop(session_key, None)
            return session.result
        # A repeated binding is the start of a reload. Unknown or source-divergent
        # bindings likewise require a new complete build plan.
        _binding_sessions.pop(session_key, None)

    label = anchor.parent.name if anchor.name == "__init__.py" else anchor.stem
    progress = ImplicitBuildProgress(label)
    progress.start()
    try:
        # Always enter the service so native dependency, toolchain, Cargo config,
        # environment, and lock inputs participate in the complete fingerprint.
        # A source-only memo here would bypass those stronger checks on reload.
        result = _load_prebuilt_compilation(path, module_name)
        if result is None:
            config = discover_project_config(path)
            result = default_service.compile_path(
                path,
                module_name=module_name,
                mode="build",
                load=True,
                locked=config.source_locked if config is not None else False,
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
    expected = _runtime_decorator_bindings(cached)
    if binding_key in expected and len(expected) > 1:
        session = _DecoratorBindingSession(
            cached,
            expected,
            {binding_key},
            {module_name},
        )
        if session.seen != session.expected:
            _binding_sessions[session_key] = session
    return cached


def _runtime_decorator_bindings(
    compilation: CompilationResult,
) -> frozenset[_DecoratorBindingKey]:
    """Return declarations whose Python decorators bind the loaded extension."""

    ir = compilation.ir
    return frozenset(
        [
            ("function", function.module_name, function.name)
            for function in ir.functions
            if function.exported
        ]
        + [("struct", struct.module_name, struct.name) for struct in ir.structs]
        + [("enum", enum.module_name, enum.name) for enum in ir.enums]
    )


def _cargo_policy_metadata(compilation: CompilationResult) -> dict[str, object]:
    inputs = compilation.build_inputs or {}
    policy = inputs.get("cargo_policy")
    if isinstance(policy, dict):
        return {
            "locked": bool(policy.get("locked", False)),
            "offline": bool(policy.get("offline", False)),
            "origin": (
                "prebuilt" if compilation.cache_status == "prebuilt" else "source"
            ),
        }
    return {
        "locked": None,
        "offline": None,
        "origin": "prebuilt" if compilation.cache_status == "prebuilt" else "unknown",
    }


def _dependency_lock_hash_metadata(compilation: CompilationResult) -> str | None:
    inputs = compilation.build_inputs or {}
    value = inputs.get("dependency_lock_hash")
    return value if isinstance(value, str) else None


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
        "compiler_input_hash": str,
        "wheel_source_integrity_hash": str,
        "crabwalk_version": str,
        "runtime_abi_version": int,
        "generated_wrapper_abi_version": int,
        "runtime_compatibility_specifier": str,
        "cargo_policy": dict,
        "dependency_lock_hash": str,
    }
    cargo_policy = manifest.get("cargo_policy")
    dependency_lock_hash = manifest.get("dependency_lock_hash")
    if (
        manifest.get("schema_version") != PREBUILT_MANIFEST_SCHEMA_VERSION
        or any(
            not isinstance(manifest.get(name), expected_type)
            for name, expected_type in expected_fields.items()
        )
        or not isinstance(cargo_policy, dict)
        or not isinstance(cargo_policy.get("locked"), bool)
        or not isinstance(cargo_policy.get("offline"), bool)
        or not isinstance(dependency_lock_hash, str)
        or len(dependency_lock_hash) != 64
        or any(
            character not in "0123456789abcdef" for character in dependency_lock_hash
        )
    ):
        _invalid_prebuilt(ir, "The embedded manifest has an unsupported schema.")
    assert isinstance(cargo_policy, dict)
    assert isinstance(dependency_lock_hash, str)
    if manifest["runtime_abi_version"] != RUNTIME_ABI_VERSION:
        _invalid_prebuilt(
            ir,
            "The embedded native artifact uses a different Crabwalk runtime ABI.",
        )
    if manifest["generated_wrapper_abi_version"] != GENERATED_WRAPPER_ABI_VERSION:
        _invalid_prebuilt(
            ir,
            "The embedded native artifact uses a different generated-wrapper ABI.",
        )
    if manifest["compiler_input_hash"] != ir.compiler_input_hash:
        _invalid_prebuilt(
            ir,
            "The installed native compiler inputs do not match the embedded artifact.",
        )
    if manifest["wheel_source_integrity_hash"] != ir.wheel_source_integrity_hash:
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
        build_inputs={
            "cargo_policy": {
                "locked": cargo_policy["locked"],
                "offline": cargo_policy["offline"],
            },
            "dependency_lock_hash": dependency_lock_hash,
        },
    )


def _invalid_prebuilt(ir: object, message: str) -> NoReturn:
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


def _ir_primary_span(ir: object) -> SourceSpan | None:
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
        (
            function.module_name or compilation.ir.module_name,
            function.return_type.underlying,
        )
        for function in compilation.ir.functions
        if function.exported and function.return_type.ownership == "Owned"
    )
    concrete_types.update(
        (struct.module_name, struct.type_ref) for struct in compilation.ir.structs
    )
    concrete_types.update(
        (enum.module_name, enum.type_ref)
        for enum in compilation.ir.enums
        if not enum.is_error
    )
    structs = {struct.type_ref.render(): struct for struct in compilation.ir.structs}
    enums = {
        enum.type_ref.render(): enum
        for enum in compilation.ir.enums
        if not enum.is_error
    }
    shared_types = {
        parameter.type_ref.underlying.render(): parameter.type_ref.underlying
        for function in compilation.ir.functions
        if function.exported
        for parameter in function.parameters
        if parameter.type_ref.ownership == "Shared"
    }
    with _owned_registry_lock:
        for module_name, type_ref in concrete_types:
            python_name, _ = owned_class_names(type_ref)
            native_type = getattr(module, python_name)
            type_key = type_ref.render()
            struct = structs.get(type_key)
            enum = enums.get(type_key)
            fields = (
                tuple((field.name, field.type_ref) for field in struct.fields)
                if struct is not None
                else ()
            )
            variants = (
                tuple(
                    (
                        variant.name,
                        tuple((field.name, field.type_ref) for field in variant.fields),
                    )
                    for variant in enum.variants
                )
                if enum is not None
                else ()
            )
            registration = _OwnedTypeRegistration(
                native_type,
                module,
                compilation.fingerprint,
                type_ref,
                fields,
                variants,
            )
            _owned_types_by_module[(module_name, type_key)] = registration
            _owned_types_by_compilation[(compilation.fingerprint, type_key)] = (
                registration
            )
        for type_key, type_ref in shared_types.items():
            python_name, _ = shared_class_names(type_ref)
            owned = _owned_types_by_compilation[(compilation.fingerprint, type_key)]
            _shared_types_by_compilation[(compilation.fingerprint, type_key)] = (
                _SharedTypeRegistration(
                    getattr(module, python_name),
                    compilation.fingerprint,
                    type_ref,
                    owned,
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
    *,
    owned_arguments: tuple[tuple[ParameterIR, _RustOwnedValue], ...] = (),
    native_module: object | None = None,
    call_site: str | None = None,
) -> NoReturn:
    if native_module is None and value is not None:
        native_module = value._registration.native_module

    if _is_native_exception(error, native_module, NATIVE_PANIC_ERROR):
        message = _native_error_argument(error, 0, str(error))
        raise CrabwalkPanicError(message, call_site=call_site) from error

    if _is_native_exception(error, native_module, NATIVE_RUST_RESULT_ERROR):
        rust_type = _native_error_argument(error, 0, "unknown")
        rust_message = _native_error_argument(error, 1, str(error))
        variant = _native_error_optional_argument(error, 2)
        fields = dict(_native_error_pairs(error, 3))
        sources = tuple(
            CrabwalkRustErrorSource(source_type, source_message)
            for source_type, source_message in _native_error_pairs(error, 4)
        )
        raise CrabwalkRustError(
            rust_type,
            rust_message,
            call_site=call_site,
            variant=variant,
            fields=fields,
            source_chain=sources,
        ) from error

    if _is_native_exception(error, native_module, NATIVE_BORROW_ERROR):
        parameter = _native_error_argument(error, 0, "")
        message = _native_error_argument(error, 1, "native borrow conflict")
        details = [f"conflicting call-scoped Rust borrow: {message}"]
        if parameter:
            details.append(f"parameter '{parameter}'")
        public_error = CrabwalkBorrowError(
            "; ".join(details),
            parameters=(parameter,) if parameter else (),
            definition_site=value._definition_site if value is not None else None,
            call_site=call_site,
        )
        raise public_error from error

    if not _is_native_exception(error, native_module, NATIVE_MOVE_ERROR):
        raise error

    parameter = _native_error_argument(error, 0, "")
    selected = value
    parameter_site: str | None = None
    if parameter:
        for candidate_parameter, candidate_value in owned_arguments:
            if getattr(candidate_parameter, "name", None) != parameter:
                continue
            selected = candidate_value
            parameter_site = _span_location(candidate_parameter.span)
            break
    _raise_move_error(
        parameter,
        selected,
        parameter_site=parameter_site,
        call_site=call_site,
        cause=error,
    )


def _is_native_exception(
    error: BaseException,
    native_module: object | None,
    attribute: str,
) -> bool:
    native_type = getattr(native_module, attribute, None)
    return isinstance(native_type, type) and type(error) is native_type


def _native_error_argument(error: BaseException, index: int, fallback: str) -> str:
    if index < len(error.args) and isinstance(error.args[index], str):
        return error.args[index]
    return fallback


def _native_error_optional_argument(error: BaseException, index: int) -> str | None:
    if index < len(error.args) and isinstance(error.args[index], str):
        return error.args[index]
    return None


def _native_error_pairs(
    error: BaseException,
    index: int,
) -> tuple[tuple[str, str], ...]:
    if index >= len(error.args) or not isinstance(error.args[index], (list, tuple)):
        return ()
    result: list[tuple[str, str]] = []
    for value in error.args[index]:
        if (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and isinstance(value[0], str)
            and isinstance(value[1], str)
        ):
            result.append((value[0], value[1]))
    return tuple(result)


def _raise_move_error(
    parameter: str,
    value: _RustOwnedValue | None,
    *,
    parameter_site: str | None = None,
    call_site: str | None = None,
    cause: BaseException | None = None,
) -> NoReturn:
    detail = f"{parameter} was moved" if parameter else "value was moved"
    definition_site = value._definition_site if value is not None else None
    move_site = value._move_site if value is not None else None
    if definition_site is not None:
        detail = f"{detail}; value created at {definition_site}"
    if move_site is not None:
        detail = f"{detail}; {move_site}"
    if value is not None:
        detail = (
            f"{detail}; pass rust.Ref or rust.Mut if the call should not consume it"
        )
    public_error = CrabwalkMoveError(
        detail,
        parameter=parameter or None,
        definition_site=definition_site,
        move_site=move_site,
        parameter_site=parameter_site,
        call_site=call_site,
    )
    if cause is None:
        raise public_error
    raise public_error from cause


def _raise_borrow_error(
    contexts: tuple[_BorrowContext, ...],
    value: _RustOwnedValue,
) -> NoReturn:
    details = ["conflicting call-scoped Rust borrow"]
    details.append(f"value created at {value._definition_site}")
    details.extend(context.render() for context in contexts)
    details.append(
        "use separate values or change the signature so one alias is not "
        "borrowed as both rust.Ref, rust.Mut, or rust.Owned"
    )
    raise CrabwalkBorrowError(
        "; ".join(details),
        parameters=tuple(context.parameter for context in contexts),
        definition_site=value._definition_site,
        parameter_sites=tuple(context.parameter_site for context in contexts),
        call_site=contexts[0].call_site if contexts else None,
    )
