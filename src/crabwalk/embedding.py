"""Public non-executing source-to-native embedding API."""

from __future__ import annotations

import hashlib
import json
import keyword
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic
from crabwalk.inspection import compilation_inspection
from crabwalk.runtime import RustFunction, _bind_compilation_function
from crabwalk.service import CompilationResult, default_service

_MODULE_COMPONENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SNAPSHOT_REPLACE_ATTEMPTS = 20
_SNAPSHOT_REPLACE_INITIAL_DELAY = 0.005
_SNAPSHOT_REPLACE_MAX_DELAY = 0.05


@dataclass(frozen=True, slots=True)
class GeneratedArtifacts:
    """Stable in-memory view of one generated Cargo project."""

    schema_version: int
    rust_source: str
    cargo_manifest: str
    cargo_lock: str | None
    build_script: str
    ir: dict[str, object]
    source_map: dict[str, object]
    build_inputs: dict[str, object]


@dataclass(frozen=True, slots=True)
class CompiledSource:
    """Loaded native callables produced without importing the authored source."""

    _compilation: CompilationResult
    _source_hash: str
    _source_path: Path
    _functions: Mapping[str, RustFunction]

    @property
    def source_hash(self) -> str:
        return self._source_hash

    @property
    def source_path(self) -> Path:
        """The content-addressed source snapshot used for diagnostics and Cargo."""

        return self._source_path

    @property
    def fingerprint(self) -> str:
        return self._compilation.fingerprint

    @property
    def functions(self) -> tuple[str, ...]:
        return tuple(self._functions)

    def function(self, name: str) -> RustFunction:
        """Return one exported native function by its Python source name."""

        if not isinstance(name, str) or not name:
            raise TypeError("function name must be a non-empty string")
        try:
            return self._functions[name]
        except KeyError as error:
            available = ", ".join(self._functions) or "none"
            raise KeyError(
                f"compiled source has no exported function {name!r}; "
                f"available: {available}"
            ) from error

    def inspect(self) -> dict[str, object]:
        """Return the same structured compilation report as `crabwalk inspect`."""

        return compilation_inspection(self._compilation)

    def artifacts(self) -> GeneratedArtifacts:
        """Read generated Rust, Cargo, IR, build-input, and source-map artifacts.

        This is the stable embedding counterpart to ``crabwalk expand``. Callers
        do not need to know generated-directory filenames, and the returned JSON
        values are detached in-memory dictionaries rather than live file handles.
        """

        directory = self._compilation.generated_dir
        lock_path = directory / "Cargo.lock"
        return GeneratedArtifacts(
            schema_version=1,
            rust_source=_read_generated_text(directory / "src" / "lib.rs"),
            cargo_manifest=_read_generated_text(directory / "Cargo.toml"),
            cargo_lock=(
                _read_generated_text(lock_path) if lock_path.is_file() else None
            ),
            build_script=_read_generated_text(directory / "build.rs"),
            ir=_read_generated_json(directory / "crabwalk-ir.json"),
            source_map=_read_generated_json(directory / "crabwalk-source-map.json"),
            build_inputs=_read_generated_json(directory / "crabwalk-build-inputs.json"),
        )


def _read_generated_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(
            f"cannot read generated artifact {path.name}: {error}"
        ) from error


def _read_generated_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(_read_generated_text(path))
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"generated artifact {path.name} is not valid JSON"
        ) from error
    if not isinstance(value, dict):
        raise RuntimeError(f"generated artifact {path.name} must contain a JSON object")
    return value


