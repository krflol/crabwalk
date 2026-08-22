"""One orchestration path for CLI, decorators, builds, and inspection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sysconfig
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Literal

from crabwalk.build.cache import (
    ArtifactCacheInfo,
    FileLock,
    artifact_cache_info,
    sha256_file,
    write_json,
    write_text,
)
from crabwalk.build.cargo import CargoBuildFailure, CargoBuilder
from crabwalk.build.fingerprint import build_fingerprint
from crabwalk.build.loader import load_extension
from crabwalk.compiler.codegen import GeneratedProject, generate_project
from crabwalk.compiler.frontend import analyze_project_path
from crabwalk.config import discover_project_config
from crabwalk.compiler.ir import PackageIR
from crabwalk.diagnostics import (
    CrabwalkCompilationError,
    Diagnostic,
    SourceSpan,
    sanitize_external_text,
)

CompilationMode = Literal["expand", "check", "build"]


@dataclass(frozen=True, slots=True)
class CompilationResult:
    ir: PackageIR
    fingerprint: str
    extension_name: str
    project_root: Path
    generated_dir: Path
    artifact: Path | None
    cache_hit: bool
    module: ModuleType | None
    command: tuple[str, ...] | None
    cache_status: str = "not-checked"
    cached_artifact: Path | None = None
    build_inputs: dict[str, object] | None = None
    planned_command: tuple[str, ...] | None = None


class CompilationService:
    def __init__(self, cargo: CargoBuilder | None = None):
        self.cargo = cargo or CargoBuilder()

    def compile_path(
        self,
        path: str | Path,
        *,
        module_name: str | None = None,
        mode: CompilationMode = "build",
        load: bool = False,
        locked: bool = False,
        offline: bool = False,
        project: str | Path | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> CompilationResult:
        report = progress or (lambda _phase: None)
        report("Analyzing Python source")
        requested_path = Path(path).resolve()
        config = discover_project_config(requested_path, project)
        source_path = (
            config.resolve_entry(requested_path)
            if config is not None
            else requested_path
        )
        ir = analyze_project_path(source_path, module_name)
        if config is not None and config.python_boundaries == "deny":
            boundary = next(
                (function for function in ir.functions if function.python_boundary),
                None,
            )
            if boundary is not None:
                raise CrabwalkCompilationError(
                    Diagnostic(
                        "CRAB203",
                        "Python runtime boundary denied by project policy",
                        f"{boundary.qualified_name} reaches a Python runtime operation.",
                        boundary.span,
                        "Remove the boundary or set python-boundaries to 'allow' or 'warn'.",
                    )
                )
        elif config is not None and config.python_boundaries == "warn":
            boundary_names = [
                function.qualified_name
                for function in ir.functions
                if function.python_boundary
            ]
            if boundary_names:
                warnings.warn(
                    "Crabwalk Python runtime boundaries: " + ", ".join(boundary_names),
                    UserWarning,
                    stacklevel=2,
                )
        canonical_source_path = Path(ir.source_path)
        root = (
            config.root
            if config is not None
            else _find_project_root(canonical_source_path)
        )
        dependency_lock = _dependency_lock_path(root, canonical_source_path)
        state_root = root / ".crabwalk"
        if ir.crates and locked and not dependency_lock.is_file():
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB304",
                    "Locked build has no dependency lock",
                    f"Expected {dependency_lock}.",
                    _primary_span(ir),
                    "Run one unlocked build to resolve and persist Cargo.lock.",
                )
            )
        if ir.crates and not dependency_lock.is_file():
            report("Resolving Cargo dependencies")
            self._bootstrap_dependency_lock(
                ir,
                dependency_lock,
                state_root,
                offline=offline,
            )
        dependency_lock_hash = (
            sha256_file(dependency_lock)
            if ir.crates and dependency_lock.is_file()
            else None
        )
        report("Fingerprinting build inputs")
        effective_locked = bool(ir.crates and dependency_lock_hash)
        fingerprint, inputs = build_fingerprint(
            ir,
            dependency_lock_hash,
            locked=effective_locked,
            offline=offline,
            project_config_hash=config.content_hash if config is not None else None,
        )
        extension_name = _extension_name(ir.module_name, fingerprint)
        generated = generate_project(ir, extension_name)
        generated_dir = (
            state_root / "generated" / _safe_component(ir.module_name) / fingerprint
        )
        target_dir = state_root / "target"
        lock_path = state_root / "locks" / f"{fingerprint}.lock"
        suffix = sysconfig.get_config_var("EXT_SUFFIX")
        if not suffix:
            suffix = ".pyd" if os.name == "nt" else ".so"
        planned_command = self.cargo.command_for(
            target_dir,
            "build",
            locked=effective_locked,
            offline=offline,
        )

        artifact: Path | None = None
        cache_hit = False
        cache: ArtifactCacheInfo | None = None
        command: tuple[str, ...] | None = None
        source_map = generated.source_map

        report("Waiting for the build lock")
        with FileLock(lock_path):
            _write_generated(generated_dir, generated, inputs, fingerprint)
            report("Checking the native artifact cache")
            cache = artifact_cache_info(
                state_root,
                fingerprint,
                extension_name,
                suffix,
            )
            cache_hit = cache.status == "hit"
            if ir.crates and dependency_lock.is_file():
                shutil.copy2(dependency_lock, generated_dir / "Cargo.lock")
            if mode == "check":
                report("Checking generated Rust with Cargo")
                try:
                    outcome = self.cargo.run(
                        generated_dir,
                        target_dir,
                        extension_name,
                        "check",
                        locked=effective_locked,
                        offline=offline,
                    )
                    command = outcome.command
                    _persist_dependency_lock(ir, generated_dir, dependency_lock)
                except CargoBuildFailure as error:
                    raise _cargo_diagnostics(error, source_map, ir) from error
            elif mode == "build":
                artifact = cache.artifact
                cache_dir = artifact.parent
                manifest_path = cache.manifest
                if not cache_hit:
                    report("Compiling the Rust extension")
                    try:
                        outcome = self.cargo.run(
                            generated_dir,
                            target_dir,
                            extension_name,
                            "build",
                            locked=effective_locked,
                            offline=offline,
                        )
                        command = outcome.command
                        _persist_dependency_lock(ir, generated_dir, dependency_lock)
                    except CargoBuildFailure as error:
                        raise _cargo_diagnostics(error, source_map, ir) from error
                    if outcome.artifact is None:
                        raise AssertionError("Cargo build returned no artifact")
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    temporary = cache_dir / f".{artifact.name}.{os.getpid()}.tmp"
                    shutil.copy2(outcome.artifact, temporary)
                    os.replace(temporary, artifact)
                    write_json(
                        manifest_path,
                        {
                            "schema_version": 1,
                            "fingerprint": fingerprint,
                            "extension_name": extension_name,
                            "artifact": artifact.name,
                            "artifact_sha256": sha256_file(artifact),
                            "source_hash": ir.source_hash,
                        },
                    )
                else:
                    report("Using the cached native extension")

        loaded: ModuleType | None = None
        if load:
            if mode != "build" or artifact is None:
                raise ValueError("loading requires build mode")
            report("Loading the native extension")
            try:
                loaded = load_extension(extension_name, artifact)
            except (ImportError, OSError) as error:
                raise CrabwalkCompilationError(
                    Diagnostic(
                        "CRAB401",
                        "Native extension load failed",
                        str(error),
                        _primary_span(ir),
                        "Run crabwalk doctor and inspect the generated artifact ABI.",
                    )
                ) from error

        return CompilationResult(
            ir=ir,
            fingerprint=fingerprint,
            extension_name=extension_name,
            project_root=root,
            generated_dir=generated_dir,
            artifact=artifact,
            cache_hit=cache_hit,
            module=loaded,
            command=command,
            cache_status=cache.status if cache is not None else "not-checked",
            cached_artifact=(
                cache.artifact if cache is not None and cache.status == "hit" else None
            ),
            build_inputs=inputs,
            planned_command=planned_command,
        )

    def _bootstrap_dependency_lock(
        self,
        ir: PackageIR,
        destination: Path,
        state_root: Path,
        *,
        offline: bool,
    ) -> None:
        manifest_key = _dependency_manifest_key(ir)
        bootstrap_dir = (
            state_root
            / "lock-bootstrap"
            / _safe_component(ir.module_name)
            / manifest_key
        )
        lock_path = state_root / "locks" / f"dependency-{manifest_key}.lock"
        with FileLock(lock_path):
            if destination.is_file():
                return
            generated = generate_project(ir, "_crabwalk_lock_bootstrap")
            write_text(bootstrap_dir / "Cargo.toml", generated.cargo_toml)
            write_text(bootstrap_dir / "src" / "lib.rs", generated.rust_source)
            try:
                self.cargo.generate_lockfile(bootstrap_dir, offline=offline)
            except CargoBuildFailure as error:
                raise _dependency_diagnostics(error, ir) from error
            _persist_dependency_lock(ir, bootstrap_dir, destination)


def _write_generated(
    directory: Path,
    generated: GeneratedProject,
    inputs: dict[str, object],
    fingerprint: str,
) -> None:
    write_text(directory / "Cargo.toml", generated.cargo_toml)
    write_text(directory / "src" / "lib.rs", generated.rust_source)
    write_text(directory / "crabwalk-ir.json", generated.ir_json)
    write_json(directory / "crabwalk-source-map.json", generated.source_map)
    write_json(
        directory / "crabwalk-build-inputs.json",
        {"fingerprint": fingerprint, "inputs": inputs},
    )


def _persist_dependency_lock(
    ir: PackageIR,
    generated_dir: Path,
    destination: Path,
) -> None:
    if not ir.crates:
        return
    source = generated_dir / "Cargo.lock"
    if not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def find_project_root(path: str | Path) -> Path:
    path = Path(path).resolve()
    start = path if path.is_dir() else path.parent
    for directory in (start, *start.parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    return start


def _find_project_root(path: Path) -> Path:
    return find_project_root(path)


def _dependency_lock_path(root: Path, source_path: Path) -> Path:
    try:
        relative = source_path.relative_to(root)
    except ValueError:
        relative = Path(source_path.name)
    return root / "crabwalk-locks" / relative.parent / f"{relative.stem}.Cargo.lock"


def _safe_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return safe or "module"


def _dependency_manifest_key(ir: PackageIR) -> str:
    payload = [
        {
            "binding": crate.binding,
            "package": crate.package,
            "version": crate.version,
            "features": crate.features,
            "path": crate.path,
            "git": crate.git,
            "rev": crate.rev,
        }
        for crate in sorted(ir.crates, key=lambda value: value.binding)
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _extension_name(module_name: str, fingerprint: str) -> str:
    return f"_crabwalk_{_safe_component(module_name)}_{fingerprint[:16]}"


def _primary_span(ir: PackageIR) -> SourceSpan | None:
    if ir.functions:
        return ir.functions[0].span
    if ir.structs:
        return ir.structs[0].span
    if ir.enums:
        return ir.enums[0].span
    return None


def _cargo_diagnostics(
    error: CargoBuildFailure,
    source_map: dict[str, object],
    ir: PackageIR,
) -> CrabwalkCompilationError:
    mapped = _line_map(source_map)
    diagnostics: list[Diagnostic] = []
    for event in error.messages:
        if event.get("reason") != "compiler-message":
            continue
        message = event.get("message")
        if not isinstance(message, dict) or message.get("level") != "error":
            continue
        rustc_code_value = message.get("code")
        rustc_code = (
            str(rustc_code_value.get("code"))
            if isinstance(rustc_code_value, dict) and rustc_code_value.get("code")
            else None
        )
        span = _mapped_span(message, mapped) or _primary_span(ir)
        diagnostics.append(
            Diagnostic(
                "CRAB301",
                "Rust compilation failed",
                sanitize_external_text(
                    str(message.get("message", "rustc rejected generated Rust."))
                ),
                span,
                "Inspect the generated Rust with crabwalk expand.",
                rustc_code,
                sanitize_external_text(str(message.get("rendered") or "")).rstrip()
                or None,
            )
        )
    if not diagnostics:
        detail = sanitize_external_text(
            error.stderr.strip() or error.stdout.strip() or str(error)
        )
        diagnostics.append(
            Diagnostic(
                "CRAB300",
                "Cargo build failed",
                "Cargo could not build the generated Crabwalk extension.",
                _primary_span(ir),
                "Run crabwalk doctor and inspect the generated Cargo project.",
                detail=detail,
            )
        )
    return CrabwalkCompilationError(diagnostics)


def _dependency_diagnostics(
    error: CargoBuildFailure,
    ir: PackageIR,
) -> CrabwalkCompilationError:
    detail = sanitize_external_text(
        error.stderr.strip() or error.stdout.strip() or str(error)
    )
    span = ir.crates[0].span if ir.crates else _primary_span(ir)
    return CrabwalkCompilationError(
        Diagnostic(
            "CRAB302",
            "Cargo dependency resolution failed",
            "Cargo could not resolve the declared Rust dependencies.",
            span,
            "Check the rust.crate source, version, path, revision, and feature names.",
            detail=detail,
        )
    )


def _line_map(source_map: dict[str, object]) -> dict[int, SourceSpan]:
    result: dict[int, SourceSpan] = {}
    entries = source_map.get("entries")
    if not isinstance(entries, list):
        return result
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        line = entry.get("generated_line")
        source = entry.get("source")
        if isinstance(line, int) and isinstance(source, dict):
            try:
                result[line] = SourceSpan.from_dict(source)
            except (KeyError, TypeError, ValueError):
                continue
    return result


def _mapped_span(
    message: dict[str, object],
    line_map: dict[int, SourceSpan],
) -> SourceSpan | None:
    spans = message.get("spans")
    if not isinstance(spans, list):
        return None
    ordered = sorted(
        (span for span in spans if isinstance(span, dict)),
        key=lambda value: not bool(value.get("is_primary")),
    )
    for span in ordered:
        line = span.get("line_start")
        if isinstance(line, int) and line in line_map:
            return line_map[line]
    return None


default_service = CompilationService()
