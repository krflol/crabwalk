"""Static Python AST discovery, validation, and semantic lowering."""

from __future__ import annotations

import ast
import keyword
import math
import threading
from collections import Counter, OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from crabwalk.diagnostics import (
    CrabwalkCompilationError,
    Diagnostic,
    SourceSpan,
)
from crabwalk.namespaces import (
    ENUM_FIELD_RESERVED_NAMES,
    ENUM_VARIANT_RESERVED_NAMES,
    STRUCT_FIELD_RESERVED_NAMES,
)

from .bindings import (
    assign_enum_identity,
    assign_package_identities,
    assign_struct_identity,
    assign_trait_identity,
)
from .abi import (
    enum_field_type_supported as _enum_field_type_supported,
    owned_vector_element_supported as _owned_vector_element_supported,
    python_mapping_key_supported as _python_mapping_key_supported,
    python_parameter_boundary_supported as _python_parameter_boundary_supported,
    python_return_boundary_supported as _python_return_boundary_supported,
    struct_field_type_supported as _struct_field_type_supported,
)
from .declarations import (
    DeclarationIndex,
    has_rust_async_fn_decorator as _has_rust_async_fn_decorator,
    has_rust_fn_decorator as _has_rust_fn_decorator,
    is_extern_declaration as _is_extern_declaration,
    is_rust_attribute as _is_rust_attribute,
    is_rust_call_named as _is_rust_call_named,
)
from .effects import propagate_effects
from .lowering.common import (
    fail as _fail,
    unsupported as _unsupported,
    validate_source_binding as _validate_source_binding,
    validate_unicode_text as _validate_unicode_text,
)
from .lowering.expressions import (
    binary_operator as _binary_operator_decision,
    integer_fits as _integer_fits,
)
from .lowering.patterns import PatternLoweringMixin
from .lowering.statements import block_returns as _block_returns
from .ir import (
    BOOL,
    CHAR,
    F64,
    I64,
    INFERRED,
    STR,
    STRING,
    UNIT,
    U64,
    USIZE,
    ArrayLiteralIR,
    AssignIR,
    AwaitIR,
    BinaryIR,
    BoolLiteralIR,
    BorrowIR,
    BreakIR,
    CallIR,
    ClosureIR,
    CompareIR,
    ConstructorIR,
    ContinueIR,
    CrateCallIR,
    CrateIR,
    DestructureIR,
    Effect,
    EnumConstructorIR,
    EnumIR,
    EnumVariantIR,
    ExpressionIR,
    ExpressionStatementIR,
    FloatLiteralIR,
    FieldAccessIR,
    FieldAssignIR,
    ForEachIR,
    ForRangeIR,
    FunctionPointerTwiceIR,
    FunctionIR,
    IfIR,
    IndexIR,
    IntLiteralIR,
    LetIR,
    LocalConstIR,
    MethodCallIR,
    NameIR,
    NativePrintlnIR,
    NoneLiteralIR,
    PackageIR,
    PanicIR,
    ParameterIR,
    PassIR,
    PythonPrintIR,
    ReturnIR,
    StatementIR,
    StringLiteralIR,
    StructConstructorIR,
    StructFieldIR,
    StructIR,
    TraitIR,
    TraitCallIR,
    TraitMethodIR,
    TypeParameterIR,
    TypeRef,
    TupleLiteralIR,
    TryIR,
    UnaryIR,
    WhileIR,
)
from .naming import (
    is_crabwalk_lifetime_parameter,
    is_crabwalk_type_parameter,
    is_rust_2024_identifier,
    mangle_dependency,
    mangle_item,
)
from .package_graph import (
    discover_package_source_graph,
    package_python_paths,
    single_file_source_graph,
)
from .ownership import (
    LocalState,
    LocalStorage,
    ReceiverAccess,
    builtin_receiver_access as _builtin_receiver_access,
    local_storage_for_type as _local_storage_for_type,
    place_from_ast as _place_from_ast,
    receiver_access_for_ownership as _receiver_access_for_ownership,
)
from .source import attribute_parts as _attribute_parts
from .source import parse_source
from .signatures import Signature as _Signature
from .types import (
    ExternalType,
    IteratorExecution,
    IteratorIndexing,
    IteratorItemMode,
    IteratorType,
    OwnershipType,
)

_ANALYSIS_CACHE_LIMIT = 64
_analysis_cache: OrderedDict[tuple[str, str, str], PackageIR] = OrderedDict()
_analysis_cache_lock = threading.Lock()

_PRIMITIVES = {
    name: TypeRef(name)
    for name in (
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
        "f32",
        "f64",
        "bool",
        "char",
    )
}
_PRIMITIVES.update({"String": STRING, "Str": STR})
_PRIMITIVES.update(
    {
        "TcpListener": TypeRef("TcpListener"),
        "TcpStream": TypeRef("TcpStream"),
        "ThreadPool": TypeRef("ThreadPool"),
    }
)
_GENERIC_ARITY = {
    "Arc": 1,
    "Buffer": 1,
    "Box": 1,
    "Mutex": 1,
    "Rc": 1,
    "Receiver": 1,
    "RefCell": 1,
    "Sender": 1,
    "ThreadHandle": 1,
    "Vec": 1,
    "HashMap": 2,
    "Option": 1,
    "Result": 2,
    "Owned": 1,
    "Ref": 1,
    "Mut": 1,
    "Closure": 2,
}


def analyze_path(path: str | Path, module_name: str | None = None) -> PackageIR:
    """Analyze one Python module without importing or executing it."""

    parsed = parse_source(path)
    source_path = parsed.path
    tree = parsed.tree

    _validate_rust_import(tree, source_path)
    for node in tree.body:
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and _has_rust_fn_decorator(node)
            and not _has_rust_async_fn_decorator(node)
        ):
            _unsupported(
                node,
                source_path,
                "Use @rust.async_fn on a native Rust async function.",
            )
        if isinstance(node, ast.FunctionDef) and _has_rust_async_fn_decorator(node):
            _unsupported(
                node,
                source_path,
                "@rust.async_fn requires Python's 'async def' syntax.",
            )

    declarations_index = DeclarationIndex.discover(tree)
    declarations = declarations_index.functions
    struct_nodes = declarations_index.structs
    enum_nodes = declarations_index.enums
    identity = module_name or source_path.stem
    traits = _discover_traits(
        tree,
        source_path,
        identity,
        lambda name: mangle_item(identity, name, namespace="type"),
    )
    traits = {name: assign_trait_identity(value) for name, value in traits.items()}
    if not declarations and not struct_nodes and not enum_nodes and not traits:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB101",
                "No Rust functions found",
                "The source file contains no module-level Crabwalk functions or domain types.",
                SourceSpan.from_ast(source_path, tree),
            )
        )

    discovered_crates = _discover_crates(tree, source_path)
    crates = {
        local_name: replace(
            crate,
            binding=mangle_dependency(identity, local_name),
        )
        for local_name, crate in discovered_crates.items()
    }
    external_types = _discover_external_types(tree, source_path, crates)
    type_variables = _discover_type_variables(tree, source_path)
    struct_placeholders = {
        node.name: _struct_placeholder(
            node,
            source_path,
            identity,
            mangle_item(identity, node.name, namespace="type"),
        )
        for node in struct_nodes
    }
    enum_placeholders = {
        node.name: _enum_placeholder(
            node,
            source_path,
            identity,
            mangle_item(identity, node.name, namespace="type"),
        )
        for node in enum_nodes
    }
    domain_types = {name: value.type_ref for name, value in struct_placeholders.items()}
    domain_types.update(
        {name: value.type_ref for name, value in enum_placeholders.items()}
    )
    domain_types.update({name: value.type_ref for name, value in traits.items()})
    domain_types.update(external_types)
    for name, type_ref in type_variables.items():
        if name in domain_types:
            _fail(
                "CRAB180",
                "Generic type name conflicts with a domain type",
                f"'{name}' is declared as both a type variable and a domain type.",
                source_path,
                tree,
            )
        domain_types[name] = type_ref
    structs = {
        node.name: assign_struct_identity(
            _analyze_struct(
                node,
                struct_placeholders[node.name],
                source_path,
                domain_types,
                crates,
            )
        )
        for node in struct_nodes
    }
    enums = {
        node.name: assign_enum_identity(
            _analyze_enum(
                node,
                enum_placeholders[node.name],
                source_path,
                domain_types,
                crates,
            )
        )
        for node in enum_nodes
    }
    signatures = {
        declaration.name: replace(
            _analyze_signature(declaration, source_path, domain_types, crates),
            module_name=identity,
            symbol=mangle_item(identity, declaration.name, namespace="fn"),
        )
        for declaration in declarations
    }
    functions = tuple(
        _FunctionLowerer(
            declaration,
            signatures,
            crates,
            source_path,
            domain_types=domain_types,
            domain_structs=structs,
            domain_enums=enums,
            domain_traits=traits,
        ).lower()
        for declaration in declarations
        if signatures[declaration.name].external_path is None
    )
    if not functions and not structs and not enums and not traits:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB101",
                "No Rust functions found",
                "Typed extern declarations require at least one compiled function or domain type.",
                SourceSpan.from_ast(source_path, tree),
            )
        )
    functions = propagate_effects(functions)
    source_graph = single_file_source_graph(source_path)
    return assign_package_identities(
        PackageIR(
            schema_version=23,
            module_name=identity,
            source_path=str(source_path),
            source_hash=source_graph.compiler_input_hash,
            wheel_source_integrity_hash=source_graph.wheel_source_integrity_hash,
            functions=functions,
            crates=tuple(crates.values()),
            source_paths=(str(source_path),),
            structs=tuple(structs.values()),
            enums=tuple(enums.values()),
            traits=tuple(traits.values()),
        )
    )


@dataclass(slots=True)
class _PackageModule:
    name: str
    path: Path
    source_bytes: bytes
    tree: ast.Module
    declarations: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
    struct_nodes: dict[str, ast.ClassDef]
    enum_nodes: dict[str, ast.ClassDef]
    signatures: dict[str, _Signature]
    structs: dict[str, StructIR]
    enums: dict[str, EnumIR]
    traits: dict[str, TraitIR]
    crates: dict[str, CrateIR]
    external_types: dict[str, ExternalType]
    type_variables: dict[str, TypeRef]
    is_package: bool


@dataclass(frozen=True, slots=True)
class _ModuleRef:
    name: str


_DomainIR = StructIR | EnumIR | TraitIR
_PackageBinding = _Signature | CrateIR | _DomainIR | _ModuleRef


def analyze_project_path(
    path: str | Path,
    module_name: str | None = None,
) -> PackageIR:
    """Analyze a file, or its containing regular Python package, as one crate."""

    source_path = Path(path).resolve()
    package_root = _regular_package_root(source_path)
    if package_root is None:
        if source_path.is_dir():
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB126",
                    "Package path is not a regular Python package",
                    f"{source_path} has no __init__.py.",
                    help="Pass a Python file or a package directory containing __init__.py.",
                )
            )
        source_identity = project_source_identity(source_path)
        cache_key = (
            str(source_path),
            module_name or source_path.stem,
            source_identity,
        )
        cached = _cached_analysis(cache_key)
        if cached is not None:
            return cached
        return _remember_analysis(cache_key, analyze_path(source_path, module_name))

    package_name = _package_name_for_entry(
        package_root,
        source_path,
        module_name,
    )
    source_graph = discover_package_source_graph(
        package_root,
        package_name,
        source_path,
    )
    source_identity = source_graph.compiler_input_hash
    cache_key = (str(package_root), package_name, source_identity)
    cached = _cached_analysis(cache_key)
    if cached is not None:
        return replace(
            cached,
            wheel_source_integrity_hash=(source_graph.wheel_source_integrity_hash),
        )
    return _remember_analysis(
        cache_key,
        _analyze_regular_package(package_root, source_path, module_name),
    )


def _cached_analysis(key: tuple[str, str, str]) -> PackageIR | None:
    with _analysis_cache_lock:
        result = _analysis_cache.get(key)
        if result is not None:
            _analysis_cache.move_to_end(key)
        return result


def _remember_analysis(key: tuple[str, str, str], result: PackageIR) -> PackageIR:
    with _analysis_cache_lock:
        existing = _analysis_cache.setdefault(key, result)
        _analysis_cache.move_to_end(key)
        while len(_analysis_cache) > _ANALYSIS_CACHE_LIMIT:
            _analysis_cache.popitem(last=False)
        return existing


def project_source_identity(path: str | Path) -> str:
    """Hash only sources participating in generated native output."""

    source_path = Path(path).resolve()
    package_root = _regular_package_root(source_path)
    if package_root is None:
        return single_file_source_graph(source_path).compiler_input_hash
    graph = discover_package_source_graph(
        package_root,
        package_root.name,
        source_path,
    )
    return graph.compiler_input_hash


def project_source_anchor(path: str | Path) -> Path:
    """Return the stable file identifying a Crabwalk compilation unit."""

    source_path = Path(path).resolve()
    package_root = _regular_package_root(source_path)
    return package_root / "__init__.py" if package_root is not None else source_path


def _analyze_regular_package(
    package_root: Path,
    entry_path: Path,
    requested_module_name: str | None,
) -> PackageIR:
    package_name = _package_name_for_entry(
        package_root,
        entry_path,
        requested_module_name,
    )
    source_graph = discover_package_source_graph(
        package_root,
        package_name,
        entry_path,
    )
    modules: dict[str, _PackageModule] = {}
    for source_path in source_graph.compiler_paths:
        source_bytes, tree = _read_package_source(source_path)
        name = _package_module_name(package_root, package_name, source_path)
        declarations_index = DeclarationIndex.discover(tree)
        declarations = {node.name: node for node in declarations_index.functions}
        struct_nodes = {node.name: node for node in declarations_index.structs}
        enum_nodes = {node.name: node for node in declarations_index.enums}
        traits = _discover_traits(
            tree,
            source_path,
            name,
            lambda trait_name, module_name=name: _package_rust_symbol(
                module_name, trait_name, namespace="type"
            ),
        )
        invalid_async_declarations = [
            node
            for node in tree.body
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and _has_rust_fn_decorator(node)
                and not _has_rust_async_fn_decorator(node)
            )
            or (
                isinstance(node, ast.FunctionDef) and _has_rust_async_fn_decorator(node)
            )
        ]
        discovered_crates = _discover_crates(tree, source_path)
        type_variables = _discover_type_variables(tree, source_path)
        if (
            declarations
            or struct_nodes
            or enum_nodes
            or traits
            or invalid_async_declarations
            or discovered_crates
        ):
            _validate_rust_import(tree, source_path)
        for node in invalid_async_declarations:
            detail = (
                "Use @rust.async_fn on a native Rust async function."
                if isinstance(node, ast.AsyncFunctionDef)
                else "@rust.async_fn requires Python's 'async def' syntax."
            )
            _unsupported(node, source_path, detail)

        structs = {
            declaration.name: _struct_placeholder(
                declaration,
                source_path,
                name,
                _package_rust_symbol(name, declaration.name, namespace="type"),
            )
            for declaration in struct_nodes.values()
        }
        enums = {
            declaration.name: _enum_placeholder(
                declaration,
                source_path,
                name,
                _package_rust_symbol(name, declaration.name, namespace="type"),
            )
            for declaration in enum_nodes.values()
        }
        crates = {
            local_name: replace(
                crate,
                binding=_package_crate_binding(package_name, name, local_name),
            )
            for local_name, crate in discovered_crates.items()
        }
        external_types = _discover_external_types(tree, source_path, crates)
        modules[name] = _PackageModule(
            name=name,
            path=source_path,
            source_bytes=source_bytes,
            tree=tree,
            declarations=declarations,
            struct_nodes=struct_nodes,
            enum_nodes=enum_nodes,
            signatures={},
            structs=structs,
            enums=enums,
            traits=traits,
            crates=crates,
            external_types=external_types,
            type_variables=type_variables,
            is_package=source_path.name == "__init__.py",
        )

    _validate_package_import_graph(modules)

    domain_cache: dict[str, dict[str, _DomainIR | ExternalType | _ModuleRef]] = {}

    def domain_bindings(
        name: str,
    ) -> dict[str, _DomainIR | ExternalType | _ModuleRef]:
        cached = domain_cache.get(name)
        if cached is not None:
            return cached
        module = modules[name]
        values: dict[str, _DomainIR | ExternalType | _ModuleRef] = {}
        domain_cache[name] = values
        for node in module.tree.body:
            if isinstance(node, ast.ClassDef):
                domain = module.structs.get(node.name) or module.enums.get(node.name)
                if domain is not None:
                    values[node.name] = domain
                else:
                    values.pop(node.name, None)
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                values.pop(node.name, None)
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for target in targets:
                    if isinstance(target, ast.Name):
                        trait = module.traits.get(target.id)
                        external_type = module.external_types.get(target.id)
                        if trait is not None:
                            values[target.id] = trait
                        elif external_type is not None:
                            values[target.id] = external_type
                        else:
                            values.pop(target.id, None)
                continue
            if isinstance(node, ast.ImportFrom):
                source_module = _resolved_import_module(module, node)
                if source_module is None or source_module not in modules:
                    continue
                imported = domain_bindings(source_module)
                for alias in node.names:
                    if alias.name == "*":
                        values.update(imported)
                        continue
                    local_name = alias.asname or alias.name
                    value = imported.get(alias.name)
                    if value is None:
                        child_name = f"{source_module}.{alias.name}"
                        if child_name in modules:
                            value = _ModuleRef(child_name)
                    if value is not None:
                        values[local_name] = value
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in modules:
                        local_name = alias.asname or alias.name.split(".", 1)[0]
                        target_name = alias.name if alias.asname else local_name
                        if target_name in modules:
                            values[local_name] = _ModuleRef(target_name)
        return values

    crate_cache: dict[str, dict[str, CrateIR | _ModuleRef]] = {}

    def crate_bindings(name: str) -> dict[str, CrateIR | _ModuleRef]:
        cached = crate_cache.get(name)
        if cached is not None:
            return cached
        module = modules[name]
        values: dict[str, CrateIR | _ModuleRef] = {}
        crate_cache[name] = values
        for node in module.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                values.pop(node.name, None)
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    crate = module.crates.get(target.id)
                    if crate is not None:
                        values[target.id] = crate
                    else:
                        values.pop(target.id, None)
                continue
            if isinstance(node, ast.ImportFrom):
                source_module = _resolved_import_module(module, node)
                if source_module is None or source_module not in modules:
                    continue
                imported = crate_bindings(source_module)
                for alias in node.names:
                    if alias.name == "*":
                        values.update(imported)
                        continue
                    local_name = alias.asname or alias.name
                    value = imported.get(alias.name)
                    if value is None:
                        child_name = f"{source_module}.{alias.name}"
                        if child_name in modules:
                            value = _ModuleRef(child_name)
                    if value is not None:
                        values[local_name] = value
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in modules:
                        local_name = alias.asname or alias.name.split(".", 1)[0]
                        target_name = alias.name if alias.asname else local_name
                        if target_name in modules:
                            values[local_name] = _ModuleRef(target_name)
        return values

    module_domain_types: dict[str, dict[str, TypeRef]] = {}
    module_domain_structs: dict[str, dict[str, StructIR]] = {}
    module_domain_enums: dict[str, dict[str, EnumIR]] = {}
    module_domain_traits: dict[str, dict[str, TraitIR]] = {}
    for name in sorted(modules):
        module = modules[name]
        visible_domains = domain_bindings(name)
        domain_types: dict[str, TypeRef] = {}
        domain_structs: dict[str, StructIR] = {}
        domain_enums: dict[str, EnumIR] = {}
        domain_traits: dict[str, TraitIR] = {}
        for local_name, value in visible_domains.items():
            if isinstance(value, StructIR):
                domain_types[local_name] = value.type_ref
                domain_structs[local_name] = value
            elif isinstance(value, EnumIR):
                domain_types[local_name] = value.type_ref
                domain_enums[local_name] = value
            elif isinstance(value, TraitIR):
                domain_types[local_name] = value.type_ref
                domain_traits[local_name] = value
            elif isinstance(value, ExternalType):
                domain_types[local_name] = value
            elif isinstance(value, _ModuleRef):
                _collect_domain_members(
                    (local_name,),
                    value.name,
                    domain_bindings,
                    domain_types,
                    domain_structs,
                    domain_enums,
                    domain_traits,
                    set(),
                )
        for local_name, type_ref in module.type_variables.items():
            if local_name in domain_types:
                _fail(
                    "CRAB180",
                    "Generic type name conflicts with a domain type",
                    f"'{local_name}' is declared as both a type variable and a domain type.",
                    module.path,
                    module.tree,
                )
            domain_types[local_name] = type_ref
        visible_crates = {
            local_name: value
            for local_name, value in crate_bindings(name).items()
            if isinstance(value, CrateIR)
        }
        analyzed_structs = {
            local_name: assign_struct_identity(
                _analyze_struct(
                    module.struct_nodes[local_name],
                    placeholder,
                    module.path,
                    domain_types,
                    visible_crates,
                )
            )
            for local_name, placeholder in module.structs.items()
        }
        analyzed_enums = {
            local_name: assign_enum_identity(
                _analyze_enum(
                    module.enum_nodes[local_name],
                    placeholder,
                    module.path,
                    domain_types,
                    visible_crates,
                )
            )
            for local_name, placeholder in module.enums.items()
        }
        module.structs = analyzed_structs
        module.enums = analyzed_enums
        # Replace local placeholders with their field-complete definitions.
        for local_name, struct in analyzed_structs.items():
            domain_structs[local_name] = struct
            domain_types[local_name] = struct.type_ref
        for local_name, enum in analyzed_enums.items():
            domain_enums[local_name] = enum
            domain_types[local_name] = enum.type_ref
        module_domain_types[name] = domain_types
        module_domain_structs[name] = domain_structs
        module_domain_enums[name] = domain_enums
        module_domain_traits[name] = domain_traits
        module.signatures = {
            declaration.name: replace(
                _analyze_signature(
                    declaration,
                    module.path,
                    domain_types,
                    visible_crates,
                ),
                module_name=name,
                symbol=_package_rust_symbol(name, declaration.name),
            )
            for declaration in module.declarations.values()
        }

    for module in modules.values():
        module.traits = {
            local_name: assign_trait_identity(value)
            for local_name, value in module.traits.items()
        }

    final_structs_by_symbol = {
        struct.symbol: struct
        for module in modules.values()
        for struct in module.structs.values()
    }
    final_enums_by_symbol = {
        enum.symbol: enum
        for module in modules.values()
        for enum in module.enums.values()
    }
    final_traits_by_symbol = {
        trait.symbol: trait
        for module in modules.values()
        for trait in module.traits.values()
    }
    for name, visible_structs in module_domain_structs.items():
        module_domain_structs[name] = {
            local_name: final_structs_by_symbol[value.symbol]
            for local_name, value in visible_structs.items()
        }
    for name, visible_enums in module_domain_enums.items():
        module_domain_enums[name] = {
            local_name: final_enums_by_symbol[value.symbol]
            for local_name, value in visible_enums.items()
        }
    for name, visible_traits in module_domain_traits.items():
        module_domain_traits[name] = {
            local_name: final_traits_by_symbol[value.symbol]
            for local_name, value in visible_traits.items()
        }

    binding_cache: dict[str, dict[str, _PackageBinding]] = {}

    def module_bindings(name: str) -> dict[str, _PackageBinding]:
        cached = binding_cache.get(name)
        if cached is not None:
            return cached
        module = modules[name]
        values: dict[str, _PackageBinding] = {}
        # Cache the partial table first so ordinary package re-export cycles can
        # observe declarations executed earlier in __init__.py.
        binding_cache[name] = values
        for node in module.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                signature = module.signatures.get(node.name)
                if signature is not None:
                    values[node.name] = signature
                else:
                    values.pop(node.name, None)
                continue
            if isinstance(node, ast.ClassDef):
                domain = module.structs.get(node.name) or module.enums.get(node.name)
                if domain is not None:
                    values[node.name] = domain
                else:
                    values.pop(node.name, None)
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    crate = module.crates.get(target.id)
                    if crate is not None:
                        values[target.id] = crate
                    else:
                        values.pop(target.id, None)
                continue
            if isinstance(node, ast.ImportFrom):
                source_module = _resolved_import_module(module, node)
                if source_module is None or source_module not in modules:
                    continue
                imported = module_bindings(source_module)
                for alias in node.names:
                    if alias.name == "*":
                        values.update(imported)
                        continue
                    local_name = alias.asname or alias.name
                    value = imported.get(alias.name)
                    if value is None:
                        child_name = f"{source_module}.{alias.name}"
                        if child_name in modules:
                            value = _ModuleRef(child_name)
                    if value is not None:
                        values[local_name] = value
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in modules:
                        continue
                    local_name = alias.asname or alias.name.split(".", 1)[0]
                    target_name = alias.name if alias.asname else local_name
                    if target_name in modules:
                        values[local_name] = _ModuleRef(target_name)
        return values

    functions: list[FunctionIR] = []
    all_crates: dict[str, CrateIR] = {}
    for module_name in sorted(modules):
        module = modules[module_name]
        visible = module_bindings(module_name)
        signatures = {
            name: value
            for name, value in visible.items()
            if isinstance(value, _Signature)
        }
        crates = {
            name: value for name, value in visible.items() if isinstance(value, CrateIR)
        }
        qualified_signatures: dict[tuple[str, ...], _Signature] = {}
        qualified_crates: dict[tuple[str, ...], CrateIR] = {}
        for local_name, value in visible.items():
            if isinstance(value, _ModuleRef):
                _collect_module_members(
                    (local_name,),
                    value.name,
                    module_bindings,
                    qualified_signatures,
                    qualified_crates,
                    set(),
                )
        for declaration in module.declarations.values():
            if module.signatures[declaration.name].external_path is not None:
                continue
            functions.append(
                _FunctionLowerer(
                    declaration,
                    signatures,
                    crates,
                    module.path,
                    qualified_signatures,
                    qualified_crates,
                    module_domain_types[module_name],
                    module_domain_structs[module_name],
                    module_domain_enums[module_name],
                    module_domain_traits[module_name],
                ).lower()
            )
        for crate in module.crates.values():
            existing = all_crates.get(crate.binding)
            if existing is not None and existing != crate:
                _fail(
                    "CRAB137",
                    "Conflicting package crate binding",
                    f"Cargo dependency binding {crate.binding!r} is declared twice.",
                    module.path,
                    module.tree,
                )
            all_crates[crate.binding] = crate

    all_structs = tuple(
        struct for name in sorted(modules) for struct in modules[name].structs.values()
    )
    all_enums = tuple(
        enum for name in sorted(modules) for enum in modules[name].enums.values()
    )
    all_traits = tuple(
        trait for name in sorted(modules) for trait in modules[name].traits.values()
    )
    if not functions and not all_structs and not all_enums and not all_traits:
        root_module = modules[package_name]
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB101",
                "No Rust functions found",
                "The package contains no module-level @rust.fn functions.",
                SourceSpan.from_ast(root_module.path, root_module.tree),
            )
        )

    functions_tuple = propagate_effects(tuple(functions))
    source_paths: list[str] = []
    for name in sorted(modules):
        module = modules[name]
        source_paths.append(str(module.path))
    return assign_package_identities(
        PackageIR(
            schema_version=23,
            module_name=package_name,
            source_path=str(package_root / "__init__.py"),
            source_hash=source_graph.compiler_input_hash,
            wheel_source_integrity_hash=source_graph.wheel_source_integrity_hash,
            functions=functions_tuple,
            crates=tuple(all_crates[name] for name in sorted(all_crates)),
            source_paths=tuple(source_paths),
            structs=all_structs,
            enums=all_enums,
            traits=all_traits,
        )
    )


