"""Stable, machine-readable descriptions of compiled Crabwalk programs."""

from __future__ import annotations

import os
import sysconfig
from dataclasses import fields, is_dataclass
from typing import Iterator

from crabwalk.build.cache import artifact_cache_info
from crabwalk.compiler.codegen import function_releases_gil
from crabwalk.compiler.ir import (
    CallIR,
    CrateCallIR,
    FunctionIR,
    NativePrintlnIR,
    PythonPrintIR,
    TypeRef,
    UNIT,
)
from crabwalk.diagnostics import SourceSpan
from crabwalk.service import CompilationResult


def compilation_inspection(result: CompilationResult) -> dict[str, object]:
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if not suffix:
        suffix = ".pyd" if os.name == "nt" else ".so"
    cache = artifact_cache_info(
        result.project_root / ".crabwalk",
        result.fingerprint,
        result.extension_name,
        suffix,
    )
    return {
        "schema_version": 2,
        "module": result.ir.module_name,
        "source_hash": result.ir.source_hash,
        "compiler_input_hash": result.ir.compiler_input_hash,
        "wheel_source_integrity_hash": result.ir.wheel_source_integrity_hash,
        "source_files": list(result.ir.source_paths or (result.ir.source_path,)),
        "fingerprint": result.fingerprint,
        "extension_name": result.extension_name,
        "generated_dir": str(result.generated_dir),
        "cache": {
            "status": cache.status,
            "artifact": str(cache.artifact),
            "size": cache.size,
            "reason": cache.reason,
        },
        "build_command": list(result.planned_command or ()),
        "build_inputs": result.build_inputs or {},
        "cargo_policy": _cargo_policy(result),
        "crates": [
            {
                "binding": crate.binding,
                "package": crate.package,
                "version": crate.version,
                "features": list(crate.features),
                "path": crate.path,
                "git": crate.git,
                "rev": crate.rev,
            }
            for crate in result.ir.crates
        ],
        "structs": [
            {
                "name": struct.qualified_name,
                "native_symbol": struct.symbol,
                "derives": ["::".join(value) for value in struct.derives],
                "fields": [
                    {"name": field.name, "type": field.type_ref.display()}
                    for field in struct.fields
                ],
                "source": struct.span.to_dict(),
            }
            for struct in result.ir.structs
        ],
        "enums": [
            {
                "name": enum.qualified_name,
                "native_symbol": enum.symbol,
                "derives": ["::".join(value) for value in enum.derives],
                "variants": [
                    {
                        "name": variant.name,
                        "tuple_style": variant.tuple_style,
                        "fields": [
                            {"name": field.name, "type": field.type_ref.display()}
                            for field in variant.fields
                        ],
                    }
                    for variant in enum.variants
                ],
                "source": enum.span.to_dict(),
            }
            for enum in result.ir.enums
        ],
        "functions": [
            function_inspection(function) for function in result.ir.functions
        ],
    }


def _cargo_policy(result: CompilationResult) -> dict[str, object]:
    inputs = result.build_inputs or {}
    policy = inputs.get("cargo_policy")
    if isinstance(policy, dict):
        return {
            "locked": bool(policy.get("locked", False)),
            "offline": bool(policy.get("offline", False)),
        }
    return {"locked": None, "offline": None}


def function_inspection(function: FunctionIR) -> dict[str, object]:
    python_calls: list[dict[str, object]] = []
    native_calls: list[dict[str, object]] = []
    for value in _walk(function.body):
        if isinstance(value, PythonPrintIR):
            python_calls.append({"name": "print", "source": value.span.to_dict()})
        elif isinstance(value, NativePrintlnIR):
            native_calls.append(
                {"name": "rust.println", "source": value.span.to_dict()}
            )
        elif isinstance(value, CallIR):
            native_calls.append({"name": value.target, "source": value.span.to_dict()})
        elif isinstance(value, CrateCallIR):
            native_calls.append(
                {
                    "name": "::".join(value.path),
                    "adapter": value.adapter_name,
                    "declared_effects": (
                        [effect.value for effect in value.declared_effects]
                        if value.declared_effects is not None
                        else None
                    ),
                    "source": value.span.to_dict(),
                }
            )

    parameters = [
        {
            "name": parameter.name,
            "type": parameter.type_ref.display(),
            "rust_type": parameter.type_ref.render(),
            "mutable": parameter.mutable,
            "ownership": parameter.type_ref.ownership,
            "conversion": _input_conversion(parameter.type_ref),
        }
        for parameter in function.parameters
    ]
    return_conversion = _return_conversion(function.return_type)
    if function_releases_gil(function):
        gil = "released during the native call"
    elif function.python_boundary:
        gil = "held or reacquired for Python runtime operations"
    elif any(
        parameter.type_ref.ownership is not None for parameter in function.parameters
    ):
        gil = "held while call-scoped Rust ownership guards are active"
    else:
        gil = "held for ABI conversion or borrowed input lifetime"
    return {
        "name": function.qualified_name,
        "module": function.module_name,
        "native_symbol": function.rust_symbol,
        "source": function.span.to_dict(),
        "parameters": parameters,
        "return_type": function.return_type.display(),
        "return_rust_type": function.return_type.render(),
        "return_conversion": return_conversion,
        "effects": list(function.effects),
        "classification": (
            "Python runtime boundary" if function.python_boundary else "Native Rust"
        ),
        "gil": gil,
        "python_calls": python_calls,
        "native_calls": native_calls,
    }


