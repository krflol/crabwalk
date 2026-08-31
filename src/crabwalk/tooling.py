"""Stable developer-tooling contracts shared by the CLI and editor adapters."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic
from crabwalk.service import CompilationResult

DIAGNOSTIC_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class DiagnosticExplanation:
    code: str
    family: str
    summary: str
    next_step: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "family": self.family,
            "summary": self.summary,
            "next_step": self.next_step,
        }


_EXPLANATIONS = {
    "CRAB102": DiagnosticExplanation(
        "CRAB102",
        "language subset",
        "The source uses Python syntax or an operation Crabwalk has not modeled.",
        "Use the help text at the source span or inspect the capability table for the supported typed form.",
    ),
    "CRAB192": DiagnosticExplanation(
        "CRAB192",
        "patterns",
        "A match pattern cannot be represented with Rust's supported pattern semantics.",
        "Use typed literals/constructors and keep range endpoints to matching integer or char literals.",
    ),
    "CRAB203": DiagnosticExplanation(
        "CRAB203",
        "effects",
        "Project policy denied a compiled function that reaches the Python runtime.",
        "Remove the Python call or change [tool.crabwalk].python-boundaries deliberately.",
    ),
    "CRAB220": DiagnosticExplanation(
        "CRAB220",
        "iterators",
        "An iterator item or adapter combination is outside the typed iterator contract.",
        "Inspect item ownership/execution/indexing and use a supported adapter order.",
    ),
    "CRAB225": DiagnosticExplanation(
        "CRAB225",
        "parallel iterators",
        "A Rayon operation requires indexed parallel iteration after an adapter removed it.",
        "Move enumerate/zip before filter-like adapters or use an unindexed terminal operation.",
    ),
    "CRAB226": DiagnosticExplanation(
        "CRAB226",
        "opaque storage",
        "An anonymous Rust adapter/future local cannot change its concrete storage type by assignment.",
        "Bind the transformed value to a new local or use explicit shadowing.",
    ),
    "CRAB236": DiagnosticExplanation(
        "CRAB236",
        "GIL policy",
        "An explicit audited GIL-release request is invalid for this function.",
        "Keep Python and call-scoped borrows outside the detached call, or remove release_gil=True.",
    ),
    "CRAB237": DiagnosticExplanation(
        "CRAB237",
        "Python ABI",
        "A direct Python boundary contains a tuple larger than PyO3 can convert.",
        "Use at most 12 items, a generated domain type, or nested smaller tuples.",
    ),
    "CRAB301": DiagnosticExplanation(
        "CRAB301",
        "rustc",
        "rustc rejected the generated crate.",
        "Read the mapped source span, then use crabwalk show/export-rust for the exact generated Rust.",
    ),
    "CRAB309": DiagnosticExplanation(
        "CRAB309",
        "build lifecycle",
        "Compilation was cancelled and any active Cargo process tree was terminated.",
        "Retry when the source revision is still current.",
    ),
    "CRAB401": DiagnosticExplanation(
        "CRAB401",
        "native loading",
        "Python could not load the compiled or prebuilt native extension.",
        "Run crabwalk doctor and inspect ABI, platform, manifest, and artifact integrity details.",
    ),
    "CRAB511": DiagnosticExplanation(
        "CRAB511",
        "packaging",
        "The PEP 517 application project contract is incomplete or inconsistent.",
        "Validate [project], [build-system], and [tool.crabwalk] package metadata.",
    ),
}


def explain_diagnostic(code: str) -> DiagnosticExplanation | None:
    return _EXPLANATIONS.get(code.strip().upper())


def diagnostic_document(
    diagnostics: tuple[Diagnostic, ...],
    *,
    operation: str,
) -> dict[str, object]:
    """Return the versioned, machine-readable diagnostic stream envelope."""

    return {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "operation": operation,
        "ok": False,
        "diagnostics": [diagnostic_to_dict(value) for value in diagnostics],
    }


def diagnostic_to_dict(diagnostic: Diagnostic) -> dict[str, object]:
    return {
        "code": diagnostic.code,
        "title": diagnostic.title,
        "message": diagnostic.message,
        "span": diagnostic.span.to_dict() if diagnostic.span is not None else None,
        "help": diagnostic.help,
        "rustc_code": diagnostic.rustc_code,
        "detail": diagnostic.detail,
        "external_origin": diagnostic.external_origin,
    }


def export_generated_project(
    result: CompilationResult,
    destination: str | Path,
) -> Path:
    """Copy the exact generated crate and provenance files without cache layout."""

    target = Path(destination).resolve()
    if target.exists() and any(target.iterdir()):
        _fail(
            "CRAB310",
            "Rust export destination is not empty",
            str(target),
        )
    target.mkdir(parents=True, exist_ok=True)
    required = (
        "Cargo.toml",
        "Cargo.lock",
        "build.rs",
        "crabwalk-ir.json",
        "crabwalk-source-map.json",
        "crabwalk-build-inputs.json",
        "src/lib.rs",
    )
    for relative in required:
        source = result.generated_dir / relative
        if not source.is_file():
            _fail(
                "CRAB310",
                "Generated Rust export is incomplete",
                f"Missing {source}.",
            )
        destination_path = target / relative
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination_path)
    manifest = {
        "schema_version": 1,
        "module": result.ir.module_name,
        "fingerprint": result.fingerprint,
        "compiler_input_hash": result.ir.compiler_input_hash,
        "files": list(required),
    }
    (target / "crabwalk-export.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


def _fail(code: str, title: str, message: str) -> NoReturn:
    raise CrabwalkCompilationError(Diagnostic(code, title, message))