def _collect_module_members(
    prefix: tuple[str, ...],
    module_name: str,
    module_bindings: Callable[[str], dict[str, _PackageBinding]],
    signatures: dict[tuple[str, ...], _Signature],
    crates: dict[tuple[str, ...], CrateIR],
    seen: set[str],
) -> None:
    if module_name in seen:
        return
    seen.add(module_name)
    bindings = module_bindings(module_name)
    for name, value in bindings.items():
        path = (*prefix, name)
        if isinstance(value, _Signature):
            signatures[path] = value
        elif isinstance(value, CrateIR):
            crates[path] = value
        elif isinstance(value, _ModuleRef):
            _collect_module_members(
                path,
                value.name,
                module_bindings,
                signatures,
                crates,
                seen,
            )


def _collect_domain_members(
    prefix: tuple[str, ...],
    module_name: str,
    domain_bindings: Callable[[str], dict[str, _DomainIR | ExternalType | _ModuleRef]],
    types: dict[str, TypeRef],
    structs: dict[str, StructIR],
    enums: dict[str, EnumIR],
    traits: dict[str, TraitIR],
    seen: set[str],
) -> None:
    if module_name in seen:
        return
    seen.add(module_name)
    for name, value in domain_bindings(module_name).items():
        path = (*prefix, name)
        qualified = ".".join(path)
        if isinstance(value, StructIR):
            types[qualified] = value.type_ref
            structs[qualified] = value
        elif isinstance(value, EnumIR):
            types[qualified] = value.type_ref
            enums[qualified] = value
        elif isinstance(value, TraitIR):
            types[qualified] = value.type_ref
            traits[qualified] = value
        elif isinstance(value, ExternalType):
            types[qualified] = value
        elif isinstance(value, _ModuleRef):
            _collect_domain_members(
                path,
                value.name,
                domain_bindings,
                types,
                structs,
                enums,
                traits,
                seen,
            )


def _regular_package_root(path: Path) -> Path | None:
    directory = path if path.is_dir() else path.parent
    if not (directory / "__init__.py").is_file():
        return None
    while (directory.parent / "__init__.py").is_file():
        directory = directory.parent
    return directory


def _package_python_paths(package_root: Path) -> tuple[Path, ...]:
    return package_python_paths(package_root)


def _package_name_for_entry(
    package_root: Path,
    entry_path: Path,
    requested: str | None,
) -> str:
    default = package_root.name
    if not requested or entry_path.is_dir():
        return requested or default
    relative = entry_path.relative_to(package_root)
    suffix = list(relative.parts)
    if suffix[-1] == "__init__.py":
        suffix = suffix[:-1]
    else:
        suffix[-1] = Path(suffix[-1]).stem
    requested_parts = requested.split(".")
    if suffix and requested_parts[-len(suffix) :] == suffix:
        prefix = requested_parts[: -len(suffix)]
        return ".".join(prefix) if prefix else default
    if not suffix:
        return requested
    return default


def _package_module_name(
    package_root: Path,
    package_name: str,
    source_path: Path,
) -> str:
    relative = source_path.relative_to(package_root)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join((package_name, *parts)) if parts else package_name


def _read_package_source(path: Path) -> tuple[bytes, ast.Module]:
    parsed = parse_source(path)
    return parsed.source_bytes, parsed.tree


def _resolved_import_module(
    module: _PackageModule,
    node: ast.ImportFrom,
) -> str | None:
    if node.level == 0:
        return node.module
    package_parts = (
        module.name.split(".") if module.is_package else module.name.split(".")[:-1]
    )
    remove = node.level - 1
    if remove > len(package_parts):
        return None
    base = package_parts[: len(package_parts) - remove]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _validate_package_import_graph(modules: dict[str, _PackageModule]) -> None:
    """Reject package semantics Crabwalk cannot model exactly during alpha."""

    edges: dict[str, list[tuple[str, ast.AST]]] = {name: [] for name in modules}
    for name, module in modules.items():
        for node in module.tree.body:
            if isinstance(node, ast.ImportFrom):
                source = _resolved_import_module(module, node)
                if any(alias.name == "*" for alias in node.names):
                    _fail(
                        "CRAB205",
                        "Package star import is unsupported",
                        "Import explicit names; Crabwalk does not approximate __all__ or private-name filtering.",
                        module.path,
                        node,
                    )
                if source is None or source not in modules:
                    continue
                targets = _import_initialization_targets(source, name, modules)
                for alias in node.names:
                    child = f"{source}.{alias.name}"
                    if child in modules:
                        targets.update(
                            _import_initialization_targets(child, name, modules)
                        )
                edges[name].extend((target, node) for target in sorted(targets))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in modules:
                        edges[name].extend(
                            (target, node)
                            for target in sorted(
                                _import_initialization_targets(
                                    alias.name,
                                    name,
                                    modules,
                                )
                            )
                        )

    state = {name: 0 for name in modules}
    stack: list[str] = []

    def visit(name: str) -> None:
        state[name] = 1
        stack.append(name)
        for target, node in edges[name]:
            if state[target] == 0:
                visit(target)
                continue
            if state[target] == 1:
                start = stack.index(target)
                cycle = (*stack[start:], target)
                _fail(
                    "CRAB204",
                    "Package import cycle is unsupported",
                    " -> ".join(cycle),
                    modules[name].path,
                    node,
                )
        stack.pop()
        state[name] = 2

    for name in sorted(modules):
        if state[name] == 0:
            visit(name)


def _import_initialization_targets(
    target: str,
    current: str,
    modules: dict[str, _PackageModule],
) -> set[str]:
    """Return target modules whose package initializers Python must execute."""

    current_parts = current.split(".")
    initialized_ancestors = {
        ".".join(current_parts[:length]) for length in range(1, len(current_parts))
    }
    target_parts = target.split(".")
    return {
        prefix
        for length in range(1, len(target_parts) + 1)
        if (prefix := ".".join(target_parts[:length])) in modules
        and prefix != current
        and prefix not in initialized_ancestors
    }


def _package_rust_symbol(
    module_name: str,
    source_name: str,
    *,
    namespace: str = "fn",
) -> str:
    return mangle_item(module_name, source_name, namespace=namespace)


def _package_crate_binding(
    package_name: str,
    module_name: str,
    local_name: str,
) -> str:
    del package_name
    return mangle_dependency(module_name, local_name)


