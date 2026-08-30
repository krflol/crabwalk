"""Source-spanned semantic IR shared by all Crabwalk frontends."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Literal, TypeAlias

from crabwalk.diagnostics import SourceSpan
from . import types as _types
from .symbols import BindingIR, SymbolId

BOOL = _types.BOOL
CHAR = _types.CHAR
F64 = _types.F64
I64 = _types.I64
INFERRED = _types.INFERRED
STR = _types.STR
STRING = _types.STRING
UNIT = _types.UNIT
U64 = _types.U64
USIZE = _types.USIZE
TypeRef = _types.TypeRef


class Effect(StrEnum):
    """Semantic effects that constrain native execution and ABI policy."""

    NATIVE_RUST = "NativeRust"
    CONVERSION_BOUNDARY = "ConversionBoundary"
    BORROWED_BUFFER = "BorrowedBuffer"
    OPAQUE_CRATE_CALL = "OpaqueCrateCall"
    PYTHON_RUNTIME = "PythonRuntime"
    BLOCKING = "Blocking"
    THREAD_SPAWN = "ThreadSpawn"
    GLOBAL_MUTATION = "GlobalMutation"
    UNSAFE_MEMORY = "UnsafeMemory"
    UNSAFE_FFI = "UnsafeFfi"
    MAY_PANIC = "MayPanic"


@dataclass(frozen=True, slots=True)
class CrateIR:
    binding: str
    package: str
    version: str | None
    features: tuple[str, ...]
    path: str | None
    git: str | None
    rev: str | None
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class StructFieldIR:
    name: str
    type_ref: TypeRef
    span: SourceSpan
    binding: BindingIR | None = None

    @property
    def rust_name(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.name


@dataclass(frozen=True, slots=True)
class StructIR:
    name: str
    module_name: str
    symbol: str
    fields: tuple[StructFieldIR, ...]
    derives: tuple[tuple[str, ...], ...]
    span: SourceSpan
    symbol_id: SymbolId | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.module_name}.{self.name}" if self.module_name else self.name

    @property
    def type_ref(self) -> TypeRef:
        return _types.DomainType(self.symbol, self.qualified_name)


@dataclass(frozen=True, slots=True)
class EnumVariantIR:
    name: str
    fields: tuple[StructFieldIR, ...]
    tuple_style: bool
    span: SourceSpan
    binding: BindingIR | None = None
    from_source: TypeRef | None = None

    @property
    def rust_name(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.name


@dataclass(frozen=True, slots=True)
class EnumIR:
    name: str
    module_name: str
    symbol: str
    variants: tuple[EnumVariantIR, ...]
    derives: tuple[tuple[str, ...], ...]
    span: SourceSpan
    symbol_id: SymbolId | None = None
    is_error: bool = False

    @property
    def qualified_name(self) -> str:
        return f"{self.module_name}.{self.name}" if self.module_name else self.name

    @property
    def type_ref(self) -> TypeRef:
        if self.is_error:
            return _types.ErrorDomainType(self.symbol, self.qualified_name)
        return _types.DomainType(self.symbol, self.qualified_name)


@dataclass(frozen=True, slots=True)
class TraitMethodIR:
    name: str
    return_type: TypeRef
    span: SourceSpan
    parameter_types: tuple[TypeRef, ...] = ()
    receiver_ownership: Literal["Ref", "Mut", "Owned"] = "Ref"
    type_parameters: tuple["TypeParameterIR", ...] = ()
    binding: BindingIR | None = None

    @property
    def rust_name(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.name


@dataclass(frozen=True, slots=True)
class TraitIR:
    name: str
    module_name: str
    symbol: str
    methods: tuple[TraitMethodIR, ...]
    span: SourceSpan
    symbol_id: SymbolId | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.module_name}.{self.name}" if self.module_name else self.name

    @property
    def type_ref(self) -> TypeRef:
        return _types.TraitMarkerType(self.symbol)


@dataclass(frozen=True, slots=True)
class ParameterIR:
    name: str
    type_ref: TypeRef
    span: SourceSpan
    mutable: bool = False
    binding: BindingIR | None = None
    has_default: bool = False
    default_value: object | None = None

    @property
    def rust_name(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.name


@dataclass(frozen=True, slots=True)
class TypeParameterIR:
    name: str
    bounds: tuple[str, ...]
    span: SourceSpan
    is_lifetime: bool = False
    binding: BindingIR | None = None

    @property
    def rust_name(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.name


@dataclass(frozen=True, slots=True)
class IntLiteralIR:
    value: int
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class FloatLiteralIR:
    value: float
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class BoolLiteralIR:
    value: bool
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class StringLiteralIR:
    value: str
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TupleLiteralIR:
    values: tuple["ExpressionIR", ...]
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ArrayLiteralIR:
    values: tuple["ExpressionIR", ...]
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class IndexIR:
    receiver: "ExpressionIR"
    index: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class NoneLiteralIR:
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class NameIR:
    name: str
    type_ref: TypeRef
    span: SourceSpan
    binding: BindingIR | None = None

    @property
    def rust_name(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.name


@dataclass(frozen=True, slots=True)
class UnaryIR:
    operator: Literal["positive", "negative", "not"]
    operand: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class BinaryIR:
    operator: Literal[
        "add",
        "subtract",
        "multiply",
        "divide",
        "remainder",
        "and",
        "or",
    ]
    left: "ExpressionIR"
    right: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan
    target_symbol: str | None = None


@dataclass(frozen=True, slots=True)
class CompareIR:
    operator: Literal["eq", "not_eq", "lt", "lt_eq", "gt", "gt_eq"]
    left: "ExpressionIR"
    right: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CallIR:
    target: str
    arguments: tuple["ExpressionIR", ...]
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CrateCallIR:
    path: tuple[str, ...]
    arguments: tuple["ExpressionIR", ...]
    type_ref: TypeRef
    span: SourceSpan
    declared_effects: tuple[Effect, ...] | None = None
    adapter_name: str | None = None


@dataclass(frozen=True, slots=True)
class BorrowIR:
    kind: Literal["shared", "mutable"]
    value: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ConstructorIR:
    constructor: Literal[
        "String",
        "Vec",
        "HashMap",
        "HashSet",
        "BTreeMap",
        "BTreeSet",
        "PathBuf",
        "CheckedCast",
        "Box",
        "Rc",
        "RefCell",
        "Arc",
        "Mutex",
        "Channel",
        "Spawn",
        "BlockOn",
        "Join",
        "Select",
        "YieldNow",
        "SleepMillis",
        "DynBox",
        "ArrayRepeat",
        "Some",
        "None",
        "Ok",
        "Err",
        "UnsafeRead",
        "UnsafeWrite",
        "CAbs",
        "UnsafeStaticIncrement",
        "TypeAliasIdentity",
        "BoxedClosureCall",
        "ClosureVectorTotal",
        "TcpListener",
        "TcpStream",
        "ThreadPool",
        "FileOpen",
    ]
    arguments: tuple["ExpressionIR", ...]
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class StructConstructorIR:
    struct_symbol: str
    arguments: tuple[tuple[str, "ExpressionIR"], ...]
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class FieldAccessIR:
    receiver: "ExpressionIR"
    field: str
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class EnumConstructorIR:
    enum_symbol: str
    variant: str
    arguments: tuple[tuple[str, "ExpressionIR"], ...]
    tuple_style: bool
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class MethodCallIR:
    receiver: "ExpressionIR"
    method: str
    arguments: tuple["ExpressionIR", ...]
    type_ref: TypeRef
    span: SourceSpan
    target_symbol: str | None = None
    dispatch_targets: tuple[str, ...] = ()
    required_receiver: Literal["shared", "mutable", "owned", "interior"] = "shared"


@dataclass(frozen=True, slots=True)
class TraitCallIR:
    trait_symbol: str
    concrete_type: TypeRef
    method: str
    receiver: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan
    target_symbol: str | None = None
    arguments: tuple["ExpressionIR", ...] = ()
    required_receiver: Literal["shared", "mutable", "owned"] = "shared"


@dataclass(frozen=True, slots=True)
class FunctionPointerTwiceIR:
    target: str
    argument: "ExpressionIR"
    parameter_type: TypeRef
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class NativePrintlnIR:
    value: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class PythonPrintIR:
    value: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TryIR:
    value: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class AwaitIR:
    """Await one native Rust future and expose its output type."""

    value: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class PanicIR:
    message: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ClosureIR:
    parameter: str | None
    parameter_type: TypeRef
    body: "ExpressionIR"
    borrowed_parameter: bool
    type_ref: TypeRef
    span: SourceSpan
    parameter_binding: BindingIR | None = None
    parameter_projection: Literal["direct", "deref", "borrow"] = "direct"
    second_parameter: str | None = None
    second_parameter_type: TypeRef | None = None
    second_parameter_binding: BindingIR | None = None
    prefix: tuple["ExpressionIR", ...] = ()
    capture_mode: Literal["borrow", "move"] = "borrow"
    call_trait: Literal["inferred", "Fn", "FnMut", "FnOnce"] = "inferred"

    @property
    def rust_parameter(self) -> str | None:
        if self.parameter_binding is not None:
            return self.parameter_binding.rust_name
        return self.parameter

    @property
    def rust_second_parameter(self) -> str | None:
        if self.second_parameter_binding is not None:
            return self.second_parameter_binding.rust_name
        return self.second_parameter


ExpressionIR: TypeAlias = (
    IntLiteralIR
    | FloatLiteralIR
    | BoolLiteralIR
    | StringLiteralIR
    | TupleLiteralIR
    | ArrayLiteralIR
    | IndexIR
    | NoneLiteralIR
    | NameIR
    | UnaryIR
    | BinaryIR
    | CompareIR
    | CallIR
    | CrateCallIR
    | BorrowIR
    | ConstructorIR
    | StructConstructorIR
    | FieldAccessIR
    | EnumConstructorIR
    | MethodCallIR
    | TraitCallIR
    | FunctionPointerTwiceIR
    | NativePrintlnIR
    | PythonPrintIR
    | TryIR
    | AwaitIR
    | PanicIR
    | ClosureIR
)


@dataclass(frozen=True, slots=True)
class ReturnIR:
    value: ExpressionIR | None
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class LetIR:
    name: str
    value: ExpressionIR
    type_ref: TypeRef
    rust_annotation: TypeRef | None
    mutable: bool
    span: SourceSpan
    binding: BindingIR | None = None

    @property
    def rust_name(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.name


@dataclass(frozen=True, slots=True)
class AssignIR:
    name: str
    value: ExpressionIR
    span: SourceSpan
    binding: BindingIR | None = None

    @property
    def rust_name(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.name


@dataclass(frozen=True, slots=True)
class FieldAssignIR:
    receiver: ExpressionIR
    field: str
    value: ExpressionIR
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class DestructureIR:
    names: tuple[str, ...]
    value: ExpressionIR
    type_ref: TypeRef
    mutable: tuple[bool, ...]
    span: SourceSpan
    bindings: tuple[BindingIR, ...] = ()

    @property
    def rust_names(self) -> tuple[str, ...]:
        if self.bindings:
            return tuple(binding.rust_name for binding in self.bindings)
        return self.names


@dataclass(frozen=True, slots=True)
class LocalConstIR:
    name: str
    value: ExpressionIR
    type_ref: TypeRef
    span: SourceSpan
    binding: BindingIR | None = None

    @property
    def rust_name(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.name


@dataclass(frozen=True, slots=True)
class ExpressionStatementIR:
    value: ExpressionIR
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class IfIR:
    condition: ExpressionIR
    body: tuple["StatementIR", ...]
    otherwise: tuple["StatementIR", ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class WhileIR:
    condition: ExpressionIR
    body: tuple["StatementIR", ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ForRangeIR:
    variable: str
    start: ExpressionIR
    stop: ExpressionIR
    body: tuple["StatementIR", ...]
    span: SourceSpan
    binding: BindingIR | None = None

    @property
    def rust_variable(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.variable


@dataclass(frozen=True, slots=True)
class ForEachIR:
    variable: str
    iterator: ExpressionIR
    item_type: TypeRef
    item_mode: _types.IteratorItemMode
    body: tuple["StatementIR", ...]
    span: SourceSpan
    bindings: tuple[BindingIR, ...] = ()

    @property
    def rust_variable(self) -> str:
        if not self.bindings:
            return self.variable
        if len(self.bindings) == 1:
            return self.bindings[0].rust_name
        return f"({', '.join(binding.rust_name for binding in self.bindings)})"


@dataclass(frozen=True, slots=True)
class BreakIR:
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ContinueIR:
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class PassIR:
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class MatchArmIR:
    variant: str | None
    enum_symbol: str
    bindings: tuple[tuple[str, str], ...]
    tuple_style: bool
    body: tuple["StatementIR", ...]
    span: SourceSpan
    local_bindings: tuple[BindingIR | None, ...] = ()


@dataclass(frozen=True, slots=True)
class MatchIR:
    subject: ExpressionIR
    enum_symbol: str
    subject_borrowed: bool
    arms: tuple[MatchArmIR, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class PatternWildcardIR:
    """A wildcard pattern which introduces no binding."""


@dataclass(frozen=True, slots=True)
class PatternCaptureIR:
    """One source capture with a compiler-assigned emitted identity."""

    name: str
    type_ref: TypeRef
    binding: BindingIR | None = None

    @property
    def rust_name(self) -> str:
        return self.binding.rust_name if self.binding is not None else self.name


@dataclass(frozen=True, slots=True)
class PatternLiteralIR:
    value: bool | int | str
    type_ref: TypeRef


@dataclass(frozen=True, slots=True)
class PatternRestIR:
    """An unnamed tuple rest pattern (`..`)."""


@dataclass(frozen=True, slots=True)
class PatternTupleIR:
    items: tuple["PatternIR", ...]


@dataclass(frozen=True, slots=True)
class PatternFieldIR:
    rust_name: str
    pattern: "PatternIR"


@dataclass(frozen=True, slots=True)
class PatternConstructorIR:
    rust_path: str
    style: Literal["unit", "tuple", "record"]
    items: tuple["PatternIR", ...] = ()
    fields: tuple[PatternFieldIR, ...] = ()
    record_rest: bool = False


@dataclass(frozen=True, slots=True)
class PatternOrIR:
    alternatives: tuple["PatternIR", ...]


@dataclass(frozen=True, slots=True)
class PatternRangeIR:
    low: "PatternIR"
    high: "PatternIR"


@dataclass(frozen=True, slots=True)
class PatternAtIR:
    capture: PatternCaptureIR
    pattern: "PatternIR"


PatternIR: TypeAlias = (
    PatternWildcardIR
    | PatternCaptureIR
    | PatternLiteralIR
    | PatternRestIR
    | PatternTupleIR
    | PatternConstructorIR
    | PatternOrIR
    | PatternRangeIR
    | PatternAtIR
)


@dataclass(frozen=True, slots=True)
class PatternMatchArmIR:
    pattern: PatternIR
    bindings: tuple[tuple[str, TypeRef], ...]
    guard: ExpressionIR | None
    body: tuple["StatementIR", ...]
    span: SourceSpan
    local_bindings: tuple[BindingIR, ...] = ()


@dataclass(frozen=True, slots=True)
class PatternMatchIR:
    subject: ExpressionIR
    subject_type: TypeRef
    subject_borrowed: bool
    arms: tuple[PatternMatchArmIR, ...]
    span: SourceSpan


StatementIR: TypeAlias = (
    ReturnIR
    | LetIR
    | AssignIR
    | FieldAssignIR
    | DestructureIR
    | LocalConstIR
    | ExpressionStatementIR
    | IfIR
    | WhileIR
    | ForRangeIR
    | ForEachIR
    | BreakIR
    | ContinueIR
    | PassIR
    | MatchIR
    | PatternMatchIR
)


@dataclass(frozen=True, slots=True)
class FunctionIR:
    name: str
    parameters: tuple[ParameterIR, ...]
    return_type: TypeRef
    body: tuple[StatementIR, ...]
    span: SourceSpan
    python_boundary: bool = False
    effects: tuple[Effect, ...] = (Effect.NATIVE_RUST,)
    module_name: str = ""
    symbol: str = ""
    type_parameters: tuple[TypeParameterIR, ...] = ()
    exported: bool = True
    is_async: bool = False
    method_name: str | None = None
    method_for: TypeRef | None = None
    trait_symbol: str | None = None
    operator_kind: str | None = None
    symbol_id: SymbolId | None = None

    @property
    def rust_symbol(self) -> str:
        return self.symbol or self.name

    @property
    def qualified_name(self) -> str:
        return f"{self.module_name}.{self.name}" if self.module_name else self.name


@dataclass(frozen=True, slots=True)
class PackageIR:
    schema_version: int
    module_name: str
    source_path: str
    source_hash: str
    wheel_source_integrity_hash: str
    functions: tuple[FunctionIR, ...]
    crates: tuple[CrateIR, ...] = ()
    source_paths: tuple[str, ...] = ()
    structs: tuple[StructIR, ...] = ()
    enums: tuple[EnumIR, ...] = ()
    traits: tuple[TraitIR, ...] = ()

    @property
    def compiler_input_hash(self) -> str:
        """Identity of only the source closure that affects generated Rust."""

        return self.source_hash

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["compiler_input_hash"] = self.compiler_input_hash
        return value
