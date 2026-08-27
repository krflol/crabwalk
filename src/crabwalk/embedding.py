"""Public non-executing source-to-native embedding API."""

from __future__ import annotations

import hashlib
import keyword
import os
import re
import tempfile
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic
from crabwalk.inspection import compilation_inspection
from crabwalk.runtime import RustFunction, _bind_compilation_function
from crabwalk.service import CompilationResult, default_service

_MODULE_COMPONENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def compile_source(
    source: str,
    *,
    filename: str = "embedded.py",
    module_name: str | None = None,
    cache_directory: str | Path | None = None,
    locked: bool = False,
    offline: bool = False,
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> CompiledSource:
    """Compile source text and bind exports without executing the Python module.

    The source is stored as an immutable, content-addressed UTF-8 snapshot because
    Cargo diagnostics and Crabwalk source maps require a durable filename. Static
    analysis reads that snapshot, and binding occurs directly from semantic IR and
    the loaded native extension; Python top-level statements are never imported or
    executed.

    Cancellation is cooperative between compiler/build phases. It cannot preempt a
    Cargo process that is already running.
    """

    if not isinstance(source, str):
        raise TypeError("source must be a string")
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    try:
        encoded = normalized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise CrabwalkCompilationError(
            Diagnostic(
                "CRAB002",
                "Source is not UTF-8",
                str(error),
                help="Remove lone surrogate code points from the source text.",
            )
        ) from error

    safe_filename = _validated_filename(filename)
    source_hash = hashlib.sha256(encoded).hexdigest()
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
    path = _materialize_source(
        root,
        safe_filename,
        source_hash,
        encoded,
    )
    compilation = default_service.compile_path(
        path,
        module_name=resolved_module,
        mode="build",
        load=True,
        locked=locked,
        offline=offline,
        progress=report,
    )
    report("Binding exported native functions")
    functions = {
        function.name: _bind_compilation_function(compilation, function)
        for function in compilation.ir.functions
        if function.exported
    }
    return CompiledSource(
        compilation,
        source_hash,
        path,
        MappingProxyType(functions),
    )


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
        os.replace(temporary, path)
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