class _FunctionLowerer(PatternLoweringMixin):
    def __init__(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        signatures: dict[str, _Signature],
        crates: dict[str, CrateIR],
        path: Path,
        qualified_signatures: dict[tuple[str, ...], _Signature] | None = None,
        qualified_crates: dict[tuple[str, ...], CrateIR] | None = None,
        domain_types: dict[str, TypeRef] | None = None,
        domain_structs: dict[str, StructIR] | None = None,
        domain_enums: dict[str, EnumIR] | None = None,
        domain_traits: dict[str, TraitIR] | None = None,
    ):
        self.node = node
        self.signatures = signatures
        self.signature = signatures[node.name]
        self.crates = crates
        self.qualified_signatures = qualified_signatures or {}
        self.qualified_crates = qualified_crates or {}
        self.domain_types = domain_types or {}
        self.domain_structs = domain_structs or {}
        self.domain_enums = domain_enums or {}
        self.domain_traits = domain_traits or {}
        self.structs_by_symbol = {
            value.symbol: value for value in self.domain_structs.values()
        }
        self.enums_by_symbol = {
            value.symbol: value for value in self.domain_enums.values()
        }
        self.traits_by_symbol = {
            value.symbol: value for value in self.domain_traits.values()
        }
        visible_signatures = {
            value.rust_symbol: value
            for value in (
                *self.signatures.values(),
                *self.qualified_signatures.values(),
            )
        }
        self.method_signatures = {
            (value.method_for.rust_name, value.method_name): value
            for value in visible_signatures.values()
            if value.method_for is not None
            and value.method_name is not None
            and value.trait_symbol is None
            and value.operator_kind is None
        }
        self.operator_signatures = {
            (value.method_for.rust_name, value.operator_kind): value
            for value in visible_signatures.values()
            if value.method_for is not None and value.operator_kind is not None
        }
        self.trait_impl_signatures = tuple(
            value
            for value in visible_signatures.values()
            if value.method_for is not None and value.trait_symbol is not None
        )
        self.parameter_ownership = {
            value.name: value.type_ref.ownership for value in self.signature.parameters
        }
        self.path = path
        self.write_counts = _assignment_counts(node)
        self.mutated_names = _mutated_receiver_names(node) | _mutably_borrowed_names(
            node, signatures
        )
        self.mutated_names |= _field_assigned_names(node)
        self.mutated_names |= _mutably_called_method_names(
            node,
            tuple(self.method_signatures.values()),
        )
        self.loop_depth = 0
        self.local_states: dict[str, LocalState] = {}

    def lower(self) -> FunctionIR:
        parameters = tuple(
            replace(
                parameter,
                mutable=(
                    self.write_counts[parameter.name] > 0
                    or parameter.name in self.mutated_names
                ),
            )
            for parameter in self.signature.parameters
        )
        environment = {
            parameter.name: parameter.type_ref.underlying for parameter in parameters
        }
        self.local_states = {
            name: LocalState(type_ref, _local_storage_for_type(type_ref))
            for name, type_ref in environment.items()
        }
        body = self._lower_block(self.node.body, environment)
        if self.signature.return_type != UNIT and not _block_returns(body):
            _fail(
                "CRAB109",
                "Missing return",
                (
                    f"'{self.node.name}' does not return "
                    f"{self.signature.return_type.display()} on every reachable path."
                ),
                self.path,
                self.node,
                f"Return {self.signature.return_type.display()} on every path.",
            )
        return FunctionIR(
            name=self.node.name,
            parameters=parameters,
            return_type=self.signature.return_type,
            body=body,
            span=SourceSpan.from_ast(self.path, self.node),
            module_name=self.signature.module_name,
            symbol=self.signature.rust_symbol,
            type_parameters=self.signature.type_parameters,
            exported=self.signature.exported,
            is_async=self.signature.is_async,
            method_name=self.signature.method_name,
            method_for=self.signature.method_for,
            trait_symbol=self.signature.trait_symbol,
            operator_kind=self.signature.operator_kind,
        )

    def _declare_local(self, name: str, type_ref: TypeRef) -> None:
        self.local_states[name] = LocalState(
            type_ref,
            _local_storage_for_type(type_ref),
        )

    def _clone_local_states(self) -> dict[str, LocalState]:
        return {
            name: LocalState(
                value.semantic_type,
                value.storage,
                value.moved_at,
                value.moved_by,
            )
            for name, value in self.local_states.items()
        }

    def _restore_local_states(self, states: dict[str, LocalState]) -> None:
        self.local_states = {
            name: LocalState(
                value.semantic_type,
                value.storage,
                value.moved_at,
                value.moved_by,
            )
            for name, value in states.items()
        }

    def _merge_branch_local_states(
        self,
        base: dict[str, LocalState],
        branches: tuple[dict[str, LocalState], ...],
    ) -> None:
        self._restore_local_states(base)
        for name, state in self.local_states.items():
            moved = next(
                (
                    branch[name].moved_at
                    for branch in branches
                    if name in branch and branch[name].moved_at is not None
                ),
                None,
            )
            state.moved_at = moved
            state.moved_by = next(
                (
                    branch[name].moved_by
                    for branch in branches
                    if name in branch and branch[name].moved_at is not None
                ),
                None,
            )

    def _consume_local(self, node: ast.expr, operation: str) -> None:
        place = _place_from_ast(node)
        if place is None:
            return
        state = self.local_states.get(place.root)
        if state is None:
            return
        if _is_copy_semantic_type(state.semantic_type):
            return
        state.moved_at = SourceSpan.from_ast(self.path, node)
        state.moved_by = operation

    def _reject_moved_local_use(self, node: ast.Name) -> None:
        state = self.local_states.get(node.id)
        if state is None or state.moved_at is None:
            return
        location = (
            f"{state.moved_at.path}:{state.moved_at.line}:{state.moved_at.column}"
        )
        _fail(
            "CRAB227",
            "Use of moved native local",
            (
                f"'{node.id}' was consumed by {state.moved_by or 'an owned operation'} "
                f"at {location} and cannot be used again."
            ),
            self.path,
            node,
            "Create a new binding before the consuming operation or reinitialize it.",
        )

    def _lower_block(
        self,
        nodes: list[ast.stmt],
        environment: dict[str, TypeRef],
    ) -> tuple[StatementIR, ...]:
        return tuple(self._lower_statement(node, environment) for node in nodes)

    def _lower_statement(
        self,
        node: ast.stmt,
        environment: dict[str, TypeRef],
    ) -> StatementIR:
        if isinstance(node, ast.Return):
            if self.signature.return_type == UNIT:
                if node.value is None or (
                    isinstance(node.value, ast.Constant) and node.value.value is None
                ):
                    return ReturnIR(None, SourceSpan.from_ast(self.path, node))
                _fail(
                    "CRAB115",
                    "Rust type mismatch",
                    "A unit-returning function cannot return a value.",
                    self.path,
                    node,
                )
            if node.value is None:
                _fail(
                    "CRAB110",
                    "Return value required",
                    (
                        f"'{self.signature.name}' must return "
                        f"{self.signature.return_type.display()}."
                    ),
                    self.path,
                    node,
                )
            semantic_return_type = self.signature.return_type.underlying
            value = self._lower_expression(
                node.value, environment, semantic_return_type
            )
            _require_type(value.type_ref, semantic_return_type, self.path, node.value)
            return ReturnIR(value, SourceSpan.from_ast(self.path, node))

        if isinstance(node, ast.Assign):
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], (ast.Tuple, ast.List))
                and all(isinstance(value, ast.Name) for value in node.targets[0].elts)
            ):
                target = node.targets[0]
                for target_name in target.elts:
                    assert isinstance(target_name, ast.Name)
                    _validate_source_binding(
                        target_name.id,
                        self.path,
                        target_name,
                        "destructured local",
                    )
                names = tuple(
                    value.id for value in target.elts if isinstance(value, ast.Name)
                )
                if any(name in environment for name in names):
                    _fail(
                        "CRAB116",
                        "Destructured local is already defined",
                        "Tuple destructuring introduces new local names; use rust.shadow for rebinding.",
                        self.path,
                        target,
                    )
                value = self._lower_expression(node.value, environment)
                if value.type_ref.rust_name != "Tuple" or len(
                    value.type_ref.arguments
                ) != len(names):
                    _fail(
                        "CRAB127",
                        "Tuple destructuring shape mismatch",
                        f"Expected a {len(names)}-element Rust tuple.",
                        self.path,
                        node.value,
                    )
                for name, type_ref in zip(names, value.type_ref.arguments):
                    environment[name] = type_ref
                    self._declare_local(name, type_ref)
                return DestructureIR(
                    names,
                    value,
                    value.type_ref,
                    tuple(
                        self.write_counts[name] > 1 or name in self.mutated_names
                        for name in names
                    ),
                    SourceSpan.from_ast(self.path, node),
                )
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Attribute):
                target = node.targets[0]
                receiver = self._lower_expression(target.value, environment)
                receiver_type = receiver.type_ref.underlying
                struct = self.structs_by_symbol.get(receiver_type.rust_name)
                field = (
                    next(
                        (value for value in struct.fields if value.name == target.attr),
                        None,
                    )
                    if struct is not None
                    else None
                )
                if field is None:
                    _fail(
                        "CRAB190",
                        "Unknown Rust field assignment",
                        f"{receiver_type.display()} has no field named {target.attr!r}.",
                        self.path,
                        target,
                    )
                if _place_from_ast(target.value) is not None:
                    self._require_place_access(
                        target.value,
                        "mutable",
                        "field assignment",
                    )
                value = self._lower_expression(node.value, environment, field.type_ref)
                return FieldAssignIR(
                    receiver,
                    field.rust_name,
                    value,
                    SourceSpan.from_ast(self.path, node),
                )
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                _unsupported(
                    node, self.path, "Only a single local-name assignment is supported."
                )
            target = node.targets[0]
            existing = environment.get(target.id)
            if existing is not None and _is_rust_call_named(node.value, "shadow"):
                assert isinstance(node.value, ast.Call)
                if node.value.keywords or len(node.value.args) != 1:
                    _fail(
                        "CRAB114",
                        "Rust shadow argument mismatch",
                        "rust.shadow expects exactly one expression.",
                        self.path,
                        node.value,
                    )
                value = self._lower_expression(
                    node.value.args[0],
                    environment,
                    existing,
                )
                _require_type(value.type_ref, existing, self.path, node.value.args[0])
                environment[target.id] = value.type_ref
                self._declare_local(target.id, value.type_ref)
                return LetIR(
                    target.id,
                    value,
                    value.type_ref,
                    None,
                    False,
                    SourceSpan.from_ast(self.path, node),
                )
            value = self._lower_expression(node.value, environment, existing)
            if existing is not None:
                _require_type(value.type_ref, existing, self.path, node.value)
                state = self.local_states.get(target.id)
                if state is not None and state.storage == LocalStorage.OPAQUE:
                    _fail(
                        "CRAB226",
                        "Anonymous Rust local cannot be reassigned",
                        (
                            f"'{target.id}' has an opaque iterator, future, or closure "
                            "storage type whose concrete Rust identity may change."
                        ),
                        self.path,
                        target,
                        (
                            f"Use {target.id} = rust.shadow(...) to create a fresh "
                            "Rust binding."
                        ),
                    )
                if state is not None:
                    state.moved_at = None
                    state.moved_by = None
                return AssignIR(target.id, value, SourceSpan.from_ast(self.path, node))
            if value.type_ref == INFERRED:
                _fail(
                    "CRAB222",
                    "Opaque crate value has no semantic type",
                    (
                        "An inferred crate result cannot be stored and used across "
                        "expressions."
                    ),
                    self.path,
                    node.value,
                    (
                        "Add a concrete annotation for a primitive result or declare "
                        "the crate type and function with rust.extern_type/rust.extern."
                    ),
                )
            _validate_source_binding(target.id, self.path, target, "local")
            environment[target.id] = value.type_ref
            self._declare_local(target.id, value.type_ref)
            return LetIR(
                target.id,
                value,
                value.type_ref,
                None,
                self.write_counts[target.id] > 1 or target.id in self.mutated_names,
                SourceSpan.from_ast(self.path, node),
            )

        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            _validate_source_binding(
                node.target.id,
                self.path,
                node.target,
                "local",
            )
            if node.value is None:
                _unsupported(
                    node, self.path, "Uninitialized local declarations are deferred."
                )
            target_type = _annotation_type(
                node.annotation,
                self.path,
                node,
                self.domain_types,
            )
            if _is_rust_call_named(node.value, "const"):
                assert isinstance(node.value, ast.Call)
                if node.target.id in environment:
                    _fail(
                        "CRAB116",
                        "Local constant is already defined",
                        f"'{node.target.id}' already has a Rust binding.",
                        self.path,
                        node.target,
                    )
                if node.value.keywords or len(node.value.args) != 1:
                    _fail(
                        "CRAB114",
                        "Rust constant argument mismatch",
                        "rust.const expects exactly one constant expression.",
                        self.path,
                        node.value,
                    )
                value = self._lower_expression(
                    node.value.args[0], environment, target_type
                )
                environment[node.target.id] = target_type
                self._declare_local(node.target.id, target_type)
                return LocalConstIR(
                    node.target.id,
                    value,
                    target_type,
                    SourceSpan.from_ast(self.path, node),
                )
            if node.target.id in environment and _is_rust_call_named(
                node.value, "shadow"
            ):
                assert isinstance(node.value, ast.Call)
                if node.value.keywords or len(node.value.args) != 1:
                    _fail(
                        "CRAB114",
                        "Rust shadow argument mismatch",
                        "rust.shadow expects exactly one expression.",
                        self.path,
                        node.value,
                    )
                value = self._lower_expression(
                    node.value.args[0], environment, target_type
                )
                _require_type(
                    value.type_ref,
                    target_type,
                    self.path,
                    node.value.args[0],
                )
                environment[node.target.id] = target_type
                self._declare_local(node.target.id, target_type)
                return LetIR(
                    node.target.id,
                    value,
                    target_type,
                    target_type,
                    self.write_counts[node.target.id] > 1
                    or node.target.id in self.mutated_names,
                    SourceSpan.from_ast(self.path, node),
                )
            if node.target.id in environment:
                _fail(
                    "CRAB116",
                    "Local is already defined",
                    f"'{node.target.id}' already has a Rust type.",
                    self.path,
                    node.target,
                )
            value = self._lower_expression(node.value, environment, target_type)
            _require_type(value.type_ref, target_type, self.path, node.value)
            environment[node.target.id] = target_type
            self._declare_local(node.target.id, target_type)
            return LetIR(
                node.target.id,
                value,
                target_type,
                target_type,
                self.write_counts[node.target.id] > 1
                or node.target.id in self.mutated_names,
                SourceSpan.from_ast(self.path, node),
            )

        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            target_type = environment.get(node.target.id)
            if target_type is None:
                _fail(
                    "CRAB112",
                    "Unresolved name",
                    f"'{node.target.id}' is not defined.",
                    self.path,
                    node.target,
                )
            self._reject_moved_local_use(node.target)
            right = self._lower_expression(node.value, environment, target_type)
            operator = _binary_operator(node.op, self.path, expression=node)
            if operator in {"and", "or"}:
                _unsupported(node, self.path)
            _require_numeric(target_type, self.path, node)
            value = BinaryIR(
                operator,  # type: ignore[arg-type]
                NameIR(
                    node.target.id,
                    target_type,
                    SourceSpan.from_ast(self.path, node.target),
                ),
                right,
                target_type,
                SourceSpan.from_ast(self.path, node),
            )
            return AssignIR(node.target.id, value, SourceSpan.from_ast(self.path, node))

        if isinstance(node, ast.If):
            condition = self._lower_expression(node.test, environment, BOOL)
            _require_type(condition.type_ref, BOOL, self.path, node.test)
            base_states = self._clone_local_states()
            self._restore_local_states(base_states)
            body = self._lower_block(node.body, dict(environment))
            body_states = self._clone_local_states()
            self._restore_local_states(base_states)
            otherwise = self._lower_block(node.orelse, dict(environment))
            otherwise_states = self._clone_local_states()
            self._merge_branch_local_states(
                base_states,
                (body_states, otherwise_states),
            )
            return IfIR(
                condition,
                body,
                otherwise,
                SourceSpan.from_ast(self.path, node),
            )

        if isinstance(node, ast.While):
            if node.orelse:
                _unsupported(node, self.path, "while/else is deferred.")
            condition = self._lower_expression(node.test, environment, BOOL)
            _require_type(condition.type_ref, BOOL, self.path, node.test)
            base_states = self._clone_local_states()
            self.loop_depth += 1
            try:
                body = self._lower_block(node.body, dict(environment))
            finally:
                self.loop_depth -= 1
            body_states = self._clone_local_states()
            self._merge_branch_local_states(base_states, (base_states, body_states))
            return WhileIR(condition, body, SourceSpan.from_ast(self.path, node))

        if isinstance(node, ast.For):
            if node.orelse:
                _unsupported(node, self.path, "Rust loops do not support for/else.")
            is_range = (
                isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "range"
                and not node.iter.keywords
                and len(node.iter.args) in {1, 2}
            )
            if is_range:
                assert isinstance(node.iter, ast.Call)
                if not isinstance(node.target, ast.Name):
                    _unsupported(
                        node.target,
                        self.path,
                        "range(...) loops require one name target.",
                    )
                if len(node.iter.args) == 1:
                    stop = self._lower_expression(node.iter.args[0], environment)
                    _require_integer(stop.type_ref, self.path, node.iter.args[0])
                    start = IntLiteralIR(
                        0,
                        stop.type_ref,
                        SourceSpan.from_ast(self.path, node.iter),
                    )
                else:
                    stop = self._lower_expression(node.iter.args[1], environment)
                    _require_integer(stop.type_ref, self.path, node.iter.args[1])
                    start = self._lower_expression(
                        node.iter.args[0], environment, stop.type_ref
                    )
                    _require_type(
                        start.type_ref, stop.type_ref, self.path, node.iter.args[0]
                    )
                _validate_source_binding(
                    node.target.id,
                    self.path,
                    node.target,
                    "loop target",
                )
                loop_environment = dict(environment)
                loop_environment[node.target.id] = stop.type_ref
                base_states = self._clone_local_states()
                self._declare_local(node.target.id, stop.type_ref)
                self.loop_depth += 1
                try:
                    body = self._lower_block(node.body, loop_environment)
                finally:
                    self.loop_depth -= 1
                body_states = self._clone_local_states()
                if node.target.id in base_states:
                    body_states[node.target.id] = base_states[node.target.id]
                else:
                    body_states.pop(node.target.id, None)
                self._merge_branch_local_states(
                    base_states,
                    (base_states, body_states),
                )
                return ForRangeIR(
                    node.target.id,
                    start,
                    stop,
                    body,
                    SourceSpan.from_ast(self.path, node),
                )

            iterator = self._lower_expression(node.iter, environment)
            if not isinstance(iterator.type_ref, IteratorType) or (
                iterator.type_ref.execution != IteratorExecution.SEQUENTIAL
            ):
                _unsupported(
                    node.iter,
                    self.path,
                    (
                        "Iterate over range(...) or a supported sequential Rust "
                        "iterator such as text.lines()."
                    ),
                )
            iterator_type = iterator.type_ref
            item_type = iterator_type.exposed_item_type
            self._consume_local(node.iter, "for-loop iteration")
            base_states = self._clone_local_states()
            loop_environment = dict(environment)
            scoped_targets: tuple[str, ...]
            if isinstance(node.target, ast.Name):
                loop_target = node.target.id
                _validate_source_binding(
                    loop_target,
                    self.path,
                    node.target,
                    "loop target",
                )
                loop_environment[loop_target] = item_type
                scoped_targets = (loop_target,)
                self._declare_local(loop_target, item_type)
            elif isinstance(node.target, (ast.Tuple, ast.List)):
                tuple_type = item_type.underlying
                if (
                    tuple_type.rust_name != "Tuple"
                    or len(node.target.elts) != len(tuple_type.arguments)
                    or not all(
                        isinstance(value, ast.Name) for value in node.target.elts
                    )
                ):
                    _unsupported(
                        node.target,
                        self.path,
                        "Tuple iterator items require an equally sized target of names.",
                    )
                target_names = tuple(
                    value.id
                    for value in node.target.elts
                    if isinstance(value, ast.Name)
                )
                for target_name in node.target.elts:
                    assert isinstance(target_name, ast.Name)
                    _validate_source_binding(
                        target_name.id,
                        self.path,
                        target_name,
                        "loop target",
                    )
                if len(set(target_names)) != len(target_names):
                    _fail(
                        "CRAB192",
                        "Duplicate loop pattern binding",
                        "Each tuple loop target must have a unique name.",
                        self.path,
                        node.target,
                    )
                loop_target = f"({', '.join(target_names)})"
                scoped_targets = target_names
                component_types = tuple_type.arguments
                if isinstance(item_type, OwnershipType) and (
                    item_type.ownership_kind in {"Ref", "Mut"}
                ):
                    component_types = tuple(
                        OwnershipType(item_type.ownership_kind, value)
                        for value in component_types
                    )
                loop_environment.update(zip(target_names, component_types))
                for target_name, component_type in zip(
                    target_names,
                    component_types,
                ):
                    self._declare_local(target_name, component_type)
            else:
                _unsupported(
                    node.target,
                    self.path,
                    "Iterator loops support a name or a tuple of names.",
                )
            self.loop_depth += 1
            try:
                body = self._lower_block(node.body, loop_environment)
            finally:
                self.loop_depth -= 1
            body_states = self._clone_local_states()
            for target_name in scoped_targets:
                if target_name in base_states:
                    body_states[target_name] = base_states[target_name]
                else:
                    body_states.pop(target_name, None)
            self._merge_branch_local_states(
                base_states,
                (base_states, body_states),
            )
            return ForEachIR(
                loop_target,
                iterator,
                item_type,
                iterator_type.item_mode,
                body,
                SourceSpan.from_ast(self.path, node),
            )

        if isinstance(node, ast.Break):
            if self.loop_depth == 0:
                _fail(
                    "CRAB117",
                    "break outside supported loop",
                    "break is valid only inside a compiled while or range loop.",
                    self.path,
                    node,
                )
            return BreakIR(SourceSpan.from_ast(self.path, node))

        if isinstance(node, ast.Continue):
            if self.loop_depth == 0:
                _fail(
                    "CRAB118",
                    "continue outside supported loop",
                    "continue is valid only inside a compiled while or range loop.",
                    self.path,
                    node,
                )
            return ContinueIR(SourceSpan.from_ast(self.path, node))

        if isinstance(node, ast.Pass):
            return PassIR(SourceSpan.from_ast(self.path, node))

        if isinstance(node, ast.Expr):
            # Rust expression statements may intentionally discard any value.
            # Keeping the semicolon in code generation gives Crabwalk the same
            # behavior, which is important for APIs such as HashMap.insert().
            value = self._lower_expression(node.value, environment)
            return ExpressionStatementIR(value, SourceSpan.from_ast(self.path, node))

        if isinstance(node, ast.Match):
            return self._lower_match(node, environment)

        _unsupported(node, self.path)

    def _lower_expression(
        self,
        node: ast.expr,
        environment: dict[str, TypeRef],
        expected: TypeRef | None = None,
    ) -> ExpressionIR:
        span = SourceSpan.from_ast(self.path, node)

        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            if expected is not None:
                _require_type(BOOL, expected, self.path, node)
            return BoolLiteralIR(node.value, BOOL, span)

        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            type_ref = expected if expected is not None and expected.is_numeric else I64
            if type_ref.is_float:
                return FloatLiteralIR(float(node.value), type_ref, span)
            if not type_ref.is_integer:
                _require_type(I64, type_ref, self.path, node)
            if not _integer_fits(node.value, type_ref):
                _fail(
                    "CRAB111",
                    f"Integer does not fit {type_ref.display()}",
                    (
                        f"The integer literal {node.value!r} is outside "
                        f"the {type_ref.display()} range."
                    ),
                    self.path,
                    node,
                )
            return IntLiteralIR(node.value, type_ref, span)

        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            type_ref = expected if expected is not None and expected.is_float else F64
            if not type_ref.is_float:
                _require_type(F64, type_ref, self.path, node)
            if not math.isfinite(node.value):
                _fail(
                    "CRAB119",
                    "Non-finite float literal is unsupported",
                    "Use an explicit Rust constant for NaN or infinity.",
                    self.path,
                    node,
                )
            return FloatLiteralIR(node.value, type_ref, span)

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            _validate_unicode_text(node.value, self.path, node)
            if expected == CHAR:
                if len(node.value) != 1:
                    _fail(
                        "CRAB128",
                        "Rust char literal must contain one Unicode scalar",
                        f"Found a Python string containing {len(node.value)} characters.",
                        self.path,
                        node,
                    )
                return StringLiteralIR(node.value, CHAR, span)
            type_ref = expected if expected in {STRING, STR} else STRING
            if expected is not None and expected not in {STRING, STR}:
                _require_type(STRING, expected, self.path, node)
            return StringLiteralIR(node.value, type_ref, span)

        if isinstance(node, ast.Tuple):
            tuple_type = (
                expected
                if expected is not None and expected.rust_name == "Tuple"
                else None
            )
            if tuple_type is not None and len(tuple_type.arguments) != len(node.elts):
                _fail(
                    "CRAB127",
                    "Rust tuple length mismatch",
                    f"Expected {len(tuple_type.arguments)} elements, found {len(node.elts)}.",
                    self.path,
                    node,
                )
            values = tuple(
                self._lower_expression(
                    value,
                    environment,
                    tuple_type.arguments[index] if tuple_type is not None else None,
                )
                for index, value in enumerate(node.elts)
            )
            result_type = tuple_type or TypeRef(
                "Tuple", tuple(value.type_ref for value in values)
            )
            return TupleLiteralIR(values, result_type, span)

        if isinstance(node, ast.List) and expected is not None:
            if expected.rust_name != "Array":
                _require_type(TypeRef("Array"), expected, self.path, node)
            if len(node.elts) != expected.const_value:
                _fail(
                    "CRAB129",
                    "Rust array length mismatch",
                    f"Expected {expected.const_value} elements, found {len(node.elts)}.",
                    self.path,
                    node,
                )
            element_type = expected.arguments[0]
            values = tuple(
                self._lower_expression(value, environment, element_type)
                for value in node.elts
            )
            return ArrayLiteralIR(values, expected, span)

        if isinstance(node, ast.Constant) and node.value is None:
            if expected == UNIT:
                return NoneLiteralIR(UNIT, span)
            if expected is not None and expected.rust_name == "Option":
                return ConstructorIR("None", (), expected, span)
            _fail(
                "CRAB120",
                "None requires an Option or unit context",
                "Use None only where rust.Option[T] or a unit return is expected.",
                self.path,
                node,
            )

        if isinstance(node, ast.Name):
            type_ref = environment.get(node.id)
            if type_ref is None:
                _fail(
                    "CRAB112",
                    "Unresolved name",
                    f"'{node.id}' is not a local, parameter, or supported Rust symbol.",
                    self.path,
                    node,
                )
            self._reject_moved_local_use(node)
            if expected is not None:
                _require_type(type_ref, expected, self.path, node)
            return NameIR(node.id, type_ref, span)

        if isinstance(node, ast.Await):
            value = self._lower_expression(node.value, environment)
            if (
                value.type_ref.rust_name != "Future"
                or len(value.type_ref.arguments) != 1
            ):
                _fail(
                    "CRAB189",
                    "Rust await requires a Future",
                    f"Found {value.type_ref.display()} instead.",
                    self.path,
                    node.value,
                    "Await a call to a @rust.async_fn helper.",
                )
            result_type = value.type_ref.arguments[0]
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            self._consume_local(node.value, "await")
            return AwaitIR(value, result_type, span)

        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            receiver = self._lower_expression(node.value, environment)
            receiver_type = receiver.type_ref
            if receiver_type.rust_name == "Tuple":
                if (
                    not isinstance(node.slice, ast.Constant)
                    or type(node.slice.value) is not int
                ):
                    _fail(
                        "CRAB127",
                        "Rust tuple index must be a literal integer",
                        "Use tuple_value[0], tuple_value[1], and so on.",
                        self.path,
                        node.slice,
                    )
                index_value = int(node.slice.value)
                if not 0 <= index_value < len(receiver_type.arguments):
                    _fail(
                        "CRAB127",
                        "Rust tuple index is out of range",
                        f"The tuple has {len(receiver_type.arguments)} elements.",
                        self.path,
                        node.slice,
                    )
                result_type = receiver_type.arguments[index_value]
                index = IntLiteralIR(
                    index_value,
                    USIZE,
                    SourceSpan.from_ast(self.path, node.slice),
                )
            elif receiver_type.rust_name in {"Array", "Vec", "Buffer"}:
                result_type = receiver_type.arguments[0]
                index = self._lower_expression(node.slice, environment, USIZE)
            else:
                _unsupported(
                    node,
                    self.path,
                    f"{receiver_type.display()} does not support Crabwalk indexing.",
                )
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return IndexIR(receiver, index, result_type, span)

        if isinstance(node, ast.Attribute):
            receiver = self._lower_expression(node.value, environment)
            struct = self.structs_by_symbol.get(receiver.type_ref.underlying.rust_name)
            field = (
                next(
                    (value for value in struct.fields if value.name == node.attr), None
                )
                if struct is not None
                else None
            )
            if field is None:
                _unsupported(
                    node,
                    self.path,
                    f"{receiver.type_ref.display()} has no supported field {node.attr}.",
                )
            if expected is not None:
                _require_type(field.type_ref, expected, self.path, node)
            return FieldAccessIR(receiver, field.rust_name, field.type_ref, span)

        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                operand = self._lower_expression(node.operand, environment, BOOL)
                return UnaryIR("not", operand, BOOL, span)
            operator = (
                "positive"
                if isinstance(node.op, ast.UAdd)
                else "negative"
                if isinstance(node.op, ast.USub)
                else None
            )
            if operator is not None:
                type_ref = expected if expected is not None else I64
                _require_numeric(type_ref, self.path, node)
                if (
                    operator == "negative"
                    and type_ref.is_integer
                    and not type_ref.is_signed_integer
                ):
                    _fail(
                        "CRAB121",
                        "Unsigned value cannot be negated",
                        f"{type_ref.display()} has no negative values.",
                        self.path,
                        node,
                    )
                operand = self._lower_expression(node.operand, environment, type_ref)
                return UnaryIR(operator, operand, type_ref, span)  # type: ignore[arg-type]

        if isinstance(node, ast.BinOp):
            operator = _binary_operator(node.op, self.path, expression=node)
            type_hint = expected or _peek_expression_type(
                node.right, environment, self.signatures
            )
            left = self._lower_expression(node.left, environment, type_hint)
            operator_signature = self.operator_signatures.get(
                (left.type_ref.rust_name, operator)
            )
            if not left.type_ref.is_numeric:
                if operator_signature is None or operator != "add":
                    _require_numeric(left.type_ref, self.path, node.left)
                assert operator_signature.method_for is not None
                right_type = operator_signature.parameters[1].type_ref.underlying
                right = self._lower_expression(
                    node.right,
                    environment,
                    right_type,
                )
                _require_type(
                    right.type_ref,
                    right_type,
                    self.path,
                    node.right,
                )
                result_type = operator_signature.return_type.underlying
                if expected is not None:
                    _require_type(result_type, expected, self.path, node)
                self._require_place_access(node.left, "owned", "add operator")
                self._consume_local(node.left, "add operator")
                if operator_signature.parameters[1].type_ref.ownership == "Owned":
                    self._consume_local(node.right, "add operator")
                return BinaryIR(
                    "add",
                    left,
                    right,
                    result_type,
                    span,
                    operator_signature.rust_symbol,
                )
            right = self._lower_expression(node.right, environment, left.type_ref)
            _require_type(right.type_ref, left.type_ref, self.path, node.right)
            return BinaryIR(
                operator,  # type: ignore[arg-type]
                left,
                right,
                left.type_ref,
                span,
            )

        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [
                self._lower_expression(value, environment, BOOL)
                for value in node.values
            ]
            operator = "and" if isinstance(node.op, ast.And) else "or"
            result = values[0]
            for value in values[1:]:
                result = BinaryIR(operator, result, value, BOOL, span)
            return result

        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == len(node.comparators) == 1
        ):
            hint = _peek_expression_type(
                node.comparators[0], environment, self.signatures
            )
            left = self._lower_expression(node.left, environment, hint)
            right = self._lower_expression(
                node.comparators[0], environment, left.type_ref
            )
            _require_type(right.type_ref, left.type_ref, self.path, node.comparators[0])
            operator_map: dict[type[ast.cmpop], str] = {
                ast.Eq: "eq",
                ast.NotEq: "not_eq",
                ast.Lt: "lt",
                ast.LtE: "lt_eq",
                ast.Gt: "gt",
                ast.GtE: "gt_eq",
            }
            operator = operator_map.get(type(node.ops[0]))
            if operator is None:
                _unsupported(node, self.path)
            return CompareIR(operator, left, right, BOOL, span)  # type: ignore[arg-type]

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            struct = self.domain_structs.get(node.func.id)
            if struct is not None:
                return self._lower_struct_constructor(
                    node,
                    struct,
                    environment,
                    expected,
                )
            if node.func.id == "print":
                if node.keywords or len(node.args) != 1:
                    _fail(
                        "CRAB114",
                        "Python print argument mismatch",
                        "The first Python boundary supports print(value) only.",
                        self.path,
                        node,
                    )
                value = self._lower_expression(node.args[0], environment)
                if value.type_ref.rust_name not in {
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
                    "f32",
                    "f64",
                    "bool",
                    "char",
                    "String",
                    "Str",
                }:
                    _fail(
                        "CRAB201",
                        "Unsupported Python boundary conversion",
                        (
                            f"print does not yet convert "
                            f"{value.type_ref.display()} across the Python boundary."
                        ),
                        self.path,
                        node.args[0],
                    )
                return PythonPrintIR(value, UNIT, span)
            signature = self.signatures.get(node.func.id)
            if signature is None:
                _fail(
                    "CRAB113",
                    "Unsupported call target",
                    f"'{node.func.id}' is not a @rust.fn function in this module.",
                    self.path,
                    node.func,
                )
            return self._lower_function_call(node, signature, environment, expected)

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            path = _attribute_parts(node.func)
            enum = self.domain_enums.get(".".join(path[:-1])) if len(path) > 1 else None
            if enum is not None:
                variant = next(
                    (value for value in enum.variants if value.name == path[-1]),
                    None,
                )
                if variant is not None:
                    return self._lower_enum_constructor(
                        node,
                        enum,
                        variant,
                        environment,
                        expected,
                    )
            struct = self.domain_structs.get(".".join(_attribute_parts(node.func)))
            if struct is not None:
                return self._lower_struct_constructor(
                    node,
                    struct,
                    environment,
                    expected,
                )
            signature = self.qualified_signatures.get(_attribute_parts(node.func))
            if signature is not None:
                return self._lower_function_call(node, signature, environment, expected)

        if isinstance(node, ast.Call) and _is_rust_attribute(node.func):
            return self._lower_rust_call(node, environment, expected)

        if isinstance(node, ast.Call):
            crate_path = _crate_path(
                node.func,
                self.crates,
                self.qualified_crates,
            )
            if crate_path is not None:
                if node.keywords:
                    _unsupported(
                        node,
                        self.path,
                        "Rust crate calls accept positional arguments only.",
                    )
                arguments = tuple(
                    self._lower_expression(
                        argument,
                        environment,
                        STR
                        if isinstance(argument, ast.Constant)
                        and isinstance(argument.value, str)
                        else None,
                    )
                    for argument in node.args
                )
                return CrateCallIR(
                    crate_path,
                    arguments,
                    expected or INFERRED,
                    span,
                )

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and not node.keywords
        ):
            receiver = self._lower_expression(node.func.value, environment)
            return self._lower_method_call(
                node,
                receiver,
                node.func.attr,
                environment,
                expected,
            )

        _unsupported(node, self.path)

    def _lower_function_call(
        self,
        node: ast.Call,
        signature: _Signature,
        environment: dict[str, TypeRef],
        expected: TypeRef | None,
    ) -> CallIR | CrateCallIR:
        if node.keywords or len(node.args) != len(signature.parameters):
            _fail(
                "CRAB114",
                "Rust function argument mismatch",
                (
                    f"'{signature.name}' expects "
                    f"{len(signature.parameters)} positional argument(s)."
                ),
                self.path,
                node,
            )
        substitutions: dict[str, TypeRef] = {}
        lowered_arguments: list[ExpressionIR] = []
        for argument, parameter in zip(node.args, signature.parameters):
            if signature.type_parameters:
                pattern = parameter.type_ref.underlying
                partially_resolved = _substitute_generics(pattern, substitutions)
                value = self._lower_expression(
                    argument,
                    environment,
                    None
                    if _contains_generic_type(partially_resolved)
                    else partially_resolved,
                )
                _unify_generic_type(
                    pattern,
                    value.type_ref,
                    substitutions,
                    self.path,
                    argument,
                )
                resolved_parameter = _substitute_generics(
                    parameter.type_ref, substitutions
                )
                if _contains_generic_type(resolved_parameter):
                    _fail(
                        "CRAB182",
                        "Generic type could not be inferred",
                        f"Infer the generic arguments for '{signature.name}' from concrete values.",
                        self.path,
                        argument,
                    )
                _require_type(
                    value.type_ref,
                    resolved_parameter.underlying,
                    self.path,
                    argument,
                )
                lowered_arguments.append(
                    self._apply_call_ownership(
                        argument,
                        value,
                        resolved_parameter,
                    )
                )
            else:
                parameter_type = parameter.type_ref
                if (
                    signature.external_path is not None
                    and parameter_type.rust_name == "Closure"
                ):
                    closure_input, closure_output = parameter_type.arguments
                    closure = (
                        self._lower_zero_closure(
                            argument,
                            environment,
                            expected_result=closure_output,
                        )
                        if closure_input == UNIT
                        else self._lower_closure(
                            argument,
                            environment,
                            closure_input,
                            borrowed_parameter=False,
                            expected_result=closure_output,
                        )
                    )
                    lowered_arguments.append(closure)
                else:
                    lowered_arguments.append(
                        self._lower_call_argument(
                            argument,
                            environment,
                            parameter_type,
                        )
                    )
        arguments = tuple(lowered_arguments)
        return_type = _substitute_generics(signature.return_type, substitutions)
        if _contains_generic_type(return_type):
            _fail(
                "CRAB182",
                "Generic return type could not be inferred",
                f"'{signature.name}' returns an unresolved generic type.",
                self.path,
                node,
            )
        semantic_return_type = return_type.underlying
        call_type = (
            TypeRef("Future", (semantic_return_type,))
            if signature.is_async
            else semantic_return_type
        )
        if expected is not None:
            _require_type(call_type, expected, self.path, node)
        if signature.external_path is not None:
            return CrateCallIR(
                signature.external_path,
                arguments,
                call_type,
                SourceSpan.from_ast(self.path, node),
                signature.external_effects,
                signature.name,
            )
        return CallIR(
            signature.rust_symbol,
            arguments,
            call_type,
            SourceSpan.from_ast(self.path, node),
        )

    def _lower_struct_constructor(
        self,
        node: ast.Call,
        struct: StructIR,
        environment: dict[str, TypeRef],
        expected: TypeRef | None,
    ) -> StructConstructorIR:
        if node.args and node.keywords:
            _fail(
                "CRAB151",
                "Mixed struct constructor arguments",
                "Use either all positional fields or all named fields.",
                self.path,
                node,
            )
        supplied: list[tuple[str, ast.expr]]
        if node.keywords:
            if any(value.arg is None for value in node.keywords):
                _unsupported(
                    node, self.path, "Struct constructors do not support **kwargs."
                )
            supplied = [(str(value.arg), value.value) for value in node.keywords]
        else:
            supplied = [
                (field.name, value) for field, value in zip(struct.fields, node.args)
            ]
        expected_names = [field.name for field in struct.fields]
        supplied_names = [name for name, _ in supplied]
        if len(supplied) != len(struct.fields) or set(supplied_names) != set(
            expected_names
        ):
            _fail(
                "CRAB152",
                "Struct constructor fields do not match",
                f"{struct.qualified_name} requires fields: {', '.join(expected_names)}.",
                self.path,
                node,
            )
        nodes_by_name = dict(supplied)
        arguments = tuple(
            (
                field.rust_name,
                self._lower_expression(
                    nodes_by_name[field.name],
                    environment,
                    field.type_ref,
                ),
            )
            for field in struct.fields
        )
        result_type = struct.type_ref
        if expected is not None:
            _require_type(result_type, expected, self.path, node)
        return StructConstructorIR(
            struct.symbol, arguments, result_type, SourceSpan.from_ast(self.path, node)
        )

    def _lower_enum_constructor(
        self,
        node: ast.Call,
        enum: EnumIR,
        variant: EnumVariantIR,
        environment: dict[str, TypeRef],
        expected: TypeRef | None,
    ) -> EnumConstructorIR:
        if variant.tuple_style:
            if node.keywords or len(node.args) != len(variant.fields):
                _fail(
                    "CRAB165",
                    "Enum tuple variant arguments do not match",
                    f"{enum.qualified_name}.{variant.name} expects {len(variant.fields)} positional values.",
                    self.path,
                    node,
                )
            supplied = list(zip((field.name for field in variant.fields), node.args))
        else:
            if node.args or any(value.arg is None for value in node.keywords):
                _fail(
                    "CRAB165",
                    "Enum record variant arguments do not match",
                    f"{enum.qualified_name}.{variant.name} accepts named payload fields only.",
                    self.path,
                    node,
                )
            supplied = [(str(value.arg), value.value) for value in node.keywords]
            if {name for name, _ in supplied} != {
                field.name for field in variant.fields
            }:
                _fail(
                    "CRAB165",
                    "Enum record variant fields do not match",
                    f"{variant.name} requires: {', '.join(field.name for field in variant.fields)}.",
                    self.path,
                    node,
                )
        nodes = dict(supplied)
        arguments = tuple(
            (
                field.rust_name,
                self._lower_expression(nodes[field.name], environment, field.type_ref),
            )
            for field in variant.fields
        )
        if expected is not None:
            _require_type(enum.type_ref, expected, self.path, node)
        return EnumConstructorIR(
            enum.symbol,
            variant.rust_name,
            arguments,
            variant.tuple_style,
            enum.type_ref,
            SourceSpan.from_ast(self.path, node),
        )

    def _lower_call_argument(
        self,
        node: ast.expr,
        environment: dict[str, TypeRef],
        parameter_type: TypeRef,
    ) -> ExpressionIR:
        value = self._lower_expression(
            node,
            environment,
            parameter_type.underlying,
        )
        return self._apply_call_ownership(node, value, parameter_type)

    def _apply_call_ownership(
        self,
        node: ast.expr,
        value: ExpressionIR,
        parameter_type: TypeRef,
    ) -> ExpressionIR:
        if parameter_type.rust_name == "Ref":
            return BorrowIR(
                "shared",
                value,
                parameter_type,
                SourceSpan.from_ast(self.path, node),
            )
        if parameter_type.rust_name == "Mut":
            if _place_from_ast(node) is None:
                _fail(
                    "CRAB140",
                    "Mutable borrow requires a Rust place",
                    "Pass a local, field, or indexed Rust place to rust.Mut[T].",
                    self.path,
                    node,
                )
            self._require_place_access(node, "mutable", "mutable argument")
            return BorrowIR(
                "mutable",
                value,
                parameter_type,
                SourceSpan.from_ast(self.path, node),
            )
        if parameter_type.rust_name == "Owned":
            self._require_place_access(node, "owned", "owned argument")
            self._consume_local(node, "owned argument")
        return value

    def _require_place_access(
        self,
        node: ast.expr,
        required: ReceiverAccess,
        operation: str,
    ) -> None:
        """Reject an operation that exceeds the root place's ownership grant."""

        place = _place_from_ast(node)
        if place is None:
            return
        ownership = self.parameter_ownership.get(place.root)
        if ownership is None or required in {"shared", "interior"}:
            return
        if required == "mutable" and ownership in {"Owned", "Mut"}:
            return
        if required == "owned" and ownership == "Owned":
            return
        available = {
            "Ref": "shared",
            "Mut": "mutable",
            "Owned": "owned",
        }.get(ownership, "owned")
        _fail(
            "CRAB208",
            "Receiver ownership is insufficient",
            (
                f"{operation} requires {required} access, but root binding "
                f"'{place.root}' provides {available} access."
            ),
            self.path,
            node,
            (
                f"Use rust.Mut[...] for mutable access to '{place.root}'."
                if required == "mutable"
                else f"Pass '{place.root}' as rust.Owned[...] before consuming it."
            ),
        )

    def _lower_rust_call(
        self,
        node: ast.Call,
        environment: dict[str, TypeRef],
        expected: TypeRef | None,
    ) -> ExpressionIR:
        assert isinstance(node.func, ast.Attribute)
        name = node.func.attr
        span = SourceSpan.from_ast(self.path, node)
        if node.keywords:
            _unsupported(
                node, self.path, "Rust constructors accept positional arguments only."
            )

        if name == "println":
            if len(node.args) != 1:
                _fail(
                    "CRAB114",
                    "Rust function argument mismatch",
                    "rust.println expects one argument.",
                    self.path,
                    node,
                )
            value = self._lower_expression(node.args[0], environment)
            return NativePrintlnIR(value, UNIT, span)

        if name == "panic":
            if len(node.args) != 1:
                _fail(
                    "CRAB114",
                    "Rust panic argument mismatch",
                    "rust.panic expects one string message.",
                    self.path,
                    node,
                )
            message = self._lower_expression(node.args[0], environment, STR)
            return PanicIR(message, expected or UNIT, span)

        if name == "try_":
            if len(node.args) != 1:
                _fail(
                    "CRAB114",
                    "Rust try argument mismatch",
                    "rust.try_ expects one rust.Result expression.",
                    self.path,
                    node,
                )
            value = self._lower_expression(node.args[0], environment)
            if value.type_ref.rust_name != "Result":
                _fail(
                    "CRAB177",
                    "Rust try requires Result",
                    f"Found {value.type_ref.display()}.",
                    self.path,
                    node.args[0],
                )
            result_type = value.type_ref.arguments[0]
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return TryIR(value, result_type, span)

        if name == "block_on":
            if len(node.args) != 1:
                _fail(
                    "CRAB189",
                    "Rust block_on argument mismatch",
                    "rust.block_on expects one Future expression.",
                    self.path,
                    node,
                )
            value = self._lower_expression(node.args[0], environment)
            if (
                value.type_ref.rust_name != "Future"
                or len(value.type_ref.arguments) != 1
            ):
                _fail(
                    "CRAB189",
                    "Rust block_on requires a Future",
                    f"Found {value.type_ref.display()} instead.",
                    self.path,
                    node.args[0],
                    "Pass the result of calling a @rust.async_fn helper.",
                )
            result_type = value.type_ref.arguments[0]
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR("BlockOn", (value,), result_type, span)

        if name == "yield_now":
            if node.args:
                _fail(
                    "CRAB189",
                    "Rust yield_now argument mismatch",
                    "rust.yield_now does not accept arguments.",
                    self.path,
                    node,
                )
            result_type = TypeRef("Future", (UNIT,))
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR("YieldNow", (), result_type, span)

        if name == "sleep_millis":
            if len(node.args) != 1:
                _fail(
                    "CRAB189",
                    "Rust sleep_millis argument mismatch",
                    "rust.sleep_millis expects one u64 millisecond count.",
                    self.path,
                    node,
                )
            duration = self._lower_expression(node.args[0], environment, U64)
            result_type = TypeRef("Future", (UNIT,))
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR("SleepMillis", (duration,), result_type, span)

        if name == "dyn_box":
            if len(node.args) != 2:
                _fail(
                    "CRAB191",
                    "Dynamic trait box argument mismatch",
                    "rust.dyn_box expects a trait name and one concrete value.",
                    self.path,
                    node,
                )
            trait_type = _annotation_type(
                node.args[0],
                self.path,
                node.args[0],
                self.domain_types,
            )
            if trait_type.rust_name != "Trait" or trait_type.python_name is None:
                _fail(
                    "CRAB191",
                    "Dynamic trait box needs a declared trait",
                    "Argument one must name a visible rust.trait declaration.",
                    self.path,
                    node.args[0],
                )
            value = self._lower_expression(node.args[1], environment)
            implemented = any(
                signature.trait_symbol == trait_type.python_name
                and signature.method_for is not None
                and signature.method_for.rust_name == value.type_ref.rust_name
                for signature in self.trait_impl_signatures
            )
            if not implemented:
                _fail(
                    "CRAB191",
                    "Concrete type does not implement dynamic trait",
                    (
                        f"{value.type_ref.display()} has no visible rust.impl for "
                        f"{trait_type.python_name}."
                    ),
                    self.path,
                    node.args[1],
                )
            result_type = TypeRef(
                "Box",
                (TypeRef("Dyn", python_name=trait_type.python_name),),
            )
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR("DynBox", (value,), result_type, span)

        if name == "trait_call":
            if (
                len(node.args) != 3
                or not isinstance(node.args[2], ast.Constant)
                or not isinstance(node.args[2].value, str)
            ):
                _fail(
                    "CRAB194",
                    "Fully qualified trait call is invalid",
                    "Use rust.trait_call(Trait, value, 'method').",
                    self.path,
                    node,
                )
            trait_type = _annotation_type(
                node.args[0], self.path, node.args[0], self.domain_types
            )
            if trait_type.rust_name != "Trait" or trait_type.python_name is None:
                _fail(
                    "CRAB194",
                    "Fully qualified call needs a declared trait",
                    "Argument one must name a visible rust.trait declaration.",
                    self.path,
                    node.args[0],
                )
            trait = self.traits_by_symbol.get(trait_type.python_name)
            method_name = node.args[2].value
            method = (
                next(
                    (value for value in trait.methods if value.name == method_name),
                    None,
                )
                if trait is not None
                else None
            )
            if method is None:
                _fail(
                    "CRAB194",
                    "Unknown fully qualified trait method",
                    f"{method_name!r} is not declared by this trait.",
                    self.path,
                    node.args[2],
                )
            receiver = self._lower_expression(node.args[1], environment)
            implementations = tuple(
                signature.trait_symbol == trait_type.python_name
                and signature.method_for is not None
                and signature.method_for.rust_name == receiver.type_ref.rust_name
                and signature.method_name == method_name
                for signature in self.trait_impl_signatures
            )
            matching_implementations = tuple(
                signature
                for signature, matches in zip(
                    self.trait_impl_signatures, implementations
                )
                if matches
            )
            if not matching_implementations:
                _fail(
                    "CRAB194",
                    "Trait method is not implemented for this type",
                    f"No visible implementation handles {receiver.type_ref.display()}.",
                    self.path,
                    node.args[1],
                )
            if expected is not None:
                _require_type(method.return_type, expected, self.path, node)
            self._require_place_access(
                node.args[1],
                "shared",
                f"trait method '{method_name}'",
            )
            return TraitCallIR(
                trait_type.python_name,
                receiver.type_ref,
                method.rust_name,
                receiver,
                method.return_type,
                span,
                matching_implementations[0].rust_symbol,
            )

        if name == "call_twice":
            if (
                len(node.args) != 2
                or not isinstance(node.args[0], ast.Name)
                or node.args[0].id not in self.signatures
            ):
                _fail(
                    "CRAB195",
                    "Function pointer target is invalid",
                    "Use rust.call_twice(one_argument_rust_function, value).",
                    self.path,
                    node,
                )
            signature = self.signatures[node.args[0].id]
            if (
                len(signature.parameters) != 1
                or signature.parameters[0].type_ref.ownership is not None
                or signature.return_type != signature.parameters[0].type_ref
                or not signature.return_type.is_numeric
            ):
                _fail(
                    "CRAB195",
                    "Function pointer signature is unsupported",
                    "call_twice needs fn(T) -> T for one concrete numeric T.",
                    self.path,
                    node.args[0],
                )
            argument_type = signature.parameters[0].type_ref
            argument = self._lower_expression(node.args[1], environment, argument_type)
            if expected is not None:
                _require_type(signature.return_type, expected, self.path, node)
            return FunctionPointerTwiceIR(
                signature.rust_symbol,
                argument,
                argument_type,
                signature.return_type,
                span,
            )

        if name == "unsafe_read":
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Name):
                _fail(
                    "CRAB196",
                    "Raw pointer read needs a local name",
                    "Use rust.unsafe_read(local_copy_value).",
                    self.path,
                    node,
                )
            value = self._lower_expression(node.args[0], environment)
            if not _is_copy_semantic_type(value.type_ref):
                _fail(
                    "CRAB196",
                    "Raw pointer read needs a Copy value",
                    "This safe teaching intrinsic does not move through raw pointers.",
                    self.path,
                    node.args[0],
                )
            if expected is not None:
                _require_type(value.type_ref, expected, self.path, node)
            return ConstructorIR("UnsafeRead", (value,), value.type_ref, span)

        if name == "unsafe_write":
            if len(node.args) != 2 or not isinstance(node.args[0], ast.Name):
                _fail(
                    "CRAB196",
                    "Raw pointer write needs a local name and value",
                    "Use rust.unsafe_write(local_copy_value, replacement).",
                    self.path,
                    node,
                )
            target_type = environment.get(node.args[0].id)
            if target_type is None or not _is_copy_semantic_type(target_type):
                _fail(
                    "CRAB196",
                    "Raw pointer write target is unsupported",
                    "The target must be a visible local Copy value.",
                    self.path,
                    node.args[0],
                )
            target = self._lower_expression(node.args[0], environment, target_type)
            value = self._lower_expression(node.args[1], environment, target_type)
            if expected not in {None, UNIT}:
                _require_type(UNIT, expected, self.path, node)
            return ConstructorIR("UnsafeWrite", (target, value), UNIT, span)

        if name == "c_abs":
            if len(node.args) != 1:
                _fail(
                    "CRAB196",
                    "C abs needs one i32",
                    "Use rust.c_abs(value).",
                    self.path,
                    node,
                )
            result_type = TypeRef("i32")
            value = self._lower_expression(node.args[0], environment, result_type)
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR("CAbs", (value,), result_type, span)

        if name == "unsafe_static_increment":
            if len(node.args) != 1:
                _fail(
                    "CRAB196",
                    "Mutable static increment needs one u64",
                    "Use rust.unsafe_static_increment(amount).",
                    self.path,
                    node,
                )
            amount = self._lower_expression(node.args[0], environment, U64)
            if expected is not None:
                _require_type(U64, expected, self.path, node)
            return ConstructorIR("UnsafeStaticIncrement", (amount,), U64, span)

        if name == "type_alias_identity":
            if len(node.args) != 1:
                _fail(
                    "CRAB197",
                    "Type alias identity needs one value",
                    "Use rust.type_alias_identity(value).",
                    self.path,
                    node,
                )
            value = self._lower_expression(node.args[0], environment, expected)
            return ConstructorIR("TypeAliasIdentity", (value,), value.type_ref, span)

        if name == "boxed_closure_call":
            if len(node.args) != 2:
                _fail(
                    "CRAB198",
                    "Boxed closure call needs value and addend",
                    "Use rust.boxed_closure_call(value, addend).",
                    self.path,
                    node,
                )
            value = self._lower_expression(node.args[0], environment, U64)
            addend = self._lower_expression(node.args[1], environment, U64)
            if expected is not None:
                _require_type(U64, expected, self.path, node)
            return ConstructorIR("BoxedClosureCall", (value, addend), U64, span)

        if name == "closure_vector_total":
            if len(node.args) != 1:
                _fail(
                    "CRAB198",
                    "Closure vector demo needs one value",
                    "Use rust.closure_vector_total(value).",
                    self.path,
                    node,
                )
            value = self._lower_expression(node.args[0], environment, U64)
            if expected is not None:
                _require_type(U64, expected, self.path, node)
            return ConstructorIR("ClosureVectorTotal", (value,), U64, span)

        if name == "TcpListener":
            if len(node.args) != 1:
                _fail(
                    "CRAB199",
                    "TCP listener needs one address",
                    'Use rust.TcpListener("127.0.0.1:0").',
                    self.path,
                    node,
                )
            address = self._lower_expression(node.args[0], environment, STR)
            result_type = TypeRef("TcpListener")
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR("TcpListener", (address,), result_type, span)

        if name == "TcpStream":
            if len(node.args) != 1:
                _fail(
                    "CRAB199",
                    "TCP stream needs one loopback port",
                    "Use rust.TcpStream(listener.local_port()).",
                    self.path,
                    node,
                )
            port = self._lower_expression(node.args[0], environment, U64)
            result_type = TypeRef("TcpStream")
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR("TcpStream", (port,), result_type, span)

        if name == "ThreadPool":
            if len(node.args) != 1:
                _fail(
                    "CRAB199",
                    "Thread pool needs one size",
                    "Use rust.ThreadPool(4).",
                    self.path,
                    node,
                )
            size = self._lower_expression(node.args[0], environment, USIZE)
            result_type = TypeRef("ThreadPool")
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR("ThreadPool", (size,), result_type, span)

        if name in {"join", "select"}:
            if len(node.args) != 2:
                _fail(
                    "CRAB189",
                    f"Rust {name} argument mismatch",
                    f"rust.{name} expects exactly two Future expressions.",
                    self.path,
                    node,
                )
            left = self._lower_expression(node.args[0], environment)
            right = self._lower_expression(node.args[1], environment)
            if (
                left.type_ref.rust_name != "Future"
                or len(left.type_ref.arguments) != 1
                or right.type_ref.rust_name != "Future"
                or len(right.type_ref.arguments) != 1
            ):
                _fail(
                    "CRAB189",
                    f"Rust {name} requires Futures",
                    "Both arguments must be calls that produce native Rust futures.",
                    self.path,
                    node,
                )
            if name == "join":
                output = TypeRef(
                    "Tuple",
                    (left.type_ref.arguments[0], right.type_ref.arguments[0]),
                )
                constructor = "Join"
            else:
                _require_type(
                    right.type_ref.arguments[0],
                    left.type_ref.arguments[0],
                    self.path,
                    node.args[1],
                )
                output = left.type_ref.arguments[0]
                constructor = "Select"
            result_type = TypeRef("Future", (output,))
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR(constructor, (left, right), result_type, span)  # type: ignore[arg-type]

        if name == "String":
            if len(node.args) != 1:
                _fail(
                    "CRAB114",
                    "Rust constructor argument mismatch",
                    "rust.String expects one string argument.",
                    self.path,
                    node,
                )
            value = self._lower_expression(node.args[0], environment, STR)
            return ConstructorIR("String", (value,), STRING, span)

        if name == "Vec":
            if len(node.args) != 1 or not isinstance(node.args[0], ast.List):
                _fail(
                    "CRAB114",
                    "Rust constructor argument mismatch",
                    "rust.Vec expects one explicit Python list literal in M2.",
                    self.path,
                    node,
                )
            vector_type = (
                expected
                if expected is not None and expected.rust_name == "Vec"
                else None
            )
            if vector_type is None and not node.args[0].elts:
                _fail(
                    "CRAB122",
                    "Empty Vec needs a type context",
                    "Annotate the local as rust.Vec[T].",
                    self.path,
                    node,
                )
            element_type = (
                vector_type.arguments[0]
                if vector_type is not None
                else self._lower_expression(node.args[0].elts[0], environment).type_ref
            )
            values = tuple(
                self._lower_expression(value, environment, element_type)
                for value in node.args[0].elts
            )
            result_type = TypeRef("Vec", (element_type,))
            return ConstructorIR("Vec", values, result_type, span)

        if name == "HashMap":
            if node.args or expected is None or expected.rust_name != "HashMap":
                _fail(
                    "CRAB178",
                    "HashMap constructor needs a type context",
                    "Annotate an empty map as rust.HashMap[K, V] = rust.HashMap().",
                    self.path,
                    node,
                )
            return ConstructorIR("HashMap", (), expected, span)

        if name in {"Arc", "Box", "Mutex", "Rc", "RefCell"}:
            if len(node.args) != 1 or expected is None or expected.rust_name != name:
                _fail(
                    "CRAB186",
                    f"{name} constructor needs a concrete type context",
                    f"Annotate the local as rust.{name}[T] = rust.{name}(value).",
                    self.path,
                    node,
                )
            value = self._lower_expression(
                node.args[0], environment, expected.arguments[0]
            )
            return ConstructorIR(name, (value,), expected, span)

        if name == "channel":
            if len(node.args) != 1:
                _fail(
                    "CRAB187",
                    "Channel needs one Rust message type",
                    "Use rust.channel(rust.u64) in a typed Sender/Receiver tuple context.",
                    self.path,
                    node,
                )
            message_type = _annotation_type(
                node.args[0],
                self.path,
                node.args[0],
                self.domain_types,
            )
            result_type = TypeRef(
                "Tuple",
                (
                    TypeRef("Sender", (message_type,)),
                    TypeRef("Receiver", (message_type,)),
                ),
            )
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR("Channel", (), result_type, span)

        if name == "spawn":
            if len(node.args) != 1:
                _fail(
                    "CRAB188",
                    "Thread spawn needs one closure",
                    "Use rust.spawn(lambda: expression).",
                    self.path,
                    node,
                )
            closure = self._lower_zero_closure(node.args[0], environment)
            result_type = TypeRef("ThreadHandle", (closure.body.type_ref,))
            if expected is not None:
                _require_type(result_type, expected, self.path, node)
            return ConstructorIR("Spawn", (closure,), result_type, span)

        if name == "drop":
            if len(node.args) != 1 or expected not in {None, UNIT}:
                _fail(
                    "CRAB114",
                    "Rust drop argument mismatch",
                    "rust.drop expects one owned Rust value and returns unit.",
                    self.path,
                    node,
                )
            value = self._lower_expression(node.args[0], environment)
            return CrateCallIR(("std", "mem", "drop"), (value,), UNIT, span)

        if name == "repeat":
            if (
                expected is None
                or expected.rust_name != "Array"
                or len(node.args) != 2
                or not isinstance(node.args[1], ast.Constant)
                or type(node.args[1].value) is not int
            ):
                _fail(
                    "CRAB129",
                    "Repeated array needs a fixed array context",
                    "Use rust.repeat(value, length) for a rust.Array[T, length] local.",
                    self.path,
                    node,
                )
            if node.args[1].value != expected.const_value:
                _fail(
                    "CRAB129",
                    "Repeated array length mismatch",
                    f"Expected length {expected.const_value}, found {node.args[1].value}.",
                    self.path,
                    node.args[1],
                )
            value = self._lower_expression(
                node.args[0], environment, expected.arguments[0]
            )
            return ConstructorIR("ArrayRepeat", (value,), expected, span)

        if name == "Some":
            if len(node.args) != 1:
                _fail(
                    "CRAB114",
                    "Rust constructor argument mismatch",
                    "rust.Some expects one argument.",
                    self.path,
                    node,
                )
            option_type = (
                expected
                if expected is not None and expected.rust_name == "Option"
                else None
            )
            value = self._lower_expression(
                node.args[0],
                environment,
                option_type.arguments[0] if option_type is not None else None,
            )
            return ConstructorIR(
                "Some",
                (value,),
                option_type or TypeRef("Option", (value.type_ref,)),
                span,
            )

        if name in {"Ok", "Err"}:
            if expected is None or expected.rust_name != "Result":
                _fail(
                    "CRAB123",
                    "Result constructor needs a type context",
                    f"Use rust.{name} where rust.Result[T, E] is expected.",
                    self.path,
                    node,
                )
            if len(node.args) != 1:
                _fail(
                    "CRAB114",
                    "Rust constructor argument mismatch",
                    f"rust.{name} expects one argument.",
                    self.path,
                    node,
                )
            index = 0 if name == "Ok" else 1
            value = self._lower_expression(
                node.args[0], environment, expected.arguments[index]
            )
            return ConstructorIR(name, (value,), expected, span)  # type: ignore[arg-type]

        _fail(
            "CRAB113",
            "Unsupported Rust call target",
            f"rust.{name} is not supported in this compiler milestone.",
            self.path,
            node.func,
        )

    def _lower_method_call(
        self,
        node: ast.Call,
        receiver: ExpressionIR,
        method: str,
        environment: dict[str, TypeRef],
        expected: TypeRef | None,
    ) -> ExpressionIR:
        span = SourceSpan.from_ast(self.path, node)
        receiver_type = receiver.type_ref
        result: TypeRef
        arguments: tuple[ExpressionIR, ...]

        semantic_receiver = receiver_type.underlying
        inherent = self.method_signatures.get((semantic_receiver.rust_name, method))
        if inherent is not None:
            method_parameters = inherent.parameters[1:]
            if node.keywords or len(node.args) != len(method_parameters):
                _fail(
                    "CRAB190",
                    "Rust method argument mismatch",
                    f"{method} expects {len(method_parameters)} positional argument(s).",
                    self.path,
                    node,
                )
            arguments = tuple(
                self._lower_call_argument(argument, environment, parameter.type_ref)
                for argument, parameter in zip(node.args, method_parameters)
            )
            result = inherent.return_type.underlying
            if expected is not None:
                _require_type(result, expected, self.path, node)
            required = _receiver_access_for_ownership(
                inherent.parameters[0].type_ref.ownership
            )
            assert isinstance(node.func, ast.Attribute)
            self._require_place_access(node.func.value, required, f"method '{method}'")
            if required == "owned":
                self._consume_local(node.func.value, f"method '{method}'")
            return MethodCallIR(
                receiver,
                method,
                arguments,
                result,
                span,
                inherent.rust_symbol,
                (inherent.rust_symbol,),
                required,
            )

        dynamic_type = semantic_receiver
        if dynamic_type.rust_name == "Box" and dynamic_type.arguments:
            dynamic_type = dynamic_type.arguments[0]
        if dynamic_type.rust_name == "Dyn" and dynamic_type.python_name is not None:
            trait = self.traits_by_symbol.get(dynamic_type.python_name)
            trait_method = (
                next((value for value in trait.methods if value.name == method), None)
                if trait is not None
                else None
            )
            if trait_method is None or node.args or node.keywords:
                _fail(
                    "CRAB191",
                    "Unknown dynamic trait method",
                    f"{method} is not an object-safe no-argument method on this trait.",
                    self.path,
                    node,
                )
            result = trait_method.return_type
            if expected is not None:
                _require_type(result, expected, self.path, node)
            dispatch_targets = tuple(
                sorted(
                    signature.rust_symbol
                    for signature in self.trait_impl_signatures
                    if signature.trait_symbol == dynamic_type.python_name
                    and signature.method_name == method
                )
            )
            assert isinstance(node.func, ast.Attribute)
            self._require_place_access(node.func.value, "shared", f"method '{method}'")
            return MethodCallIR(
                receiver,
                method,
                (),
                result,
                span,
                None,
                dispatch_targets,
                "shared",
            )

        receiver_type = semantic_receiver
        if receiver_type.rust_name == "Buffer":
            element_type = receiver_type.arguments[0]
            if method == "len" and not node.args:
                arguments = ()
                result = USIZE
            elif method == "is_empty" and not node.args:
                arguments = ()
                result = BOOL
            elif method == "iter" and not node.args:
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    element_type,
                    IteratorItemMode.OWNED,
                )
            else:
                _unsupported(
                    node,
                    self.path,
                    (
                        f"Buffer.{method} is unsupported; read-only buffers expose "
                        "len(), is_empty(), indexing, and copied iter()."
                    ),
                )
        elif receiver_type.rust_name == "Vec":
            element_type = receiver_type.arguments[0]
            if method == "push" and len(node.args) == 1:
                arguments = (
                    self._lower_expression(node.args[0], environment, element_type),
                )
                result = UNIT
            elif method == "pop" and not node.args:
                arguments = ()
                result = TypeRef("Option", (element_type,))
            elif method == "len" and not node.args:
                arguments = ()
                result = USIZE
            elif method == "is_empty" and not node.args:
                arguments = ()
                result = BOOL
            elif method == "iter" and not node.args:
                if not _is_copy_semantic_type(element_type):
                    _fail(
                        "CRAB184",
                        "Iterator copy requires a Copy element",
                        "Vec.iter() currently exposes copied primitive items to Python lambdas.",
                        self.path,
                        node,
                    )
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    element_type,
                    IteratorItemMode.OWNED,
                )
            elif method == "iter_ref" and not node.args:
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    element_type,
                    IteratorItemMode.SHARED_REF,
                )
            elif method == "split_at_mut_sum" and len(node.args) == 1:
                if (
                    not element_type.is_numeric
                    or not isinstance(node.func, ast.Attribute)
                    or not isinstance(node.func.value, ast.Name)
                ):
                    _fail(
                        "CRAB196",
                        "Unsafe split demo needs a named numeric Vec",
                        "Call values.split_at_mut_sum(midpoint) on a local Vec.",
                        self.path,
                        node,
                    )
                arguments = (self._lower_expression(node.args[0], environment, USIZE),)
                result = element_type
            elif method == "par_iter" and not node.args:
                if not any(crate.package == "rayon" for crate in self.crates.values()):
                    _fail(
                        "CRAB176",
                        "Rayon parallel iterator is not declared",
                        "Vec.par_iter() requires a package-local rayon crate declaration.",
                        self.path,
                        node,
                        'Declare rayon = rust.crate("rayon", version="1") at module scope.',
                    )
                arguments = ()
                result = IteratorType(
                    IteratorExecution.PARALLEL,
                    element_type,
                    IteratorItemMode.SHARED_REF,
                    IteratorIndexing.INDEXED,
                )
            else:
                _unsupported(
                    node, self.path, f"Vec.{method} is not in the M2 capability table."
                )
        elif receiver_type.rust_name == "Arc":
            inner = receiver_type.arguments[0]
            if method == "clone" and not node.args:
                arguments = ()
                result = receiver_type
            elif method == "strong_count" and not node.args:
                arguments = ()
                result = USIZE
            elif (
                inner.rust_name == "Mutex"
                and method == "add_locked"
                and len(node.args) == 1
                and inner.arguments[0].is_numeric
            ):
                arguments = (
                    self._lower_expression(
                        node.args[0], environment, inner.arguments[0]
                    ),
                )
                result = UNIT
            elif (
                inner.rust_name == "Mutex"
                and method == "get_locked"
                and not node.args
                and _is_copy_semantic_type(inner.arguments[0])
            ):
                arguments = ()
                result = inner.arguments[0]
            else:
                _unsupported(
                    node,
                    self.path,
                    f"Arc.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type.rust_name == "Box":
            inner = receiver_type.arguments[0]
            if (
                method == "deref_copy"
                and not node.args
                and _is_copy_semantic_type(inner)
            ):
                arguments = ()
                result = inner
            else:
                _unsupported(
                    node,
                    self.path,
                    f"Box.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type.rust_name == "Rc":
            inner = receiver_type.arguments[0]
            if method == "clone" and not node.args:
                arguments = ()
                result = receiver_type
            elif method == "strong_count" and not node.args:
                arguments = ()
                result = USIZE
            elif (
                method == "deref_copy"
                and not node.args
                and _is_copy_semantic_type(inner)
            ):
                arguments = ()
                result = inner
            else:
                _unsupported(
                    node,
                    self.path,
                    f"Rc.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type.rust_name == "RefCell":
            inner = receiver_type.arguments[0]
            if method == "replace" and len(node.args) == 1:
                arguments = (self._lower_expression(node.args[0], environment, inner),)
                result = inner
            elif (
                method == "borrow_copy"
                and not node.args
                and _is_copy_semantic_type(inner)
            ):
                arguments = ()
                result = inner
            else:
                _unsupported(
                    node,
                    self.path,
                    f"RefCell.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type.rust_name == "Sender":
            message_type = receiver_type.arguments[0]
            if method == "send" and len(node.args) == 1:
                arguments = (
                    self._lower_expression(node.args[0], environment, message_type),
                )
                result = UNIT
            else:
                _unsupported(
                    node,
                    self.path,
                    f"Sender.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type.rust_name == "Receiver":
            if method == "recv" and not node.args:
                arguments = ()
                result = receiver_type.arguments[0]
            elif method == "recv_async" and not node.args:
                arguments = ()
                result = TypeRef("Future", (receiver_type.arguments[0],))
            else:
                _unsupported(
                    node,
                    self.path,
                    f"Receiver.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type.rust_name == "ThreadHandle":
            if method == "join" and not node.args:
                arguments = ()
                result = receiver_type.arguments[0]
            else:
                _unsupported(
                    node,
                    self.path,
                    f"ThreadHandle.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type.rust_name == "TcpListener":
            if method == "local_port" and not node.args:
                arguments = ()
                result = U64
            elif method == "serve_http_once" and len(node.args) == 2:
                arguments = (
                    self._lower_expression(node.args[0], environment, STR),
                    self._lower_expression(node.args[1], environment, STR),
                )
                result = U64
            else:
                _unsupported(
                    node,
                    self.path,
                    f"TcpListener.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type.rust_name == "TcpStream":
            if method == "write_get" and len(node.args) == 1:
                arguments = (self._lower_expression(node.args[0], environment, STR),)
                result = UNIT
            elif method == "shutdown_write" and not node.args:
                arguments = ()
                result = UNIT
            elif method == "read_to_string" and not node.args:
                arguments = ()
                result = STRING
            else:
                _unsupported(
                    node,
                    self.path,
                    f"TcpStream.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type.rust_name == "ThreadPool":
            if method == "execute" and len(node.args) == 1:
                arguments = (self._lower_zero_closure(node.args[0], environment),)
                if arguments[0].body.type_ref != UNIT:
                    _fail(
                        "CRAB199",
                        "Thread pool job must return unit",
                        "The job closure may perform work but must not return a value.",
                        self.path,
                        node.args[0],
                    )
                result = UNIT
            elif method == "finish" and not node.args:
                arguments = ()
                result = TypeRef("Result", (UNIT, STRING))
            else:
                _unsupported(
                    node,
                    self.path,
                    f"ThreadPool.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type.rust_name == "HashMap":
            key_type, value_type = receiver_type.arguments
            if method == "insert" and len(node.args) == 2:
                arguments = (
                    self._lower_expression(node.args[0], environment, key_type),
                    self._lower_expression(node.args[1], environment, value_type),
                )
                result = TypeRef("Option", (value_type,))
            elif method in {"contains_key", "remove"} and len(node.args) == 1:
                arguments = (
                    self._lower_expression(node.args[0], environment, key_type),
                )
                result = (
                    BOOL
                    if method == "contains_key"
                    else TypeRef("Option", (value_type,))
                )
            elif method in {"get_or", "entry_or_insert"} and len(node.args) == 2:
                arguments = (
                    self._lower_expression(node.args[0], environment, key_type),
                    self._lower_expression(node.args[1], environment, value_type),
                )
                result = value_type
            elif method in {"get", "get_mut"} and len(node.args) == 1:
                arguments = (
                    self._lower_expression(node.args[0], environment, key_type),
                )
                result = TypeRef(
                    "Option",
                    (
                        TypeRef(
                            "Mut" if method == "get_mut" else "Ref",
                            (value_type,),
                        ),
                    ),
                )
            elif method == "add" and len(node.args) == 2 and value_type.is_numeric:
                arguments = (
                    self._lower_expression(node.args[0], environment, key_type),
                    self._lower_expression(node.args[1], environment, value_type),
                )
                result = UNIT
            elif method == "len" and not node.args:
                arguments = ()
                result = USIZE
            elif method == "is_empty" and not node.args:
                arguments = ()
                result = BOOL
            elif method in {"iter", "iter_ref"} and not node.args:
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    TypeRef(
                        "Tuple",
                        (
                            TypeRef("Ref", (key_type,)),
                            TypeRef("Ref", (value_type,)),
                        ),
                    ),
                    IteratorItemMode.OWNED,
                )
            elif method == "keys" and not node.args:
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    key_type,
                    IteratorItemMode.SHARED_REF,
                )
            elif method == "values" and not node.args:
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    value_type,
                    IteratorItemMode.SHARED_REF,
                )
            elif method == "into_iter" and not node.args:
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    TypeRef("Tuple", (key_type, value_type)),
                    IteratorItemMode.OWNED,
                )
            else:
                _unsupported(
                    node,
                    self.path,
                    f"HashMap.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type in {STRING, STR}:
            if method == "len" and not node.args:
                arguments = ()
                result = USIZE
            elif method == "is_empty" and not node.args:
                arguments = ()
                result = BOOL
            elif method == "lines" and not node.args:
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    STR,
                    IteratorItemMode.OWNED,
                )
            elif receiver_type == STRING and method == "as_str" and not node.args:
                arguments = ()
                result = STR
            elif method == "to_lowercase" and not node.args:
                arguments = ()
                result = STRING
            elif (
                method in {"contains", "starts_with", "ends_with"}
                and len(node.args) == 1
            ):
                arguments = (self._lower_expression(node.args[0], environment, STR),)
                result = BOOL
            elif (
                receiver_type == STRING and method == "push_str" and len(node.args) == 1
            ):
                arguments = (self._lower_expression(node.args[0], environment, STR),)
                result = UNIT
            elif method == "replace" and len(node.args) == 2:
                arguments = (
                    self._lower_expression(node.args[0], environment, STR),
                    self._lower_expression(node.args[1], environment, STR),
                )
                result = STRING
            elif method == "find" and len(node.args) == 1:
                arguments = (self._lower_expression(node.args[0], environment, STR),)
                result = TypeRef("Option", (USIZE,))
            elif method in {"trim", "trim_start", "trim_end"} and not node.args:
                arguments = ()
                result = STR
            elif method == "split" and len(node.args) == 1:
                arguments = (self._lower_expression(node.args[0], environment, STR),)
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    STR,
                    IteratorItemMode.OWNED,
                )
            elif method == "split_whitespace" and not node.args:
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    STR,
                    IteratorItemMode.OWNED,
                )
            elif method == "split_once" and len(node.args) == 1:
                arguments = (self._lower_expression(node.args[0], environment, STR),)
                result = TypeRef("Option", (TypeRef("Tuple", (STR, STR)),))
            elif method in {"strip_prefix", "strip_suffix"} and len(node.args) == 1:
                arguments = (self._lower_expression(node.args[0], environment, STR),)
                result = TypeRef("Option", (STR,))
            elif method == "chars" and not node.args:
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    CHAR,
                    IteratorItemMode.OWNED,
                )
            elif method == "bytes" and not node.args:
                arguments = ()
                result = IteratorType(
                    IteratorExecution.SEQUENTIAL,
                    TypeRef("u8"),
                    IteratorItemMode.OWNED,
                )
            elif method == "parse" and not node.args:
                if (
                    expected is None
                    or expected.rust_name != "Result"
                    or expected.arguments[1] != STRING
                    or not (
                        expected.arguments[0].is_numeric
                        or expected.arguments[0].rust_name == "bool"
                    )
                ):
                    _fail(
                        "CRAB224",
                        "String.parse needs a typed Result context",
                        "Assign to rust.Result[number, rust.String] so the target type is explicit.",
                        self.path,
                        node,
                    )
                arguments = ()
                result = expected
            elif method == "join" and len(node.args) == 1:
                values = self._lower_expression(node.args[0], environment)
                if values.type_ref.rust_name != "Vec" or values.type_ref.arguments[
                    0
                ].rust_name not in {"String", "Str"}:
                    _fail(
                        "CRAB224",
                        "String.join requires a vector of strings",
                        "Pass rust.Vec[rust.String] or a borrowed string vector.",
                        self.path,
                        node.args[0],
                    )
                arguments = (values,)
                result = STRING
            else:
                _unsupported(
                    node,
                    self.path,
                    f"String.{method} is not in the M2 capability table.",
                )
        elif receiver_type.rust_name == "Option":
            inner = receiver_type.arguments[0]
            if method in {"is_some", "is_none"} and not node.args:
                arguments = ()
                result = BOOL
            elif method == "unwrap" and not node.args:
                arguments = ()
                result = inner
            elif method == "expect" and len(node.args) == 1:
                arguments = (self._lower_expression(node.args[0], environment, STR),)
                result = inner
            elif method == "unwrap_or" and len(node.args) == 1:
                arguments = (self._lower_expression(node.args[0], environment, inner),)
                result = inner
            elif method == "map" and len(node.args) == 1:
                closure = self._lower_closure(
                    node.args[0], environment, inner, borrowed_parameter=False
                )
                arguments = (closure,)
                result = TypeRef("Option", (closure.body.type_ref,))
            elif method == "and_then" and len(node.args) == 1:
                closure = self._lower_closure(
                    node.args[0], environment, inner, borrowed_parameter=False
                )
                if closure.body.type_ref.rust_name != "Option":
                    _fail(
                        "CRAB223",
                        "Option.and_then closure must return Option",
                        "Return rust.Some(value), None, or another Option expression.",
                        self.path,
                        node.args[0],
                    )
                arguments = (closure,)
                result = closure.body.type_ref
            elif method == "or_else" and len(node.args) == 1:
                closure = self._lower_zero_closure(
                    node.args[0], environment, expected_result=receiver_type
                )
                _require_type(
                    closure.body.type_ref, receiver_type, self.path, node.args[0]
                )
                arguments = (closure,)
                result = receiver_type
            elif method == "as_ref" and not node.args:
                arguments = ()
                result = TypeRef("Option", (TypeRef("Ref", (inner,)),))
            elif (
                method in {"copied", "cloned"}
                and not node.args
                and (inner.ownership == "Ref")
            ):
                value_type = inner.underlying
                supported = (
                    _is_copy_semantic_type(value_type)
                    if method == "copied"
                    else _is_clone_semantic_type(value_type)
                )
                if not supported:
                    _fail(
                        "CRAB223",
                        f"Option item cannot be {method}",
                        f"{value_type.display()} does not satisfy this adapter.",
                        self.path,
                        node,
                    )
                arguments = ()
                result = TypeRef("Option", (value_type,))
            else:
                _unsupported(
                    node,
                    self.path,
                    f"Option.{method} is not in the M2 capability table.",
                )
        elif receiver_type.rust_name == "Result":
            success, error_type = receiver_type.arguments
            if method in {"is_ok", "is_err"} and not node.args:
                arguments = ()
                result = BOOL
            elif method == "unwrap" and not node.args:
                arguments = ()
                result = success
            elif method == "expect" and len(node.args) == 1:
                arguments = (self._lower_expression(node.args[0], environment, STR),)
                result = success
            elif method == "unwrap_or" and len(node.args) == 1:
                arguments = (
                    self._lower_expression(node.args[0], environment, success),
                )
                result = success
            elif method == "map" and len(node.args) == 1:
                closure = self._lower_closure(
                    node.args[0], environment, success, borrowed_parameter=False
                )
                arguments = (closure,)
                result = TypeRef("Result", (closure.body.type_ref, error_type))
            elif method == "map_err" and len(node.args) == 1:
                closure = self._lower_closure(
                    node.args[0], environment, error_type, borrowed_parameter=False
                )
                arguments = (closure,)
                result = TypeRef("Result", (success, closure.body.type_ref))
            elif method == "and_then" and len(node.args) == 1:
                closure = self._lower_closure(
                    node.args[0], environment, success, borrowed_parameter=False
                )
                if (
                    closure.body.type_ref.rust_name != "Result"
                    or closure.body.type_ref.arguments[1] != error_type
                ):
                    _fail(
                        "CRAB223",
                        "Result.and_then closure has an incompatible error type",
                        f"Return rust.Result[_, {error_type.display()}].",
                        self.path,
                        node.args[0],
                    )
                arguments = (closure,)
                result = closure.body.type_ref
            elif method == "or_else" and len(node.args) == 1:
                closure = self._lower_closure(
                    node.args[0], environment, error_type, borrowed_parameter=False
                )
                if (
                    closure.body.type_ref.rust_name != "Result"
                    or closure.body.type_ref.arguments[0] != success
                ):
                    _fail(
                        "CRAB223",
                        "Result.or_else closure has an incompatible success type",
                        f"Return rust.Result[{success.display()}, _].",
                        self.path,
                        node.args[0],
                    )
                arguments = (closure,)
                result = closure.body.type_ref
            elif method == "as_ref" and not node.args:
                arguments = ()
                result = TypeRef(
                    "Result",
                    (
                        TypeRef("Ref", (success,)),
                        TypeRef("Ref", (error_type,)),
                    ),
                )
            elif method == "ok" and not node.args:
                arguments = ()
                result = TypeRef("Option", (success,))
            elif method == "err" and not node.args:
                arguments = ()
                result = TypeRef("Option", (error_type,))
            else:
                _unsupported(
                    node,
                    self.path,
                    f"Result.{method} is not in the M2 capability table.",
                )
        elif isinstance(receiver_type, IteratorType):
            item_type = receiver_type.item_type
            if (
                method == "copied"
                and not node.args
                and receiver_type.item_mode != IteratorItemMode.OWNED
            ):
                if not _is_copy_semantic_type(item_type):
                    _fail(
                        "CRAB220",
                        "Iterator item cannot be copied",
                        f"{item_type.display()} does not implement Copy.",
                        self.path,
                        node,
                        "Use cloned() for Clone items or map into a new owned value.",
                    )
                arguments = ()
                result = IteratorType(
                    receiver_type.execution,
                    item_type,
                    IteratorItemMode.OWNED,
                    receiver_type.indexing,
                )
            elif (
                method == "cloned"
                and not node.args
                and receiver_type.item_mode != IteratorItemMode.OWNED
            ):
                if not _is_clone_semantic_type(item_type):
                    _fail(
                        "CRAB220",
                        "Iterator item cannot be cloned",
                        f"{item_type.display()} is not known to implement Clone.",
                        self.path,
                        node,
                    )
                arguments = ()
                result = IteratorType(
                    receiver_type.execution,
                    item_type,
                    IteratorItemMode.OWNED,
                    receiver_type.indexing,
                )
            elif method == "map" and len(node.args) == 1:
                closure = self._lower_closure(
                    node.args[0],
                    environment,
                    receiver_type.exposed_item_type,
                    borrowed_parameter=False,
                )
                arguments = (closure,)
                result = IteratorType(
                    receiver_type.execution,
                    closure.body.type_ref,
                    IteratorItemMode.OWNED,
                    receiver_type.indexing,
                )
            elif method == "filter" and len(node.args) == 1:
                if receiver_type.item_mode == IteratorItemMode.OWNED:
                    copy_item = _is_copy_semantic_type(item_type)
                    closure_item = (
                        item_type if copy_item else TypeRef("Ref", (item_type,))
                    )
                    projection = "deref" if copy_item else "borrow"
                else:
                    closure_item = receiver_type.exposed_item_type
                    projection = "deref"
                closure = self._lower_closure(
                    node.args[0],
                    environment,
                    closure_item,
                    borrowed_parameter=True,
                    expected_result=BOOL,
                    parameter_projection=projection,
                )
                arguments = (closure,)
                result = IteratorType(
                    receiver_type.execution,
                    receiver_type.item_type,
                    receiver_type.item_mode,
                    (
                        IteratorIndexing.UNINDEXED
                        if receiver_type.execution == IteratorExecution.PARALLEL
                        else None
                    ),
                )
            elif method == "filter_map" and len(node.args) == 1:
                closure = self._lower_closure(
                    node.args[0],
                    environment,
                    receiver_type.exposed_item_type,
                    borrowed_parameter=False,
                )
                if closure.body.type_ref.rust_name != "Option":
                    _fail(
                        "CRAB221",
                        "filter_map closure must return Option",
                        "Return rust.Some(value) or an Option-producing expression.",
                        self.path,
                        node.args[0],
                    )
                arguments = (closure,)
                result = IteratorType(
                    receiver_type.execution,
                    closure.body.type_ref.arguments[0],
                    IteratorItemMode.OWNED,
                    (
                        IteratorIndexing.UNINDEXED
                        if receiver_type.execution == IteratorExecution.PARALLEL
                        else None
                    ),
                )
            elif method == "collect_vec" and not node.args:
                if receiver_type.item_mode != IteratorItemMode.OWNED:
                    _fail(
                        "CRAB220",
                        "Borrowed iterator items cannot become an owned Vec",
                        "The iterator still yields borrowed values.",
                        self.path,
                        node,
                        "Use copied(), cloned(), or map into an owned value first.",
                    )
                arguments = ()
                result = TypeRef("Vec", (item_type,))
            elif (
                method == "collect_map"
                and not node.args
                and receiver_type.item_mode == IteratorItemMode.OWNED
                and item_type.rust_name == "Tuple"
                and len(item_type.arguments) == 2
            ):
                arguments = ()
                result = TypeRef("HashMap", item_type.arguments)
            elif (
                method == "sum"
                and not node.args
                and receiver_type.item_mode == IteratorItemMode.OWNED
                and item_type.is_numeric
            ):
                arguments = ()
                result = item_type
            elif method == "count" and not node.args:
                arguments = ()
                result = USIZE
            elif method in {"any", "all"} and len(node.args) == 1:
                arguments = (
                    self._lower_closure(
                        node.args[0],
                        environment,
                        receiver_type.exposed_item_type,
                        borrowed_parameter=False,
                        expected_result=BOOL,
                    ),
                )
                result = BOOL
            elif (
                method == "find"
                and receiver_type.execution == IteratorExecution.PARALLEL
            ):
                _fail(
                    "CRAB225",
                    "Parallel find semantics are ambiguous",
                    "Rayon distinguishes any-match, first-match, and last-match search.",
                    self.path,
                    node,
                    "Use find_any(...), find_first(...), or find_last(...).",
                )
            elif (
                method == "find"
                and receiver_type.execution == IteratorExecution.SEQUENTIAL
                and len(node.args) == 1
            ) or (
                method in {"find_any", "find_first", "find_last"}
                and receiver_type.execution == IteratorExecution.PARALLEL
                and len(node.args) == 1
            ):
                arguments = (
                    self._lower_closure(
                        node.args[0],
                        environment,
                        receiver_type.exposed_item_type,
                        borrowed_parameter=True,
                        expected_result=BOOL,
                        parameter_projection=(
                            "deref"
                            if receiver_type.item_mode != IteratorItemMode.OWNED
                            or _is_copy_semantic_type(item_type)
                            else "borrow"
                        ),
                    ),
                )
                result = TypeRef("Option", (receiver_type.exposed_item_type,))
            elif method == "fold" and len(node.args) == 2:
                if receiver_type.execution != IteratorExecution.SEQUENTIAL:
                    _fail(
                        "CRAB221",
                        "Parallel fold needs an explicit reduction strategy",
                        "Use map(...).reduce(...) for one deterministic final value.",
                        self.path,
                        node,
                    )
                initial = self._lower_expression(
                    node.args[0],
                    environment,
                    expected,
                )
                closure = self._lower_binary_closure(
                    node.args[1],
                    environment,
                    initial.type_ref,
                    receiver_type.exposed_item_type,
                    expected_result=initial.type_ref,
                )
                arguments = (initial, closure)
                result = initial.type_ref
            elif method == "reduce" and len(node.args) == 1:
                closure = self._lower_binary_closure(
                    node.args[0],
                    environment,
                    receiver_type.exposed_item_type,
                    receiver_type.exposed_item_type,
                    expected_result=receiver_type.exposed_item_type,
                )
                arguments = (closure,)
                result = TypeRef("Option", (receiver_type.exposed_item_type,))
            elif method == "enumerate" and not node.args:
                if (
                    receiver_type.execution == IteratorExecution.PARALLEL
                    and receiver_type.indexing != IteratorIndexing.INDEXED
                ):
                    _fail(
                        "CRAB225",
                        "Parallel enumerate requires an indexed iterator",
                        "The preceding adapter removes Rayon's indexed-parallel capability.",
                        self.path,
                        node,
                        "Move enumerate() before filter/filter_map or use a sequential iterator.",
                    )
                arguments = ()
                result = IteratorType(
                    receiver_type.execution,
                    TypeRef("Tuple", (USIZE, receiver_type.exposed_item_type)),
                    IteratorItemMode.OWNED,
                    receiver_type.indexing,
                )
            elif method == "zip" and len(node.args) == 1:
                other = self._lower_expression(node.args[0], environment)
                if not isinstance(other.type_ref, IteratorType) or (
                    other.type_ref.execution != receiver_type.execution
                ):
                    _fail(
                        "CRAB221",
                        "Iterator zip execution modes differ",
                        "zip requires another sequential or parallel iterator of the same family.",
                        self.path,
                        node.args[0],
                    )
                if receiver_type.execution == IteratorExecution.PARALLEL and (
                    receiver_type.indexing != IteratorIndexing.INDEXED
                    or other.type_ref.indexing != IteratorIndexing.INDEXED
                ):
                    _fail(
                        "CRAB225",
                        "Parallel zip requires indexed iterators",
                        "At least one adapter chain has lost Rayon's indexed capability.",
                        self.path,
                        node,
                        "Zip indexed sources before filter/filter_map changes either chain.",
                    )
                arguments = (other,)
                result = IteratorType(
                    receiver_type.execution,
                    TypeRef(
                        "Tuple",
                        (
                            receiver_type.exposed_item_type,
                            other.type_ref.exposed_item_type,
                        ),
                    ),
                    IteratorItemMode.OWNED,
                    receiver_type.indexing,
                )
            else:
                _unsupported(
                    node,
                    self.path,
                    f"Iterator.{method} is not in the Crabwalk capability table.",
                )
        elif receiver_type == INFERRED:
            arguments = tuple(
                self._lower_expression(
                    argument,
                    environment,
                    STR
                    if isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                    else None,
                )
                for argument in node.args
            )
            result = expected or INFERRED
        else:
            _unsupported(
                node,
                self.path,
                f"{receiver_type.display()} has no supported method {method}.",
            )

        if expected is not None:
            _require_type(result, expected, self.path, node)
        required = _builtin_receiver_access(receiver_type, method)
        if receiver.type_ref.ownership == "Ref" and required in {"mutable", "owned"}:
            _fail(
                "CRAB208",
                "Shared receiver cannot satisfy mutable or owned method access",
                f"Method '{method}' requires {required} access to a shared value.",
                self.path,
                node,
            )
        assert isinstance(node.func, ast.Attribute)
        self._require_place_access(node.func.value, required, f"method '{method}'")
        if required == "owned":
            self._consume_local(node.func.value, f"method '{method}'")
        return MethodCallIR(
            receiver,
            method,
            arguments,
            result,
            span,
            None,
            (),
            required,
        )

    def _lower_closure(
        self,
        node: ast.expr,
        environment: dict[str, TypeRef],
        parameter_type: TypeRef,
        *,
        borrowed_parameter: bool,
        expected_result: TypeRef | None = None,
        parameter_projection: Literal["direct", "deref", "borrow"] = "direct",
    ) -> ClosureIR:
        if not isinstance(node, ast.Lambda):
            _fail(
                "CRAB185",
                "Iterator adapter requires a lambda",
                "Use a one-expression lambda with one positional parameter.",
                self.path,
                node,
            )
        arguments = node.args
        if (
            len(arguments.args) != 1
            or arguments.posonlyargs
            or arguments.kwonlyargs
            or arguments.vararg is not None
            or arguments.kwarg is not None
            or arguments.defaults
            or arguments.kw_defaults
        ):
            _fail(
                "CRAB185",
                "Unsupported Rust closure signature",
                "Iterator lambdas take exactly one required positional parameter.",
                self.path,
                node,
            )
        parameter = arguments.args[0].arg
        _validate_source_binding(
            parameter,
            self.path,
            arguments.args[0],
            "closure parameter",
        )
        closure_environment = dict(environment)
        closure_environment[parameter] = parameter_type
        prior_state = self.local_states.get(parameter)
        self._declare_local(parameter, parameter_type)
        try:
            body = self._lower_expression(
                node.body,
                closure_environment,
                expected_result,
            )
        finally:
            if prior_state is None:
                self.local_states.pop(parameter, None)
            else:
                self.local_states[parameter] = prior_state
        if expected_result is not None:
            _require_type(body.type_ref, expected_result, self.path, node.body)
        return ClosureIR(
            parameter,
            parameter_type,
            body,
            borrowed_parameter,
            TypeRef("Closure", (parameter_type, body.type_ref)),
            SourceSpan.from_ast(self.path, node),
            parameter_projection=parameter_projection,
        )

    def _lower_zero_closure(
        self,
        node: ast.expr,
        environment: dict[str, TypeRef],
        *,
        expected_result: TypeRef | None = None,
    ) -> ClosureIR:
        if not isinstance(node, ast.Lambda):
            _fail(
                "CRAB188",
                "Thread spawn requires a lambda",
                "Use a zero-argument expression lambda.",
                self.path,
                node,
            )
        arguments = node.args
        if (
            arguments.args
            or arguments.posonlyargs
            or arguments.kwonlyargs
            or arguments.vararg is not None
            or arguments.kwarg is not None
            or arguments.defaults
            or arguments.kw_defaults
        ):
            _fail(
                "CRAB188",
                "Spawned closure must take no parameters",
                "Move or copy values by capturing them from the enclosing function.",
                self.path,
                node,
            )
        body = self._lower_expression(node.body, dict(environment), expected_result)
        return ClosureIR(
            None,
            UNIT,
            body,
            False,
            TypeRef("Closure", (UNIT, body.type_ref)),
            SourceSpan.from_ast(self.path, node),
        )

    def _lower_binary_closure(
        self,
        node: ast.expr,
        environment: dict[str, TypeRef],
        first_type: TypeRef,
        second_type: TypeRef,
        *,
        expected_result: TypeRef,
    ) -> ClosureIR:
        if not isinstance(node, ast.Lambda):
            _fail(
                "CRAB185",
                "Iterator reduction requires a lambda",
                "Use a one-expression lambda with two positional parameters.",
                self.path,
                node,
            )
        arguments = node.args
        if (
            len(arguments.args) != 2
            or arguments.posonlyargs
            or arguments.kwonlyargs
            or arguments.vararg is not None
            or arguments.kwarg is not None
            or arguments.defaults
            or arguments.kw_defaults
        ):
            _fail(
                "CRAB185",
                "Unsupported reduction closure signature",
                "fold and reduce lambdas take exactly two required parameters.",
                self.path,
                node,
            )
        first, second = (value.arg for value in arguments.args)
        for argument in arguments.args:
            _validate_source_binding(
                argument.arg,
                self.path,
                argument,
                "closure parameter",
            )
        closure_environment = dict(environment)
        closure_environment[first] = first_type
        closure_environment[second] = second_type
        prior_states = {
            first: self.local_states.get(first),
            second: self.local_states.get(second),
        }
        self._declare_local(first, first_type)
        self._declare_local(second, second_type)
        try:
            body = self._lower_expression(
                node.body,
                closure_environment,
                expected_result,
            )
        finally:
            for name, prior_state in prior_states.items():
                if prior_state is None:
                    self.local_states.pop(name, None)
                else:
                    self.local_states[name] = prior_state
        _require_type(body.type_ref, expected_result, self.path, node.body)
        return ClosureIR(
            first,
            first_type,
            body,
            False,
            TypeRef(
                "Closure",
                (TypeRef("Tuple", (first_type, second_type)), body.type_ref),
            ),
            SourceSpan.from_ast(self.path, node),
            second_parameter=second,
            second_parameter_type=second_type,
        )


def _validate_rust_import(tree: ast.Module, path: Path) -> None:
    valid = False
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.module != "crabwalk":
            continue
        for alias in node.names:
            if alias.name == "rust":
                if alias.asname is not None:
                    _fail(
                        "CRAB103",
                        "Unsupported Rust namespace alias",
                        "Use from crabwalk import rust without an alias.",
                        path,
                        alias,
                    )
                valid = True
    if not valid:
        _fail(
            "CRAB104",
            "Missing canonical Rust import",
            "A Crabwalk module must contain from crabwalk import rust.",
            path,
            tree,
        )


def _struct_placeholder(
    node: ast.ClassDef,
    path: Path,
    module_name: str,
    symbol: str,
) -> StructIR:
    if not node.name.isidentifier() or keyword.iskeyword(node.name):
        _fail(
            "CRAB150",
            "Unsupported Rust struct name",
            f"'{node.name}' cannot be represented as a Rust type identifier.",
            path,
            node,
        )
    if node.bases or node.keywords:
        _fail(
            "CRAB150",
            "Rust structs cannot inherit",
            "@rust.struct classes do not support Python bases or metaclass keywords.",
            path,
            node,
        )
    if len(node.decorator_list) != 1:
        _fail(
            "CRAB150",
            "Unsupported struct decorator combination",
            "@rust.struct must be the class's only decorator.",
            path,
            node,
        )
    return StructIR(
        name=node.name,
        module_name=module_name,
        symbol=symbol,
        fields=(),
        derives=(),
        span=SourceSpan.from_ast(path, node),
    )


def _analyze_struct(
    node: ast.ClassDef,
    placeholder: StructIR,
    path: Path,
    domain_types: dict[str, TypeRef],
    crates: dict[str, CrateIR],
) -> StructIR:
    fields: list[StructFieldIR] = []
    names: set[str] = set()
    for child in node.body:
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, str)
        ) or isinstance(child, ast.Pass):
            continue
        if not (
            isinstance(child, ast.AnnAssign)
            and isinstance(child.target, ast.Name)
            and child.value is None
        ):
            _unsupported(
                child,
                path,
                "@rust.struct bodies currently contain annotated fields only.",
            )
        if child.target.id in names:
            _fail(
                "CRAB155",
                "Duplicate Rust struct field",
                f"Field '{child.target.id}' is declared more than once.",
                path,
                child.target,
            )
        _validate_source_binding(
            child.target.id,
            path,
            child.target,
            "struct field",
            reserved=STRUCT_FIELD_RESERVED_NAMES,
            rust_namespace="member",
        )
        names.add(child.target.id)
        field_type = _annotation_type(
            child.annotation,
            path,
            child,
            domain_types,
        )
        if field_type == STR or field_type.ownership is not None:
            _fail(
                "CRAB156",
                "Borrowed struct fields are unsupported",
                "Use owned field types such as rust.String or another domain type.",
                path,
                child.annotation,
            )
        if not _struct_field_type_supported(
            field_type,
            {value.rust_name for value in domain_types.values()},
        ):
            _fail(
                "CRAB159",
                "Unsupported Python-visible struct field type",
                "Struct fields support primitives, String, Vec/Option whose leaves "
                "are boundary primitives, and directly nested domain types. "
                "Vec/Option of domain types are not supported.",
                path,
                child.annotation,
                "Use a direct nested domain field, a top-level Vec[Domain] boundary, "
                "or parallel primitive vectors with an application-validated length "
                "invariant.",
            )
        fields.append(
            StructFieldIR(
                child.target.id,
                field_type,
                SourceSpan.from_ast(path, child),
            )
        )
    if not fields:
        _fail(
            "CRAB157",
            "Rust struct has no fields",
            "Declare at least one annotated field.",
            path,
            node,
        )
    field_nodes = {
        child.target.id: child.target
        for child in node.body
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
    }
    for field_name in names:
        colliding_getter = f"set_{field_name}"
        if colliding_getter in names:
            _fail(
                "CRAB210",
                "Generated pyclass member collision",
                (
                    f"Field '{colliding_getter}' collides with the generated setter "
                    f"for field '{field_name}'."
                ),
                path,
                field_nodes[colliding_getter],
                "Rename one field so no field is named set_<another field>.",
            )
    derives = _domain_derives(node, path, crates, "struct")
    return replace(placeholder, fields=tuple(fields), derives=derives)


def _domain_derives(
    node: ast.ClassDef,
    path: Path,
    crates: dict[str, CrateIR],
    kind: str,
) -> tuple[tuple[str, ...], ...]:
    decorator = node.decorator_list[0]
    if isinstance(decorator, ast.Attribute):
        return ()
    assert isinstance(decorator, ast.Call)
    if decorator.args or any(value.arg != "derive" for value in decorator.keywords):
        _fail(
            "CRAB158",
            f"Unsupported rust.{kind} option",
            f"rust.{kind} accepts only derive=[crate.Derive, ...].",
            path,
            decorator,
        )
    keyword_node = next(
        (value for value in decorator.keywords if value.arg == "derive"),
        None,
    )
    if keyword_node is None:
        return ()
    value = keyword_node.value
    if not isinstance(value, (ast.List, ast.Tuple)):
        _fail(
            "CRAB158",
            "Struct derives must be static",
            "derive must be a literal list or tuple of imported crate paths.",
            path,
            value,
        )
    derives: list[tuple[str, ...]] = []
    for item in value.elts:
        derive = _crate_path(item, crates)
        if derive is None or len(derive) < 2:
            _fail(
                "CRAB158",
                "Unresolved Rust derive",
                "Each derive must resolve through a statically declared rust.crate.",
                path,
                item,
            )
        derives.append(derive)
    return tuple(derives)


def _enum_placeholder(
    node: ast.ClassDef,
    path: Path,
    module_name: str,
    symbol: str,
) -> EnumIR:
    if not node.name.isidentifier() or keyword.iskeyword(node.name):
        _fail(
            "CRAB160",
            "Unsupported Rust enum name",
            f"'{node.name}' cannot be represented as a Rust type identifier.",
            path,
            node,
        )
    if node.bases or node.keywords or len(node.decorator_list) != 1:
        _fail(
            "CRAB160",
            "Unsupported Rust enum declaration",
            "@rust.enum classes cannot inherit and must use one decorator.",
            path,
            node,
        )
    return EnumIR(
        node.name, module_name, symbol, (), (), SourceSpan.from_ast(path, node)
    )


def _analyze_enum(
    node: ast.ClassDef,
    placeholder: EnumIR,
    path: Path,
    domain_types: dict[str, TypeRef],
    crates: dict[str, CrateIR],
) -> EnumIR:
    variants: list[EnumVariantIR] = []
    names: set[str] = set()
    for child in node.body:
        if (
            isinstance(child, ast.Expr)
            and isinstance(child.value, ast.Constant)
            and isinstance(child.value.value, str)
        ) or isinstance(child, ast.Pass):
            continue
        if not (
            isinstance(child, ast.Assign)
            and len(child.targets) == 1
            and isinstance(child.targets[0], ast.Name)
            and isinstance(child.value, ast.Call)
            and _is_rust_attribute(child.value.func)
            and isinstance(child.value.func, ast.Attribute)
            and child.value.func.attr == "variant"
        ):
            _unsupported(
                child,
                path,
                "@rust.enum bodies contain Name = rust.variant(...) declarations only.",
            )
        variant_name = child.targets[0].id
        _validate_source_binding(
            variant_name,
            path,
            child.targets[0],
            "enum variant",
            reserved=ENUM_VARIANT_RESERVED_NAMES,
            rust_namespace="member",
        )
        if variant_name in names:
            _fail(
                "CRAB161",
                "Invalid or duplicate enum variant",
                f"Variant '{variant_name}' is invalid or already declared.",
                path,
                child.targets[0],
            )
        names.add(variant_name)
        call = child.value
        if call.args and call.keywords:
            _fail(
                "CRAB162",
                "Mixed enum variant fields",
                "Use positional tuple fields or named record fields, not both.",
                path,
                call,
            )
        field_nodes = (
            [(f"_{index}", value) for index, value in enumerate(call.args)]
            if call.args
            else [
                (str(value.arg), value.value)
                for value in call.keywords
                if value.arg is not None
            ]
        )
        if len(field_nodes) != len(call.args) + len(call.keywords):
            _unsupported(call, path, "Enum variants do not support **kwargs.")
        for field_name, field_node in field_nodes:
            if not field_name.startswith("_") or not field_name[1:].isdigit():
                _validate_source_binding(
                    field_name,
                    path,
                    field_node,
                    "enum field",
                    reserved=ENUM_FIELD_RESERVED_NAMES,
                    rust_namespace="member",
                )
        fields = tuple(
            StructFieldIR(
                field_name,
                _annotation_type(field_node, path, field_node, domain_types),
                SourceSpan.from_ast(path, field_node),
            )
            for field_name, field_node in field_nodes
        )
        visible_domain_symbols = {value.rust_name for value in domain_types.values()}
        if any(
            not _enum_field_type_supported(field.type_ref, visible_domain_symbols)
            for field in fields
        ):
            _fail(
                "CRAB163",
                "Unsupported enum payload type",
                "Enum payloads support ordinary fields and visible Crabwalk domain types.",
                path,
                call,
            )
        variants.append(
            EnumVariantIR(
                variant_name,
                fields,
                bool(call.args),
                SourceSpan.from_ast(path, child),
            )
        )
    if not variants:
        _fail(
            "CRAB164",
            "Rust enum has no variants",
            "Declare at least one rust.variant().",
            path,
            node,
        )
    variant_names = {variant.name for variant in variants}
    for variant in variants:
        for field in variant.fields:
            if field.name in variant_names:
                raise CrabwalkCompilationError(
                    Diagnostic(
                        "CRAB210",
                        "Generated pyclass member collision",
                        (
                            f"Enum field '{field.name}' collides with a generated "
                            "variant constructor of the same name."
                        ),
                        field.span,
                        "Rename the field or variant.",
                    )
                )
    return replace(
        placeholder,
        variants=tuple(variants),
        derives=_domain_derives(node, path, crates, "enum"),
    )


def _analyze_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    path: Path,
    domain_types: dict[str, TypeRef] | None = None,
    crates: dict[str, CrateIR] | None = None,
) -> _Signature:
    if not node.name.isidentifier() or keyword.iskeyword(node.name):
        _fail(
            "CRAB105",
            "Unsupported function name",
            f"'{node.name}' cannot yet be represented as a Rust identifier.",
            path,
            node,
        )
    arguments = node.args
    if (
        arguments.posonlyargs
        or arguments.kwonlyargs
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or arguments.defaults
        or arguments.kw_defaults
    ):
        _fail(
            "CRAB106",
            "Unsupported function signature",
            "M2 supports only required positional parameters.",
            path,
            arguments,
            "Remove defaults, positional-only markers, keyword-only parameters, and variadics.",
        )
    if len(node.decorator_list) != 1:
        _fail(
            "CRAB107",
            "Unsupported decorator combination",
            "@rust.fn must be the function's only decorator.",
            path,
            node,
        )
    external_path, external_effects = _extern_decorator_metadata(
        node,
        path,
        crates or {},
    )
    if external_path is None:
        method_name, method_for, trait_symbol, operator_kind = (
            _method_decorator_metadata(
                node,
                path,
                domain_types or {},
            )
        )
        type_parameters = _generic_type_parameters(node, path, domain_types or {})
    else:
        method_name = None
        method_for = None
        trait_symbol = None
        operator_kind = None
        type_parameters = ()
    is_async = isinstance(node, ast.AsyncFunctionDef)
    exported = (
        external_path is None
        and not type_parameters
        and not is_async
        and method_name is None
    )
    parameters_list: list[ParameterIR] = []
    for argument in arguments.args:
        _validate_source_binding(argument.arg, path, argument, "parameter")
        parameters_list.append(
            ParameterIR(
                argument.arg,
                _annotation_type(argument.annotation, path, argument, domain_types),
                SourceSpan.from_ast(path, argument),
            )
        )
    parameters = tuple(parameters_list)
    for parameter, argument in zip(parameters, arguments.args):
        if parameter.type_ref == UNIT:
            _fail(
                "CRAB108",
                "Unsupported Rust parameter type",
                "Function parameters cannot have the unit type.",
                path,
                node,
            )
        if not exported:
            continue
        if parameter.type_ref.ownership is not None:
            underlying = parameter.type_ref.underlying
            valid_owned_vector = (
                underlying.rust_name == "Vec"
                and len(underlying.arguments) == 1
                and _owned_vector_element_supported(
                    underlying.arguments[0],
                    {
                        value.rust_name
                        for value in (domain_types or {}).values()
                        if value.python_name is not None
                        and value.rust_name not in {"Trait", "Dyn"}
                    },
                    allow_domain=True,
                )
            )
            valid_domain = (
                underlying.python_name is not None and not underlying.arguments
            )
            if not (valid_owned_vector or valid_domain):
                _fail(
                    "CRAB142",
                    "Unsupported Python-crossing ownership type",
                    (
                        "The ownership preview currently supports Owned, Ref, and "
                        "Mut around concrete Vec[T] or a generated domain type."
                    ),
                    path,
                    argument.annotation or argument,
                    "Use a supported concrete Vec or @rust.struct type.",
                )
        elif parameter.type_ref.python_name is not None:
            _fail(
                "CRAB153",
                "Domain parameter needs explicit ownership",
                "Wrap generated domain parameters in rust.Owned, rust.Ref, or rust.Mut.",
                path,
                argument.annotation or argument,
            )
        elif (
            parameter.type_ref.rust_name == "Buffer"
            and not _python_parameter_boundary_supported(parameter.type_ref)
        ):
            _fail(
                "CRAB228",
                "Unsupported borrowed buffer element type",
                (
                    f"{parameter.type_ref.display()} is outside the read-only buffer "
                    "boundary. Buffer elements must be flat PyO3-compatible numeric "
                    "primitives."
                ),
                path,
                argument.annotation or argument,
                (
                    "Use i8/i16/i32/i64, u8/u16/u32/u64/usize, f32, or f64. "
                    "Buffers are top-level exported inputs only."
                ),
            )
        elif not _python_parameter_boundary_supported(parameter.type_ref):
            _fail(
                "CRAB201",
                "Implicit complex parameter conversion is unsupported",
                (
                    f"{parameter.type_ref.display()} cannot cross an exported Python "
                    "boundary implicitly."
                ),
                path,
                argument.annotation or argument,
                (
                    "For Vec[T], accept rust.Owned[rust.Vec[T]], "
                    "rust.Ref[rust.Vec[T]], or rust.Mut[rust.Vec[T]] and construct "
                    "the value with rust.from_python(...)."
                ),
            )
    if method_name is not None:
        if not parameters or method_for is None:
            _fail(
                "CRAB190",
                "Rust method requires a receiver",
                "A @rust.method or @rust.impl helper needs a first receiver parameter.",
                path,
                node,
            )
        receiver_type = parameters[0].type_ref
        if receiver_type.ownership not in {"Owned", "Ref", "Mut"}:
            _fail(
                "CRAB190",
                "Rust method receiver needs explicit ownership",
                "Use rust.Owned[T], rust.Ref[T], or rust.Mut[T] for parameter one.",
                path,
                arguments.args[0],
            )
        _require_type(
            receiver_type.underlying,
            method_for,
            path,
            arguments.args[0],
        )
        if trait_symbol is not None and receiver_type.ownership != "Ref":
            _fail(
                "CRAB190",
                "Trait object method receiver must be shared",
                "The first trait-object milestone supports rust.Ref[T] receivers.",
                path,
                arguments.args[0],
            )
    return_type = (
        UNIT
        if node.returns is None
        else _annotation_type(node.returns, path, node, domain_types)
    )
    if operator_kind is not None:
        if len(parameters) != 2 or method_for is None:
            _fail(
                "CRAB193",
                "Rust add operator needs two operands",
                "Define an owned self parameter and one concrete right-hand operand.",
                path,
                node,
            )
        if parameters[0].type_ref.ownership != "Owned":
            _fail(
                "CRAB193",
                "Rust add receiver must be owned",
                "Annotate parameter one as rust.Owned[DomainType].",
                path,
                arguments.args[0],
            )
        if parameters[1].type_ref.ownership in {"Ref", "Mut"}:
            _fail(
                "CRAB193",
                "Rust add right operand must be owned",
                "Use a concrete value or rust.Owned[T] as the second parameter.",
                path,
                arguments.args[1],
            )
    if exported and return_type.ownership is not None:
        underlying = return_type.underlying
        valid_owned_return = return_type.ownership == "Owned" and (
            (underlying.python_name is not None and not underlying.arguments)
            or (
                underlying.rust_name == "Vec"
                and len(underlying.arguments) == 1
                and _owned_vector_element_supported(
                    underlying.arguments[0],
                    {
                        value.rust_name
                        for value in (domain_types or {}).values()
                        if value.python_name is not None
                        and value.rust_name not in {"Trait", "Dyn"}
                    },
                    allow_domain=True,
                )
            )
        )
        if not valid_owned_return:
            _fail(
                "CRAB141",
                "Unsupported owned return boundary",
                "Exported returns support rust.Owned around a domain value or supported Vec.",
                path,
                node.returns or node,
            )
    if exported and return_type.python_name is not None:
        _fail(
            "CRAB154",
            "Domain return boundary is not yet explicit",
            "Return a primitive/container result, or consume the domain value internally.",
            path,
            node.returns or node,
        )
    if exported and return_type == STR:
        _fail(
            "CRAB124",
            "Borrowed string return is unsupported",
            "rust.Str cannot be returned because its lifetime is not expressible here.",
            path,
            node.returns or node,
            "Return rust.String instead.",
        )
    if exported and return_type.underlying.rust_name == "Buffer":
        _fail(
            "CRAB228",
            "Borrowed buffer return is unsupported",
            "rust.Buffer[T] is a call-scoped Python input view and cannot be returned.",
            path,
            node.returns or node,
            "Return a scalar, rust.Vec[T], or rust.Owned[rust.Vec[T]].",
        )
    if (
        exported
        and return_type.ownership is None
        and return_type.rust_name == "HashMap"
        and len(return_type.arguments) == 2
        and not _python_mapping_key_supported(return_type.arguments[0])
    ):
        key_type = return_type.arguments[0]
        _fail(
            "CRAB202",
            "HashMap key has no lossless Python representation",
            (
                f"{key_type.display()} does not have a hashable, injective Python "
                "representation and cannot safely become a dictionary key."
            ),
            path,
            node.returns or node,
            "Use scalar, String, Vec[u8], or recursively hashable and injective tuple keys.",
        )
    if (
        exported
        and return_type.ownership is None
        and not _python_return_boundary_supported(return_type)
    ):
        _fail(
            "CRAB202",
            "Implicit complex return conversion is unsupported",
            f"{return_type.display()} cannot cross an exported Python boundary implicitly.",
            path,
            node.returns or node,
            "Return a primitive, String, Option of a supported value, or Result of one.",
        )
    return _Signature(
        node.name,
        parameters,
        return_type,
        node,
        type_parameters=type_parameters,
        exported=exported,
        is_async=is_async,
        method_name=method_name,
        method_for=method_for,
        trait_symbol=trait_symbol,
        operator_kind=operator_kind,
        external_path=external_path,
        external_effects=external_effects,
    )