def compile_source(
    source: str | Mapping[str, str],
    *,
    filename: str = "embedded.py",
    entry: str | None = None,
    module_name: str | None = None,
    cache_directory: str | Path | None = None,
    source_root: str | Path | None = None,
    origin_map: Mapping[int, object] | Mapping[str, Mapping[int, object]] | None = None,
    locked: bool = False,
    offline: bool = False,
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> CompiledSource:
    """Compile source text or a virtual package without executing Python source.

    The source is stored as an immutable, content-addressed UTF-8 snapshot because
    Cargo diagnostics and Crabwalk source maps require a durable filename. Static
    analysis reads that snapshot, and binding occurs directly from semantic IR and
    the loaded native extension; Python top-level statements are never imported or
    executed.

    A mapping is a content-addressed virtual package whose keys are package-relative
    POSIX ``.py`` paths. Missing package initializers are synthesized as empty files,
    so callers can describe namespace-shaped input without mutating ``sys.path``.
    ``entry`` selects the diagnostic/build entry module and defaults to
    ``__init__.py``.

    ``source_root`` preserves the authored base directory for relative path-crate
    declarations while the Python text remains in its immutable snapshot.
    ``origin_map`` attaches opaque host metadata to diagnostics by source line: use
    ``{line: payload}`` for one source string or
    ``{"relative.py": {line: payload}}`` for a virtual package.

    Cancellation is checked between phases and terminates an already-running Cargo
    process tree before returning ``CRAB309``.
    """

    virtual_sources: dict[str, bytes] | None = None
    if isinstance(source, str):
        encoded = _encode_source(source)
        safe_filename = _validated_filename(filename)
        if entry is not None:
            raise ValueError("entry is available only for a virtual source mapping")
        source_hash = hashlib.sha256(encoded).hexdigest()
    elif isinstance(source, Mapping):
        if filename != "embedded.py":
            raise ValueError("filename is unavailable for a virtual source mapping")
        virtual_sources = _validated_sources(source)
        selected_entry = _validated_virtual_path(entry or "__init__.py")
        virtual_sources.setdefault("__init__.py", b"")
        if selected_entry not in virtual_sources:
            raise ValueError(
                f"entry {selected_entry!r} is not present in source mapping"
            )
        source_hash = _virtual_source_hash(virtual_sources)
    else:
        raise TypeError("source must be a string or mapping of .py paths to strings")
    authored_root = _validated_source_root(source_root)
    normalized_origins = _validated_origin_map(
        origin_map,
        filename=safe_filename if virtual_sources is None else None,
        virtual=virtual_sources is not None,
    )
    resolved_module = module_name or f"crabwalk_source_{source_hash[:20]}"
    _validate_module_name(resolved_module)
    root = (
        Path(cache_directory).expanduser().resolve()
        if cache_directory is not None
        else Path(tempfile.gettempdir()).resolve() / "crabwalk-embedded-sources"
    )

    def report(phase: str) -> None:
        if cancelled is not None and cancelled():
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB309",
                    "Compilation cancelled",
                    f"Cancelled before phase: {phase}.",
                    help="Retry when the caller is ready to compile this source revision.",
                )
            )
        if progress is not None:
            progress(phase)

    report("Preparing source snapshot")
    if virtual_sources is None:
        path = _materialize_source(
            root,
            safe_filename,
            source_hash,
            encoded,
        )
        compile_module_name = resolved_module
    else:
        package = _materialize_virtual_package(
            root,
            resolved_module,
            source_hash,
            virtual_sources,
        )
        path = package / selected_entry
        compile_module_name = _virtual_entry_module(resolved_module, selected_entry)
    try:
        compilation = default_service.compile_path(
            path,
            module_name=compile_module_name,
            mode="build",
            load=True,
            locked=locked,
            offline=offline,
            source_root=authored_root,
            progress=report,
            cancelled=cancelled,
        )
    except CrabwalkCompilationError as error:
        raise _attach_external_origins(
            error,
            normalized_origins,
            snapshot_path=path,
            package_root=path.parent if virtual_sources is None else package,
        ) from error
    report("Binding exported native functions")
    exported = [function for function in compilation.ir.functions if function.exported]
    functions = {
        _embedded_function_name(function.module_name, function.name, resolved_module): (
            _bind_compilation_function(compilation, function)
        )
        for function in exported
    }
    return CompiledSource(
        compilation,
        source_hash,
        path,
        MappingProxyType(functions),
    )