def _input_conversion(type_ref: TypeRef) -> dict[str, str]:
    ownership = type_ref.ownership
    if ownership == "Owned":
        return {
            "kind": "state transfer",
            "cost": "no deep copy",
            "detail": "move a Rust-owned handle into the native call",
        }
    if ownership == "Ref":
        return {
            "kind": "call-scoped borrow",
            "cost": "no deep copy",
            "detail": "shared borrow of a Rust-owned handle",
        }
    if ownership == "Mut":
        return {
            "kind": "call-scoped mutable borrow",
            "cost": "no deep copy",
            "detail": "exclusive borrow of a Rust-owned handle",
        }
    if type_ref.is_integer:
        return {
            "kind": "checked conversion",
            "cost": "constant",
            "detail": f"exact Python int range check for {type_ref.render()}",
        }
    if type_ref.is_float:
        return {
            "kind": "checked conversion",
            "cost": "constant",
            "detail": f"Python int/float conversion to {type_ref.render()}",
        }
    if type_ref.rust_name == "bool":
        return {
            "kind": "checked conversion",
            "cost": "constant",
            "detail": "exact Python bool conversion",
        }
    if type_ref.rust_name == "Str":
        return {
            "kind": "borrowed conversion",
            "cost": "UTF-8 validation; no retained copy",
            "detail": "Python str borrowed for this call only",
        }
    if type_ref.rust_name == "String":
        return {
            "kind": "allocating conversion",
            "cost": "linear in UTF-8 length",
            "detail": "Python str copied into Rust String",
        }
    if type_ref.rust_name == "Option":
        nested = _input_conversion(type_ref.arguments[0])
        return {
            "kind": "optional conversion",
            "cost": nested["cost"],
            "detail": f"None or {nested['detail']}",
        }
    return {
        "kind": "ABI conversion",
        "cost": "type-dependent",
        "detail": type_ref.display(),
    }


def _return_conversion(type_ref: TypeRef) -> dict[str, str]:
    if type_ref == UNIT:
        return {"kind": "unit", "cost": "constant", "detail": "Rust () to None"}
    if type_ref.rust_name == "String":
        return {
            "kind": "allocating conversion",
            "cost": "linear in UTF-8 length",
            "detail": "Rust String copied into Python str",
        }
    if type_ref.rust_name == "Option":
        nested = _return_conversion(type_ref.arguments[0])
        return {
            "kind": "optional conversion",
            "cost": nested["cost"],
            "detail": f"None or {nested['detail']}",
        }
    if type_ref.rust_name == "Result":
        nested = _return_conversion(type_ref.arguments[0])
        return {
            "kind": "result conversion",
            "cost": nested["cost"],
            "detail": (
                f"Ok uses {nested['detail']}; Err becomes CrabwalkRustError "
                f"labelled {type_ref.arguments[1].display()}"
            ),
        }
    return {
        "kind": "exact conversion",
        "cost": "constant",
        "detail": f"Rust {type_ref.render()} to Python scalar",
    }


def _walk(value: object) -> Iterator[object]:
    if isinstance(
        value, (str, bytes, int, float, bool, type(None), SourceSpan, TypeRef)
    ):
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            yield from _walk(item)
        return
    yield value
    if is_dataclass(value):
        for field in fields(value):
            yield from _walk(getattr(value, field.name))