def _annotation_type(
    annotation: ast.expr | None,
    path: Path,
    node: ast.AST,
    domain_types: dict[str, TypeRef] | None = None,
) -> TypeRef:
    if isinstance(annotation, ast.Constant) and annotation.value is None:
        return UNIT
    if _is_rust_attribute(annotation):
        assert isinstance(annotation, ast.Attribute)
        primitive = _PRIMITIVES.get(annotation.attr)
        if primitive is not None:
            return primitive
    if isinstance(annotation, ast.Name) and domain_types is not None:
        domain = domain_types.get(annotation.id)
        if domain is not None:
            return domain
    if isinstance(annotation, ast.Attribute) and domain_types is not None:
        domain = domain_types.get(".".join(_attribute_parts(annotation)))
        if domain is not None:
            return domain
    if isinstance(annotation, ast.Subscript) and _is_rust_attribute(annotation.value):
        assert isinstance(annotation.value, ast.Attribute)
        if annotation.value.attr == "Dyn":
            if domain_types is None:
                _fail(
                    "CRAB191",
                    "Dynamic trait type is unresolved",
                    "rust.Dyn[Trait] requires a visible rust.trait declaration.",
                    path,
                    annotation,
                )
            trait_type = _annotation_type(
                annotation.slice,
                path,
                annotation.slice,
                domain_types,
            )
            if trait_type.rust_name != "Trait" or trait_type.python_name is None:
                _fail(
                    "CRAB191",
                    "rust.Dyn requires a Rust trait",
                    "Use rust.Dyn[Draw] where Draw was declared with rust.trait.",
                    path,
                    annotation.slice,
                )
            return TypeRef("Dyn", python_name=trait_type.python_name)
        if annotation.value.attr == "Borrow":
            if (
                not isinstance(annotation.slice, ast.Tuple)
                or len(annotation.slice.elts) != 2
                or not isinstance(annotation.slice.elts[0], ast.Name)
                or domain_types is None
            ):
                _fail(
                    "CRAB183",
                    "Named Rust borrow needs a lifetime and type",
                    'Use rust.Borrow[a, rust.Str] with a = rust.lifetime("a").',
                    path,
                    annotation,
                )
            lifetime = domain_types.get(annotation.slice.elts[0].id)
            if lifetime is None or not lifetime.is_lifetime:
                _fail(
                    "CRAB183",
                    "Unknown Rust lifetime",
                    "The first rust.Borrow argument must name a local rust.lifetime.",
                    path,
                    annotation.slice.elts[0],
                )
            target = _annotation_type(
                annotation.slice.elts[1],
                path,
                annotation.slice.elts[1],
                domain_types,
            )
            if target.rust_name in {"Owned", "Ref", "Mut", "LifetimeRef"}:
                _fail(
                    "CRAB183",
                    "Nested Rust borrow is unsupported",
                    "Borrow a concrete Rust type directly.",
                    path,
                    annotation.slice.elts[1],
                )
            return TypeRef(
                "LifetimeRef",
                (target,),
                python_name=lifetime.rust_name,
            )
        if annotation.value.attr == "Tuple":
            values = (
                tuple(annotation.slice.elts)
                if isinstance(annotation.slice, ast.Tuple)
                else (annotation.slice,)
            )
            if not values:
                _fail(
                    "CRAB108",
                    "Rust tuple needs at least one type",
                    "Use rust.Tuple[T] or the unit return None.",
                    path,
                    annotation,
                )
            return TypeRef(
                "Tuple",
                tuple(
                    _annotation_type(value, path, value, domain_types)
                    for value in values
                ),
            )
        if annotation.value.attr == "Array":
            if (
                not isinstance(annotation.slice, ast.Tuple)
                or len(annotation.slice.elts) != 2
                or not isinstance(annotation.slice.elts[1], ast.Constant)
                or type(annotation.slice.elts[1].value) is not int
                or annotation.slice.elts[1].value <= 0
            ):
                _fail(
                    "CRAB108",
                    "Rust array needs an element type and positive length",
                    "Use rust.Array[rust.u64, 4].",
                    path,
                    annotation,
                )
            return TypeRef(
                "Array",
                (
                    _annotation_type(
                        annotation.slice.elts[0],
                        path,
                        annotation.slice.elts[0],
                        domain_types,
                    ),
                ),
                const_value=int(annotation.slice.elts[1].value),
            )
        arity = _GENERIC_ARITY.get(annotation.value.attr)
        if arity is not None:
            values = (
                tuple(annotation.slice.elts)
                if isinstance(annotation.slice, ast.Tuple)
                else (annotation.slice,)
            )
            if len(values) != arity:
                _fail(
                    "CRAB108",
                    "Wrong number of Rust type arguments",
                    f"rust.{annotation.value.attr} expects {arity} type argument(s).",
                    path,
                    annotation,
                )
            return TypeRef(
                annotation.value.attr,
                tuple(
                    _annotation_type(value, path, value, domain_types)
                    for value in values
                ),
            )
    _fail(
        "CRAB108",
        "Unsupported or missing Rust type",
        "Use a supported type from the canonical rust namespace.",
        path,
        annotation or node,
    )