def _validated_source_root(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("source_root must name an existing directory")
    return root


def _validated_origin_map(
    value: Mapping[int, object] | Mapping[str, Mapping[int, object]] | None,
    *,
    filename: str | None,
    virtual: bool,
) -> dict[str, dict[int, object]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("origin_map must be a mapping")
    if virtual:
        result: dict[str, dict[int, object]] = {}
        for raw_path, lines in value.items():
            if not isinstance(raw_path, str) or not isinstance(lines, Mapping):
                raise TypeError(
                    "virtual origin_map must map relative .py paths to line mappings"
                )
            path = _validated_virtual_path(raw_path)
            result[path] = _validated_origin_lines(lines)
        return result
    if any(not isinstance(line, int) for line in value):
        raise TypeError("single-source origin_map must map line numbers to payloads")
    assert filename is not None
    lines = {line: payload for line, payload in value.items() if isinstance(line, int)}
    return {filename: _validated_origin_lines(lines)}


def _validated_origin_lines(value: Mapping[int, object]) -> dict[int, object]:
    result: dict[int, object] = {}
    for line, payload in value.items():
        if not isinstance(line, int) or isinstance(line, bool) or line < 1:
            raise ValueError("origin_map line numbers must be positive integers")
        result[line] = payload
    return result


def _attach_external_origins(
    error: CrabwalkCompilationError,
    origins: Mapping[str, Mapping[int, object]],
    *,
    snapshot_path: Path,
    package_root: Path,
) -> CrabwalkCompilationError:
    if not origins:
        return error
    enriched: list[Diagnostic] = []
    resolved_snapshot = snapshot_path.resolve()
    resolved_package = package_root.resolve()
    for diagnostic in error.diagnostics:
        span = diagnostic.span
        origin: object | None = None
        if span is not None:
            span_path = Path(span.path).resolve()
            if span_path == resolved_snapshot and len(origins) == 1:
                source_key = next(iter(origins))
            else:
                try:
                    source_key = span_path.relative_to(resolved_package).as_posix()
                except ValueError:
                    source_key = ""
            origin = origins.get(source_key, {}).get(span.line)
        enriched.append(replace(diagnostic, external_origin=origin))
    return CrabwalkCompilationError(enriched)


def _encode_source(source: str) -> bytes:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    try:
        return normalized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB002",
                "Source is not UTF-8",
                str(error),
                help="Remove lone surrogate code points from the source text.",
            )
        ) from error


def _validated_sources(source: Mapping[str, str]) -> dict[str, bytes]:
    if not source:
        raise ValueError("virtual source mapping must not be empty")
    result: dict[str, bytes] = {}
    for raw_path, text in source.items():
        if not isinstance(raw_path, str) or not isinstance(text, str):
            raise TypeError("virtual source mapping must contain string paths and text")
        path = _validated_virtual_path(raw_path)
        if path in result:
            raise ValueError(f"duplicate normalized virtual source path {path!r}")
        result[path] = _encode_source(text)
        parent = PurePosixPath(path).parent
        while str(parent) != ".":
            initializer = str(parent / "__init__.py")
            result.setdefault(initializer, b"")
            parent = parent.parent
    return result


