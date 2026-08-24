"""Filesystem package discovery and native-source reachability.

This pass intentionally precedes semantic lowering.  It identifies source that
can affect generated Rust while retaining a separate integrity identity for all
Python source shipped in a mixed wheel.
"""

from __future__ import annotations

import ast
import hashlib
import io
import tokenize
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic, SourceSpan

_CRABWALK_DECLARATION_MEMBERS = frozenset(
    {
        "async_fn",
        "crate",
        "enum",
        "fn",
        "generic",
        "impl",
        "method",
        "operator",
        "struct",
        "trait",
        "typevar",
    }
)


@dataclass(frozen=True, slots=True)
class PackageSourceGraph:
    """The native compiler closure and complete wheel-source inventory."""

    compiler_paths: tuple[Path, ...]
    wheel_source_paths: tuple[Path, ...]
    compiler_input_hash: str
    wheel_source_integrity_hash: str


def discover_package_source_graph(
    package_root: Path,
    package_name: str,
    entry_path: Path,
) -> PackageSourceGraph:
    """Discover package files that participate in native compilation."""

    python_paths = _package_python_paths(package_root)
    modules = {
        _module_name(package_root, package_name, path): path for path in python_paths
    }
    paths_to_modules = {path: name for name, path in modules.items()}
    roots = {package_name}
    resolved_entry = entry_path / "__init__.py" if entry_path.is_dir() else entry_path
    entry_module = paths_to_modules.get(resolved_entry.resolve())
    if entry_module is not None:
        roots.add(entry_module)
    for name, path in modules.items():
        if _source_may_define_crabwalk(path.read_bytes()):
            roots.add(name)

    reachable: set[str] = set()
    pending: deque[str] = deque()

    def enqueue(target: str) -> None:
        parts = target.split(".")
        for length in range(1, len(parts) + 1):
            candidate = ".".join(parts[:length])
            if candidate in modules and candidate not in reachable:
                reachable.add(candidate)
                pending.append(candidate)

    for root in sorted(roots):
        enqueue(root)

    while pending:
        name = pending.popleft()
        path = modules[name]
        tree = _parse_for_imports(path)
        is_package = path.name == "__init__.py"
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                source = _resolve_import_from(name, is_package, node)
                if source in modules:
                    enqueue(source)
                if source is None:
                    continue
                for alias in node.names:
                    child = f"{source}.{alias.name}"
                    if child in modules:
                        enqueue(child)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in modules:
                        enqueue(alias.name)

    compiler_paths = tuple(modules[name] for name in sorted(reachable))
    wheel_paths = _wheel_python_paths(package_root)
    return PackageSourceGraph(
        compiler_paths=compiler_paths,
        wheel_source_paths=wheel_paths,
        compiler_input_hash=_hash_paths(package_root, compiler_paths),
        wheel_source_integrity_hash=_hash_paths(package_root, wheel_paths),
    )


def single_file_source_graph(path: Path) -> PackageSourceGraph:
    resolved = path.resolve()
    digest = _hash_paths(resolved.parent, (resolved,))
    return PackageSourceGraph((resolved,), (resolved,), digest, digest)


def package_python_paths(package_root: Path) -> tuple[Path, ...]:
    """Return ordinary package modules in deterministic relative-path order."""

    return _package_python_paths(package_root)


def _package_python_paths(package_root: Path) -> tuple[Path, ...]:
    paths = [
        path.resolve()
        for path in package_root.rglob("*.py")
        if not any(
            part.startswith(".") or part == "__pycache__"
            for part in path.relative_to(package_root).parts[:-1]
        )
    ]
    return tuple(
        sorted(paths, key=lambda value: value.relative_to(package_root).as_posix())
    )


def _wheel_python_paths(package_root: Path) -> tuple[Path, ...]:
    paths = [
        path.resolve()
        for path in package_root.rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".pyi"}
        and not any(
            part.startswith(".") or part == "__pycache__"
            for part in path.relative_to(package_root).parts[:-1]
        )
    ]
    return tuple(
        sorted(paths, key=lambda value: value.relative_to(package_root).as_posix())
    )


def _module_name(package_root: Path, package_name: str, path: Path) -> str:
    relative = path.relative_to(package_root)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join((package_name, *parts)) if parts else package_name


def _source_may_define_crabwalk(source: bytes) -> bool:
    """Find ``rust.<declaration>`` tokens without parsing unrelated modules."""

    significant: list[tuple[int, str]] = []
    try:
        tokens = tokenize.tokenize(io.BytesIO(source).readline)
        for token in tokens:
            if token.type in {
                tokenize.ENCODING,
                tokenize.ENDMARKER,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.NEWLINE,
                tokenize.NL,
                tokenize.COMMENT,
            }:
                continue
            significant.append((token.type, token.string))
    except (IndentationError, SyntaxError, tokenize.TokenError):
        # A dormant malformed Python-only module should not block native work.
        # Tokens produced before the lexical failure are still sufficient to
        # identify a Crabwalk declaration and make the syntax error reachable.
        pass
    for index in range(len(significant) - 2):
        first, dot, member = significant[index : index + 3]
        if (
            first == (tokenize.NAME, "rust")
            and dot == (tokenize.OP, ".")
            and member[0] == tokenize.NAME
            and member[1] in _CRABWALK_DECLARATION_MEMBERS
        ):
            return True
    return False


def _parse_for_imports(path: Path) -> ast.Module:
    try:
        source = path.read_bytes().decode("utf-8-sig")
    except OSError as error:
        raise CrabwalkCompilationError(
            Diagnostic("CRAB001", "Cannot read source", str(error))
        ) from error
    except UnicodeDecodeError as error:
        raise CrabwalkCompilationError(
            Diagnostic("CRAB002", "Source is not UTF-8", str(error))
        ) from error
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError as error:
        span = SourceSpan(
            str(path),
            error.lineno or 1,
            error.offset or 1,
            error.end_lineno or error.lineno or 1,
            error.end_offset or (error.offset or 1) + 1,
        )
        raise CrabwalkCompilationError(
            Diagnostic("CRAB100", "Invalid Python syntax", error.msg, span)
        ) from error


def _resolve_import_from(
    module_name: str,
    is_package: bool,
    node: ast.ImportFrom,
) -> str | None:
    if node.level == 0:
        return node.module
    package_parts = (
        module_name.split(".") if is_package else module_name.split(".")[:-1]
    )
    remove = node.level - 1
    if remove > len(package_parts):
        return None
    base = package_parts[: len(package_parts) - remove]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _hash_paths(root: Path, paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