_GENERIC_TRAIT_BOUNDS = {"Clone", "Copy", "Debug", "Display", "Ord", "PartialOrd"}


def _discover_traits(
    tree: ast.Module,
    path: Path,
    module_name: str,
    symbol_for: Callable[[str], str],
) -> dict[str, TraitIR]:
    """Discover declarative, object-safe traits with shared no-argument methods."""

    traits: dict[str, TraitIR] = {}
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and _is_rust_attribute(node.value.func)
            and node.value.func.attr == "trait"
        ):
            continue
        binding = node.targets[0].id
        call = node.value
        if (
            len(call.args) != 1
            or not isinstance(call.args[0], ast.Constant)
            or not isinstance(call.args[0].value, str)
            or call.args[0].value != binding
        ):
            _fail(
                "CRAB191",
                "Rust trait name must be static",
                f'Use {binding} = rust.trait("{binding}", method=rust.ReturnType).',
                path,
                call,
            )
        if not binding.isidentifier() or keyword.iskeyword(binding):
            _fail(
                "CRAB191",
                "Unsupported Rust trait name",
                f"'{binding}' cannot be emitted as a Rust trait identifier.",
                path,
                node.targets[0],
            )
        methods: list[TraitMethodIR] = []
        seen: set[str] = set()
        for option in call.keywords:
            if option.arg is None:
                _fail(
                    "CRAB191",
                    "Rust trait methods must be static",
                    "Trait declarations do not accept **kwargs.",
                    path,
                    option,
                )
            method_name = option.arg
            if method_name in seen or not is_rust_2024_identifier(method_name):
                _fail(
                    "CRAB191",
                    "Invalid Rust trait method",
                    f"'{method_name}' is duplicated or is not a Rust identifier.",
                    path,
                    option,
                )
            seen.add(method_name)
            return_type = _annotation_type(option.value, path, option.value, {})
            if return_type.ownership is not None or return_type.rust_name in {
                "Trait",
                "Dyn",
                "LifetimeRef",
            }:
                _fail(
                    "CRAB191",
                    "Unsupported trait method return",
                    "The first trait-object milestone uses owned concrete return types.",
                    path,
                    option.value,
                )
            methods.append(
                TraitMethodIR(
                    method_name,
                    return_type,
                    SourceSpan.from_ast(path, option),
                )
            )
        if not methods:
            _fail(
                "CRAB191",
                "Rust trait has no methods",
                "Declare at least one method as a keyword return type.",
                path,
                call,
            )
        traits[binding] = TraitIR(
            binding,
            module_name,
            symbol_for(binding),
            tuple(methods),
            SourceSpan.from_ast(path, node),
        )
    return traits