def _validated_virtual_path(value: str) -> str:
    if not value or "\\" in value:
        raise ValueError("virtual source paths must be non-empty POSIX paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".py":
        raise ValueError("virtual source paths must be contained relative .py paths")
    for index, part in enumerate(path.parts):
        component = Path(part).stem if index == len(path.parts) - 1 else part
        if part == "__init__.py" and index == len(path.parts) - 1:
            continue
        if not _MODULE_COMPONENT.fullmatch(component) or keyword.iskeyword(component):
            raise ValueError(
                f"virtual source component {component!r} is not importable"
            )
    return path.as_posix()


def _virtual_source_hash(sources: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path in sorted(sources):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sources[path])
        digest.update(b"\0")
    return digest.hexdigest()


def _virtual_entry_module(package: str, entry: str) -> str:
    path = PurePosixPath(entry)
    parts = list(path.parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join((package, *parts)) if parts else package


def _embedded_function_name(module: str, name: str, package: str) -> str:
    if module == package:
        return name
    prefix = f"{package}."
    relative = module[len(prefix) :] if module.startswith(prefix) else module
    return f"{relative}.{name}"


def _validated_filename(filename: str) -> str:
    if not isinstance(filename, str) or not filename:
        raise TypeError("filename must be a non-empty string")
    candidate = Path(filename)
    if candidate.name != filename or candidate.suffix.lower() != ".py":
        raise ValueError("filename must be a simple .py filename without directories")
    stem = candidate.stem
    if not _MODULE_COMPONENT.fullmatch(stem) or keyword.iskeyword(stem):
        raise ValueError("filename stem must be a valid non-keyword Python identifier")
    return candidate.name


def _validate_module_name(module_name: str) -> None:
    if not isinstance(module_name, str) or not module_name:
        raise TypeError("module_name must be a non-empty string")
    if any(
        not _MODULE_COMPONENT.fullmatch(part) or keyword.iskeyword(part)
        for part in module_name.split(".")
    ):
        raise ValueError("module_name must be a dotted Python identifier")


def _materialize_source(
    root: Path,
    filename: str,
    source_hash: str,
    encoded: bytes,
) -> Path:
    try:
        root.mkdir(parents=True, exist_ok=True)
        stem = Path(filename).stem
        path = root / f"{stem}-{source_hash[:24]}.py"
        if path.is_file() and path.read_bytes() == encoded:
            return path
        temporary = root / (f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_bytes(encoded)
        _publish_snapshot(temporary, path, encoded)
        return path
    except OSError as error:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB001",
                "Cannot store source snapshot",
                str(error),
                help="Check the embedding cache-directory path and permissions.",
            )
        ) from error
    finally:
        temporary_value = locals().get("temporary")
        if isinstance(temporary_value, Path):
            try:
                temporary_value.unlink(missing_ok=True)
            except OSError:
                pass


def _materialize_virtual_package(
    root: Path,
    module_name: str,
    source_hash: str,
    sources: Mapping[str, bytes],
) -> Path:
    """Atomically materialize a deterministic, immutable virtual package tree."""

    # Keep the snapshot directory deliberately short. Generated Cargo paths are
    # nested below it, and MSVC's linker still encounters legacy path limits in
    # otherwise long temporary-test/user-profile roots.
    del module_name
    package = root / f"v_{source_hash[:16]}"
    try:
        package.mkdir(parents=True, exist_ok=True)
        for relative, payload in sorted(sources.items()):
            destination = package.joinpath(*PurePosixPath(relative).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_file() and destination.read_bytes() == payload:
                continue
            temporary = destination.with_name(
                f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            temporary.write_bytes(payload)
            _publish_snapshot(temporary, destination, payload)
        return package
    except OSError as error:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB001",
                "Cannot store virtual source package",
                str(error),
                help="Check the embedding cache-directory path and permissions.",
            )
        ) from error
    finally:
        temporary_value = locals().get("temporary")
        if isinstance(temporary_value, Path):
            try:
                temporary_value.unlink(missing_ok=True)
            except OSError:
                pass


def _publish_snapshot(temporary: Path, destination: Path, payload: bytes) -> None:
    """Publish immutable source bytes despite transient Windows sharing violations.

    Snapshot paths are content-addressed, so another process publishing the exact
    same bytes is a successful outcome. Windows file watchers and antivirus tools
    can briefly deny ``os.replace`` even when no writer owns the destination; keep
    that retry bounded and never suppress a different I/O failure.
    """

    delay = _SNAPSHOT_REPLACE_INITIAL_DELAY
    for attempt in range(_SNAPSHOT_REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            try:
                if destination.is_file() and destination.read_bytes() == payload:
                    temporary.unlink(missing_ok=True)
                    return
            except OSError:
                pass
            if attempt + 1 == _SNAPSHOT_REPLACE_ATTEMPTS:
                raise
            time.sleep(delay)
            delay = min(delay * 2, _SNAPSHOT_REPLACE_MAX_DELAY)
