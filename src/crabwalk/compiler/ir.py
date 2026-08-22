"""Source-spanned semantic IR shared by all Crabwalk frontends."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Literal, TypeAlias

from crabwalk.diagnostics import SourceSpan


class Effect(StrEnum):
    """Semantic effects that constrain native execution and ABI policy."""

    NATIVE_RUST = "NativeRust"
    CONVERSION_BOUNDARY = "ConversionBoundary"
    PYTHON_RUNTIME = "PythonRuntime"
    BLOCKING = "Blocking"
    THREAD_SPAWN = "ThreadSpawn"
    GLOBAL_MUTATION = "GlobalMutation"
    UNSAFE_MEMORY = "UnsafeMemory"
    UNSAFE_FFI = "UnsafeFfi"
    MAY_PANIC = "MayPanic"


@dataclass(frozen=True, slots=True)
class TypeRef:
    rust_name: str
    arguments: tuple["TypeRef", ...] = ()
    python_name: str | None = None
    const_value: int | None = None
    is_generic: bool = False
    is_lifetime: bool = False

    def render(self) -> str:
        if self.rust_name == "Owned":
            return self.arguments[0].render()
        if self.rust_name == "Ref":
            return f"&{self.arguments[0].render()}"
        if self.rust_name == "Mut":
            return f"&mut {self.arguments[0].render()}"
        if self.rust_name == "LifetimeRef":
            target = self.arguments[0]
            rendered = "str" if target.rust_name == "Str" else target.render()
            return f"&'{self.lifetime} {rendered}"
        if self.rust_name == "Str":
            return "&str"
        if self.rust_name == "Unit":
            return "()"
        if self.rust_name == "Tuple":
            values = ", ".join(value.render() for value in self.arguments)
            return f"({values}{',' if len(self.arguments) == 1 else ''})"
        if self.rust_name == "Array":
            return f"[{self.arguments[0].render()}; {self.const_value}]"
        if self.rust_name == "HashMap":
            values = ", ".join(value.render() for value in self.arguments)
            return f"std::collections::HashMap<{values}>"
        if self.rust_name == "Dyn":
            if self.python_name is None:
                raise ValueError("Dyn TypeRef is missing its trait symbol")
            return f"dyn {self.python_name}"
        concrete_paths = {
            "TcpListener": "std::net::TcpListener",
            "TcpStream": "std::net::TcpStream",
            "ThreadPool": "__CwThreadPool",
        }
        if self.rust_name in concrete_paths:
            return concrete_paths[self.rust_name]
        standard_paths = {
            "Arc": "std::sync::Arc",
            "Mutex": "std::sync::Mutex",
            "Rc": "std::rc::Rc",
            "RefCell": "std::cell::RefCell",
            "Receiver": "std::sync::mpsc::Receiver",
            "Sender": "std::sync::mpsc::Sender",
            "ThreadHandle": "std::thread::JoinHandle",
        }
        if self.rust_name in standard_paths:
            values = ", ".join(value.render() for value in self.arguments)
            return f"{standard_paths[self.rust_name]}<{values}>"
        if not self.arguments:
            return self.rust_name
        values = ", ".join(value.render() for value in self.arguments)
        return f"{self.rust_name}<{values}>"

    def display(self) -> str:
        if self.rust_name == "LifetimeRef":
            return f"rust.Borrow[{self.lifetime}, {self.arguments[0].display()}]"
        if self.is_generic:
            return f"'{self.rust_name}" if self.is_lifetime else self.rust_name
        if self.python_name is not None:
            return self.python_name
        if self.rust_name == "Unit":
            return "None"
        if self.rust_name == "Tuple":
            values = ", ".join(value.display() for value in self.arguments)
            return f"rust.Tuple[{values}]"
        if self.rust_name == "Array":
            return f"rust.Array[{self.arguments[0].display()}, {self.const_value}]"
        if not self.arguments:
            return f"rust.{self.rust_name}"
        values = ", ".join(value.display() for value in self.arguments)
        return f"rust.{self.rust_name}[{values}]"

    @property
    def ownership(self) -> str | None:
        return self.rust_name if self.rust_name in {"Owned", "Ref", "Mut"} else None

    @property
    def underlying(self) -> "TypeRef":
        return (
            self.arguments[0]
            if self.ownership is not None or self.rust_name == "LifetimeRef"
            else self
        )

    @property
    def lifetime(self) -> str | None:
        return self.python_name if self.rust_name == "LifetimeRef" else None

    @property
    def is_integer(self) -> bool:
        return self.rust_name in {
            "i8",
            "i16",
            "i32",
            "i64",
            "i128",
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


I64 = TypeRef("i64")
U64 = TypeRef("u64")
USIZE = TypeRef("usize")
F64 = TypeRef("f64")
BOOL = TypeRef("bool")
CHAR = TypeRef("char")
STRING = TypeRef("String")
STR = TypeRef("Str")
UNIT = TypeRef("Unit")
INFERRED = TypeRef("_")


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


@dataclass(frozen=True, slots=True)
class StructIR:
    name: str
    module_name: str
    symbol: str
    fields: tuple[StructFieldIR, ...]
    derives: tuple[tuple[str, ...], ...]
    span: SourceSpan

    @property
    def qualified_name(self) -> str:
        return f"{self.module_name}.{self.name}" if self.module_name else self.name

    @property
    def type_ref(self) -> TypeRef:
        return TypeRef(self.symbol, python_name=self.qualified_name)


@dataclass(frozen=True, slots=True)
class EnumVariantIR:
    name: str
    fields: tuple[StructFieldIR, ...]
    tuple_style: bool
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class EnumIR:
    name: str
    module_name: str
    symbol: str
    variants: tuple[EnumVariantIR, ...]
    derives: tuple[tuple[str, ...], ...]
    span: SourceSpan

    @property
    def qualified_name(self) -> str:
        return f"{self.module_name}.{self.name}" if self.module_name else self.name

    @property
    def type_ref(self) -> TypeRef:
        return TypeRef(self.symbol, python_name=self.qualified_name)


@dataclass(frozen=True, slots=True)
class TraitMethodIR:
    name: str
    return_type: TypeRef
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TraitIR:
    name: str
    module_name: str
    symbol: str
    methods: tuple[TraitMethodIR, ...]
    span: SourceSpan

    @property
    def qualified_name(self) -> str:
        return f"{self.module_name}.{self.name}" if self.module_name else self.name

    @property
    def type_ref(self) -> TypeRef:
        return TypeRef("Trait", python_name=self.symbol)


@dataclass(frozen=True, slots=True)
class ParameterIR:
    name: str
    type_ref: TypeRef
    span: SourceSpan
    mutable: bool = False


@dataclass(frozen=True, slots=True)
class TypeParameterIR:
    name: str
    bounds: tuple[str, ...]
    span: SourceSpan
    is_lifetime: bool = False


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


@dataclass(frozen=True, slots=True)
class TraitCallIR:
    trait_symbol: str
    concrete_type: TypeRef
    method: str
    receiver: "ExpressionIR"
    type_ref: TypeRef
    span: SourceSpan


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
    mutable: bool
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class AssignIR:
    name: str
    value: ExpressionIR
    span: SourceSpan


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


@dataclass(frozen=True, slots=True)
class LocalConstIR:
    name: str
    value: ExpressionIR
    type_ref: TypeRef
    span: SourceSpan


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


@dataclass(frozen=True, slots=True)
class ForEachIR:
    variable: str
    iterator: ExpressionIR
    item_type: TypeRef
    body: tuple["StatementIR", ...]
    span: SourceSpan


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


@dataclass(frozen=True, slots=True)
class MatchIR:
    subject: ExpressionIR
    enum_symbol: str
    subject_borrowed: bool
    arms: tuple[MatchArmIR, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class PatternMatchArmIR:
    pattern: str
    bindings: tuple[tuple[str, TypeRef], ...]
    guard: ExpressionIR | None
    body: tuple["StatementIR", ...]
    span: SourceSpan


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
    functions: tuple[FunctionIR, ...]
    crates: tuple[CrateIR, ...] = ()
    source_paths: tuple[str, ...] = ()
    structs: tuple[StructIR, ...] = ()
    enums: tuple[EnumIR, ...] = ()
    traits: tuple[TraitIR, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