def _discover_type_variables(tree: ast.Module, path: Path) -> dict[str, TypeRef]:
    """Discover static Rust type-variable and lifetime declarations."""

    values: dict[str, TypeRef] = {}
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and _is_rust_attribute(node.value.func)
            and node.value.func.attr in {"typevar", "lifetime"}
        ):
            continue
        binding = node.targets[0].id
        is_lifetime = node.value.func.attr == "lifetime"
        identifier_is_valid = (
            is_crabwalk_lifetime_parameter(binding)
            if is_lifetime
            else is_crabwalk_type_parameter(binding)
        )
        if (
            binding in values
            or not identifier_is_valid
            or len(node.value.args) != 1
            or node.value.keywords
            or not isinstance(node.value.args[0], ast.Constant)
            or node.value.args[0].value != binding
        ):
            _fail(
                "CRAB180",
                "Invalid generic type declaration",
                'Use a unique declaration such as T = rust.typevar("T").',
                path,
                node,
            )
        values[binding] = TypeRef(
            binding,
            is_generic=True,
            is_lifetime=is_lifetime,
        )
    return values


def _generic_type_parameters(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    path: Path,
    visible_types: dict[str, TypeRef],
) -> tuple[TypeParameterIR, ...]:
    decorator = node.decorator_list[0]
    if isinstance(decorator, ast.Attribute):
        return ()
    if (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and _is_rust_attribute(decorator.func)
        and decorator.func.attr in {"method", "impl", "operator"}
    ):
        return ()
    if not (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and _is_rust_attribute(decorator.func)
        and decorator.func.attr == "generic"
    ):
        _fail(
            "CRAB107",
            "Unsupported Rust function decorator",
            "Use @rust.fn, @rust.async_fn, or @rust.generic(...).",
            path,
            decorator,
        )
    if not decorator.args or any(
        not isinstance(value, ast.Name) for value in decorator.args
    ):
        _fail(
            "CRAB180",
            "Generic parameters must be static",
            "Pass one or more names declared with rust.typevar.",
            path,
            decorator,
        )
    names = tuple(value.id for value in decorator.args if isinstance(value, ast.Name))
    if len(set(names)) != len(names) or any(
        not visible_types.get(name) or not visible_types[name].is_generic
        for name in names
    ):
        _fail(
            "CRAB180",
            "Unknown or duplicate generic parameter",
            "Every @rust.generic parameter must name a local rust.typevar declaration.",
            path,
            decorator,
        )
    if any(value.arg != "bounds" for value in decorator.keywords):
        _fail(
            "CRAB181",
            "Unsupported generic option",
            "@rust.generic accepts only bounds=[rust.Trait, ...].",
            path,
            decorator,
        )
    bounds_node = next(
        (value.value for value in decorator.keywords if value.arg == "bounds"), None
    )
    bound_names: tuple[str, ...] = ()
    if bounds_node is not None:
        if not isinstance(bounds_node, (ast.List, ast.Tuple)):
            _fail(
                "CRAB181",
                "Generic bounds must be static",
                "Use a literal list of rust trait markers.",
                path,
                bounds_node,
            )
        collected: list[str] = []
        for value in bounds_node.elts:
            if (
                not _is_rust_attribute(value)
                or not isinstance(value, ast.Attribute)
                or value.attr not in _GENERIC_TRAIT_BOUNDS
            ):
                _fail(
                    "CRAB181",
                    "Unsupported generic trait bound",
                    "Supported bounds are Clone, Copy, Debug, Display, Ord, and PartialOrd.",
                    path,
                    value,
                )
            collected.append(value.attr)
        bound_names = tuple(dict.fromkeys(collected))
    return tuple(
        TypeParameterIR(
            name,
            () if visible_types[name].is_lifetime else bound_names,
            SourceSpan.from_ast(path, decorator),
            is_lifetime=visible_types[name].is_lifetime,
        )
        for name in names
    )


def _method_decorator_metadata(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    path: Path,
    visible_types: dict[str, TypeRef],
) -> tuple[str | None, TypeRef | None, str | None, str | None]:
    decorator = node.decorator_list[0]
    if not (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and _is_rust_attribute(decorator.func)
        and decorator.func.attr in {"method", "impl", "operator"}
    ):
        return None, None, None, None

    kind = decorator.func.attr
    expected_arguments = 2 if kind == "impl" else 1
    if len(decorator.args) != expected_arguments:
        _fail(
            "CRAB190",
            f"Invalid rust.{kind} declaration",
            f"rust.{kind} expects {expected_arguments} static type argument(s).",
            path,
            decorator,
        )
    if (
        any(value.arg != "name" for value in decorator.keywords)
        or len(decorator.keywords) > 1
    ):
        _fail(
            "CRAB190",
            f"Invalid rust.{kind} option",
            f"rust.{kind} accepts only name='method_name'.",
            path,
            decorator,
        )
    explicit_name = next(
        (value.value for value in decorator.keywords if value.arg == "name"),
        None,
    )
    if explicit_name is None:
        method_name = node.name
    elif isinstance(explicit_name, ast.Constant) and isinstance(
        explicit_name.value, str
    ):
        method_name = explicit_name.value
    else:
        _fail(
            "CRAB190",
            "Rust method name must be static",
            "Use a literal string for the name option.",
            path,
            explicit_name,
        )
    if not is_rust_2024_identifier(method_name):
        _fail(
            "CRAB190",
            "Unsupported Rust method name",
            f"'{method_name}' cannot be emitted as a Rust method.",
            path,
            decorator,
        )
    if kind == "operator" and method_name != "add":
        _fail(
            "CRAB193",
            "Unsupported Rust operator implementation",
            "The first operator milestone supports name='add'.",
            path,
            decorator,
        )

    trait_symbol: str | None = None
    target_node = decorator.args[0]
    if kind == "impl":
        trait_type = _annotation_type(
            decorator.args[0],
            path,
            decorator.args[0],
            visible_types,
        )
        if trait_type.rust_name != "Trait" or trait_type.python_name is None:
            _fail(
                "CRAB190",
                "rust.impl requires a declared Rust trait",
                "Argument one must name a value declared with rust.trait(...).",
                path,
                decorator.args[0],
            )
        trait_symbol = trait_type.python_name
        target_node = decorator.args[1]
    target = _annotation_type(target_node, path, target_node, visible_types)
    if (
        target.rust_name
        in {
            "Trait",
            "Dyn",
            "Owned",
            "Ref",
            "Mut",
            "LifetimeRef",
        }
        or target.python_name is None
    ):
        _fail(
            "CRAB190",
            f"rust.{kind} requires a generated domain type",
            "Name a concrete @rust.struct type.",
            path,
            target_node,
        )
    return (
        method_name,
        target,
        trait_symbol,
        method_name if kind == "operator" else None,
    )


def _discover_external_types(
    tree: ast.Module,
    path: Path,
    crates: dict[str, CrateIR],
) -> dict[str, ExternalType]:
    """Discover statically typed crate-owned values used by adapter signatures."""

    values: dict[str, ExternalType] = {}
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and _is_rust_call_named(node.value, "extern_type")
        ):
            continue
        binding = node.targets[0].id
        _validate_source_binding(
            binding,
            path,
            node.targets[0],
            "external type",
            rust_namespace="type",
        )
        call = node.value
        crate_path = _crate_path(call.args[0], crates) if len(call.args) == 1 else None
        path_nodes = [value for value in call.keywords if value.arg == "path"]
        if (
            crate_path is None
            or len(crate_path) != 1
            or len(path_nodes) != 1
            or len(call.keywords) != 1
            or not isinstance(path_nodes[0].value, ast.Constant)
            or not isinstance(path_nodes[0].value.value, str)
        ):
            _fail(
                "CRAB224",
                "Invalid external Rust type declaration",
                "Use TypeName = rust.extern_type(crate_name, path='module::Type').",
                path,
                call,
            )
        rust_path = tuple(path_nodes[0].value.value.split("::"))
        if not rust_path or any(
            not is_rust_2024_identifier(part) for part in rust_path
        ):
            _fail(
                "CRAB224",
                "Invalid external Rust type path",
                "Every component must be a static Rust identifier.",
                path,
                path_nodes[0].value,
            )
        values[binding] = ExternalType(crate_path[0], rust_path, binding)
    return values


_EXTERN_EFFECTS: dict[str, Effect] = {
    "PythonRuntime": Effect.PYTHON_RUNTIME,
    "Blocking": Effect.BLOCKING,
    "ThreadSpawn": Effect.THREAD_SPAWN,
    "GlobalMutation": Effect.GLOBAL_MUTATION,
    "UnsafeMemory": Effect.UNSAFE_MEMORY,
    "UnsafeFfi": Effect.UNSAFE_FFI,
    "MayPanic": Effect.MAY_PANIC,
}


def _extern_decorator_metadata(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    path: Path,
    crates: dict[str, CrateIR],
) -> tuple[tuple[str, ...] | None, tuple[Effect, ...] | None]:
    if not _is_extern_declaration(node):
        return None, None
    if isinstance(node, ast.AsyncFunctionDef):
        _fail(
            "CRAB225",
            "External adapter cannot be async",
            "Declare a synchronous crate function and wrap it in a compiled async helper.",
            path,
            node,
        )
    decorator = node.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    crate_path = (
        _crate_path(decorator.args[0], crates) if len(decorator.args) == 1 else None
    )
    options = {value.arg: value for value in decorator.keywords if value.arg}
    path_option = options.get("path")
    effects_option = options.get("effects")
    if (
        crate_path is None
        or len(crate_path) != 1
        or set(options) - {"path", "effects"}
        or path_option is None
        or not isinstance(path_option.value, ast.Constant)
        or not isinstance(path_option.value.value, str)
    ):
        _fail(
            "CRAB225",
            "Invalid external crate adapter",
            "Use @rust.extern(crate_name, path='module::function', effects=[...]).",
            path,
            decorator,
        )
    rust_path = tuple(path_option.value.value.split("::"))
    if not rust_path or any(not is_rust_2024_identifier(part) for part in rust_path):
        _fail(
            "CRAB225",
            "Invalid external adapter path",
            "Every path component must be a static Rust identifier.",
            path,
            path_option.value,
        )

    if effects_option is None:
        effects = (Effect.OPAQUE_CRATE_CALL, Effect.MAY_PANIC)
    else:
        effects_node = effects_option.value
        if not isinstance(effects_node, (ast.List, ast.Tuple)) or not effects_node.elts:
            _fail(
                "CRAB225",
                "External adapter effects must be explicit",
                "Use [rust.Pure] or a non-empty list of declared effects.",
                path,
                effects_node,
            )
        names: list[str] = []
        for value in effects_node.elts:
            if not _is_rust_attribute(value) or not isinstance(value, ast.Attribute):
                _fail(
                    "CRAB225",
                    "Invalid external adapter effect",
                    "Use effect markers from the canonical rust namespace.",
                    path,
                    value,
                )
            names.append(value.attr)
        if "Pure" in names:
            if names != ["Pure"]:
                _fail(
                    "CRAB225",
                    "Pure adapter has conflicting effects",
                    "rust.Pure must be the only effect marker.",
                    path,
                    effects_node,
                )
            effects = ()
        else:
            unknown = sorted(set(names) - set(_EXTERN_EFFECTS))
            if unknown:
                _fail(
                    "CRAB225",
                    "Unknown external adapter effect",
                    f"Unsupported effect marker(s): {', '.join(unknown)}.",
                    path,
                    effects_node,
                )
            effects = tuple(dict.fromkeys(_EXTERN_EFFECTS[name] for name in names))

    if not (
        len(node.body) == 1
        and (
            isinstance(node.body[0], ast.Pass)
            or (
                isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and node.body[0].value.value is Ellipsis
            )
        )
    ):
        _fail(
            "CRAB225",
            "External adapter has a Python body",
            "Use pass or ...; the declaration describes an existing Rust function.",
            path,
            node,
        )
    return (*crate_path, *rust_path), effects


def _discover_crates(tree: ast.Module, path: Path) -> dict[str, CrateIR]:
    crates: dict[str, CrateIR] = {}
    for node in tree.body:
        if (
            not isinstance(node, ast.Assign)
            or len(node.targets) != 1
            or not isinstance(node.targets[0], ast.Name)
            or not isinstance(node.value, ast.Call)
            or not _is_rust_attribute(node.value.func)
            or not isinstance(node.value.func, ast.Attribute)
            or node.value.func.attr != "crate"
        ):
            continue
        binding = node.targets[0].id
        if not binding.isidentifier() or keyword.iskeyword(binding):
            _fail(
                "CRAB130",
                "Invalid crate binding",
                f"'{binding}' cannot be represented as a Cargo dependency name.",
                path,
                node.targets[0],
            )
        if (
            len(node.value.args) != 1
            or not isinstance(node.value.args[0], ast.Constant)
            or not isinstance(node.value.args[0].value, str)
        ):
            _fail(
                "CRAB131",
                "Crate name must be static",
                "rust.crate requires one literal package name.",
                path,
                node.value,
            )
        values: dict[str, object] = {}
        for keyword_node in node.value.keywords:
            if keyword_node.arg not in {
                "version",
                "features",
                "path",
                "git",
                "rev",
            }:
                _fail(
                    "CRAB132",
                    "Unsupported crate option",
                    f"rust.crate does not support {keyword_node.arg}.",
                    path,
                    keyword_node,
                )
            values[keyword_node.arg] = _literal_crate_value(
                keyword_node.value,
                path,
            )
        version = values.get("version")
        crate_path = values.get("path")
        git = values.get("git")
        rev = values.get("rev")
        features = values.get("features", ())
        if not all(
            value is None or isinstance(value, str)
            for value in (version, crate_path, git, rev)
        ):
            _fail(
                "CRAB133",
                "Invalid crate option type",
                "version, path, git, and rev must be literal strings.",
                path,
                node.value,
            )
        if not isinstance(features, tuple) or not all(
            isinstance(value, str) for value in features
        ):
            _fail(
                "CRAB133",
                "Invalid crate features",
                "features must be a literal list or tuple of strings.",
                path,
                node.value,
            )
        if sum(value is not None for value in (version, crate_path, git)) != 1:
            _fail(
                "CRAB134",
                "Ambiguous crate source",
                "Declare exactly one of version, path, or git.",
                path,
                node.value,
            )
        if rev is not None and git is None:
            _fail(
                "CRAB135",
                "Crate revision requires Git",
                "rev is valid only with a git dependency.",
                path,
                node.value,
            )
        resolved_path = (
            str((path.parent / crate_path).resolve())
            if isinstance(crate_path, str)
            else None
        )
        crates[binding] = CrateIR(
            binding=binding,
            package=str(node.value.args[0].value),
            version=version if isinstance(version, str) else None,
            features=features,
            path=resolved_path,
            git=git if isinstance(git, str) else None,
            rev=rev if isinstance(rev, str) else None,
            span=SourceSpan.from_ast(path, node),
        )
    return crates


def _literal_crate_value(node: ast.expr, path: Path) -> object:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)) and all(
        isinstance(value, ast.Constant) and isinstance(value.value, str)
        for value in node.elts
    ):
        return tuple(value.value for value in node.elts)
    _fail(
        "CRAB136",
        "Crate options must be static",
        "Use literal strings and literal feature lists in rust.crate.",
        path,
        node,
    )


def _crate_path(
    node: ast.expr,
    crates: dict[str, CrateIR],
    qualified_crates: dict[tuple[str, ...], CrateIR] | None = None,
) -> tuple[str, ...] | None:
    path = _attribute_parts(node)
    if not path:
        return None
    if path[0] in crates:
        return (crates[path[0]].binding, *path[1:])
    qualified_crates = qualified_crates or {}
    for length in range(len(path), 0, -1):
        crate = qualified_crates.get(path[:length])
        if crate is not None:
            return (crate.binding, *path[length:])
    return None


def _assignment_counts(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            counts[child.id] += 1
    for child in ast.walk(node):
        if (
            isinstance(child, ast.AnnAssign)
            and isinstance(child.target, ast.Name)
            and _is_rust_call_named(child.value, "shadow")
        ):
            counts[child.target.id] -= 1
    return counts


def _mutated_receiver_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr
            in {
                "push",
                "pop",
                "push_str",
                "insert",
                "remove",
                "get_mut",
                "entry_or_insert",
                "add",
                "split_at_mut_sum",
                "write_get",
                "shutdown_write",
                "read_to_string",
            }
        ):
            place = _place_from_ast(child.func.value)
            if place is not None:
                names.add(place.root)
        if (
            isinstance(child, ast.Call)
            and _is_rust_call_named(child, "unsafe_write")
            and child.args
        ):
            place = _place_from_ast(child.args[0])
            if place is not None:
                names.add(place.root)
    return names


def _mutably_borrowed_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    signatures: dict[str, _Signature],
) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id in signatures
        ):
            continue
        signature = signatures[child.func.id]
        for argument, parameter in zip(child.args, signature.parameters):
            if parameter.type_ref.ownership == "Mut":
                place = _place_from_ast(argument)
                if place is not None:
                    names.add(place.root)
    return names


def _field_assigned_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, (ast.Assign, ast.AnnAssign)):
            continue
        targets = child.targets if isinstance(child, ast.Assign) else (child.target,)
        for target in targets:
            if not isinstance(target, ast.Attribute):
                continue
            place = _place_from_ast(target.value)
            if place is not None:
                names.add(place.root)
    return names


def _mutably_called_method_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    methods: tuple[_Signature, ...],
) -> set[str]:
    mutable_method_names = {
        method.method_name
        for method in methods
        if method.method_name is not None
        and method.parameters
        and method.parameters[0].type_ref.ownership == "Mut"
    }
    return {
        place.root
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr in mutable_method_names
        for place in (_place_from_ast(child.func.value),)
        if place is not None
    }


def _peek_expression_type(
    node: ast.expr,
    environment: dict[str, TypeRef],
    signatures: dict[str, _Signature],
) -> TypeRef | None:
    if isinstance(node, ast.Name):
        return environment.get(node.id)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        signature = signatures.get(node.func.id)
        return signature.return_type if signature is not None else None
    return None


def _binary_operator(
    node: ast.operator,
    path: Path,
    *,
    expression: ast.AST | None = None,
) -> str:
    operator = _binary_operator_decision(node)
    if operator is None:
        help_text = None
        if isinstance(node, ast.FloorDiv):
            help_text = (
                "Use '/' for Rust typed division; with integer operands it "
                "performs integer division. Verify the result because this "
                "intentionally differs from Python '/'."
            )
        _unsupported(
            expression or node,
            path,
            help_text,
            construct_name=type(node).__name__,
        )
    return operator


def _require_type(
    actual: TypeRef,
    expected: TypeRef,
    path: Path,
    node: ast.AST,
) -> None:
    if actual != expected:
        _fail(
            "CRAB115",
            "Rust type mismatch",
            f"Expected {expected.display()}, found {actual.display()}.",
            path,
            node,
        )


def _contains_generic_type(type_ref: TypeRef) -> bool:
    return type_ref.is_generic or any(
        _contains_generic_type(value) for value in type_ref.arguments
    )


def _substitute_generics(
    type_ref: TypeRef,
    substitutions: dict[str, TypeRef],
) -> TypeRef:
    if type_ref.is_generic:
        return substitutions.get(type_ref.rust_name, type_ref)
    if not type_ref.arguments:
        return type_ref
    return type_ref.with_arguments(
        tuple(
            _substitute_generics(value, substitutions) for value in type_ref.arguments
        )
    )


def _unify_generic_type(
    pattern: TypeRef,
    actual: TypeRef,
    substitutions: dict[str, TypeRef],
    path: Path,
    node: ast.AST,
) -> None:
    if pattern.is_generic:
        existing = substitutions.get(pattern.rust_name)
        if existing is None:
            substitutions[pattern.rust_name] = actual
        else:
            _require_type(actual, existing, path, node)
        return
    if (
        pattern.rust_name != actual.rust_name
        or pattern.const_value != actual.const_value
        or len(pattern.arguments) != len(actual.arguments)
    ):
        _require_type(actual, pattern, path, node)
    for nested_pattern, nested_actual in zip(pattern.arguments, actual.arguments):
        _unify_generic_type(
            nested_pattern,
            nested_actual,
            substitutions,
            path,
            node,
        )


def _require_numeric(type_ref: TypeRef, path: Path, node: ast.AST) -> None:
    if not type_ref.is_numeric:
        _fail(
            "CRAB115",
            "Rust type mismatch",
            f"Expected a numeric Rust type, found {type_ref.display()}.",
            path,
            node,
        )


def _is_copy_semantic_type(type_ref: TypeRef) -> bool:
    return (
        type_ref.is_numeric
        or type_ref.rust_name in {"bool", "char", "Str"}
        or type_ref.ownership == "Ref"
        or (
            type_ref.rust_name == "Option"
            and len(type_ref.arguments) == 1
            and _is_copy_semantic_type(type_ref.arguments[0])
        )
        or (
            type_ref.rust_name == "Result"
            and len(type_ref.arguments) == 2
            and all(_is_copy_semantic_type(value) for value in type_ref.arguments)
        )
        or (
            type_ref.rust_name in {"Tuple", "Array"}
            and all(_is_copy_semantic_type(value) for value in type_ref.arguments)
        )
    )


def _is_clone_semantic_type(type_ref: TypeRef) -> bool:
    return (
        _is_copy_semantic_type(type_ref)
        or type_ref.rust_name == "String"
        or (
            type_ref.rust_name in {"Vec", "Option"}
            and len(type_ref.arguments) == 1
            and _is_clone_semantic_type(type_ref.arguments[0])
        )
        or (
            type_ref.rust_name in {"Tuple", "Array"}
            and all(_is_clone_semantic_type(value) for value in type_ref.arguments)
        )
    )


def _require_integer(type_ref: TypeRef, path: Path, node: ast.AST) -> None:
    if not type_ref.is_integer:
        _fail(
            "CRAB115",
            "Rust type mismatch",
            f"Expected a Rust integer type, found {type_ref.display()}.",
            path,
            node,
        )
