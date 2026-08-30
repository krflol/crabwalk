"""Build platform wheels containing a verified Crabwalk native extension."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import keyword
import os
import re
import sys
import sysconfig
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from collections.abc import Sequence
from typing import NoReturn

from crabwalk._version import (
    GENERATED_WRAPPER_ABI_VERSION,
    PREBUILT_MANIFEST_SCHEMA_VERSION,
    RUNTIME_ABI_VERSION,
    RUNTIME_COMPATIBILITY_SPECIFIER,
    RUNTIME_DISTRIBUTION_REQUIREMENT,
    __version__,
)
from crabwalk.build.cache import sha256_file
from crabwalk.config import discover_project_config
from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic
from crabwalk.project_metadata import ApplicationMetadata
from crabwalk.service import CompilationResult, CompilationService, default_service

_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_VERSION = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.!+_-]*[A-Za-z0-9])?$")
_PREBUILT_MANIFEST = "_crabwalk_prebuilt.json"
_NATIVE_DIRECTORY = "_crabwalk_native"


@dataclass(frozen=True, slots=True)
class WheelResult:
    path: Path
    compilation: CompilationResult
    distribution_name: str
    version: str
    tag: str
    compilations: tuple[CompilationResult, ...] = ()


def build_wheel(
    package: str | Path | Sequence[str | Path],
    output_directory: str | Path = "dist",
    *,
    distribution_name: str | None = None,
    version: str = "0.0.0",
    project: str | Path | None = None,
    locked: bool = False,
    offline: bool = False,
    service: CompilationService | None = None,
    metadata: ApplicationMetadata | None = None,
) -> WheelResult:
    """Compile one or more Python packages into one platform wheel."""

    requested_paths = (
        (Path(package).resolve(),)
        if isinstance(package, (str, Path))
        else tuple(Path(value).resolve() for value in package)
    )
    if not requested_paths:
        _fail("CRAB500", "Wheel input is empty", "Pass at least one package.")
    config = discover_project_config(requested_paths[0], project)
    source_paths = tuple(
        config.resolve_entry(path) if config is not None else path
        for path in requested_paths
    )
    package_roots = tuple(_regular_package_root(path) for path in source_paths)
    if len({root.name for root in package_roots}) != len(package_roots):
        _fail(
            "CRAB500",
            "Wheel package names collide",
            "Each configured top-level package must have a distinct import name.",
        )
    if metadata is not None:
        if distribution_name is not None and distribution_name != metadata.name:
            _fail(
                "CRAB510",
                "Conflicting distribution metadata",
                "The backend project name differs from the requested wheel name.",
            )
        if version != "0.0.0" and version != metadata.version:
            _fail(
                "CRAB510",
                "Conflicting distribution metadata",
                "The backend project version differs from the requested wheel version.",
            )
        distribution_name = metadata.name
        version = metadata.version
    if len(package_roots) > 1 and metadata is None:
        _fail(
            "CRAB500",
            "Multiple packages need distribution metadata",
            "Build through a [project] and [tool.crabwalk] configuration.",
        )
    name = distribution_name or package_roots[0].name
    _validate_metadata(name, version)
    if sys.implementation.name != "cpython":
        _fail(
            "CRAB501",
            "Unsupported wheel interpreter",
            "Crabwalk currently builds interpreter-specific CPython wheels only.",
        )

    compiler = service or default_service
    compilations = tuple(
        compiler.compile_path(
            package_root,
            module_name=package_root.name,
            mode="build",
            load=False,
            locked=locked,
            offline=offline,
            project=project,
        )
        for package_root in package_roots
    )
    for compilation in compilations:
        artifact = compilation.artifact
        if artifact is None or not artifact.is_file():
            _fail(
                "CRAB502",
                "Native wheel artifact is missing",
                "A package compilation completed without a loadable extension artifact.",
            )

    python_tag, abi_tag, platform_tag = _wheel_tags()
    tag = f"{python_tag}-{abi_tag}-{platform_tag}"
    normalized_name = _normalized_distribution(name)
    normalized_version = version.replace("-", "_")
    wheel_name = f"{normalized_name}-{normalized_version}-{tag}.whl"
    output_root = Path(output_directory).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / wheel_name
    temporary = output_root / f".{wheel_name}.{os.getpid()}.tmp"

    wheel_include = config.wheel_include if config is not None else ()
    entries: dict[str, bytes] = {}
    for package_root, compilation in zip(package_roots, compilations, strict=True):
        package_entries = _package_entries(package_root, wheel_include)
        overlap = set(entries) & set(package_entries)
        if overlap:
            _fail(
                "CRAB500",
                "Wheel package entries collide",
                min(overlap),
            )
        entries.update(package_entries)
        artifact = compilation.artifact
        assert artifact is not None
        package_prefix = PurePosixPath(package_root.name)
        artifact_entry = package_prefix / _NATIVE_DIRECTORY / artifact.name
        manifest_entry = package_prefix / _PREBUILT_MANIFEST
        entries[str(artifact_entry)] = artifact.read_bytes()
        entries[str(manifest_entry)] = _prebuilt_manifest(
            compilation, artifact_entry.relative_to(package_prefix)
        )

    dist_info = PurePosixPath(f"{normalized_name}-{normalized_version}.dist-info")
    entries[str(dist_info / "METADATA")] = (
        metadata.core_metadata(RUNTIME_DISTRIBUTION_REQUIREMENT)
        if metadata is not None
        else _metadata(name, version)
    )
    entries[str(dist_info / "WHEEL")] = _wheel_metadata(tag)
    entries[str(dist_info / "top_level.txt")] = "".join(
        f"{root.name}\n" for root in package_roots
    ).encode()
    if metadata is not None:
        entry_points = metadata.entry_points_text()
        if entry_points is not None:
            entries[str(dist_info / "entry_points.txt")] = entry_points
        for relative, payload in metadata.license_files:
            license_path = PurePosixPath(relative)
            if license_path.is_absolute() or ".." in license_path.parts:
                _fail(
                    "CRAB510",
                    "Unsafe license-file path",
                    relative,
                )
            entries[str(dist_info / "licenses" / license_path)] = payload
    record_name = str(dist_info / "RECORD")
    entries[record_name] = _record(entries, record_name)

    try:
        _write_archive(temporary, entries)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return WheelResult(
        destination,
        compilations[0],
        name,
        version,
        tag,
        compilations,
    )


def _regular_package_root(path: Path) -> Path:
    directory = path if path.is_dir() else path.parent
    if not (directory / "__init__.py").is_file():
        if not path.is_dir() or not any(path.rglob("*.py")):
            _fail(
                "CRAB500",
                "Wheel input is not a Python package",
                f"{path} is not a package directory with Python sources.",
                "Pass a regular or configured namespace package directory.",
            )
    else:
        while (directory.parent / "__init__.py").is_file():
            directory = directory.parent
    if not directory.name.isidentifier() or keyword.iskeyword(directory.name):
        _fail(
            "CRAB505",
            "Package name is not importable",
            f"{directory.name!r} is not a valid top-level Python package name.",
        )
    return directory


def _validate_metadata(name: str, version: str) -> None:
    if not _NAME.fullmatch(name):
        _fail(
            "CRAB503",
            "Invalid distribution name",
            f"{name!r} is not a safe Python distribution name.",
        )
    if not _VERSION.fullmatch(version):
        _fail(
            "CRAB504",
            "Invalid distribution version",
            f"{version!r} is not a safe wheel version.",
        )


def _package_entries(
    package_root: Path,
    wheel_include: tuple[str, ...] = (),
) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for source in sorted(
        (candidate for candidate in package_root.rglob("*") if candidate.is_file()),
        key=lambda value: value.relative_to(package_root).as_posix(),
    ):
        relative = source.relative_to(package_root)
        if _excluded(relative):
            continue
        if _sensitive_package_file(relative):
            _fail(
                "CRAB507",
                "Sensitive file found beneath wheel package",
                f"Refusing to package while {relative} is present.",
                "Move credentials and private keys outside the import package.",
            )
        if not _wheel_file_allowed(relative, wheel_include):
            continue
        if source.is_symlink():
            _fail(
                "CRAB506",
                "Symbolic links are unsupported in Crabwalk wheels",
                f"Refusing to package symbolic link {relative}.",
                "Replace it with a regular package file or an explicit build step.",
            )
        archive_path = PurePosixPath(package_root.name, *relative.parts)
        result[str(archive_path)] = source.read_bytes()
    return result


def _excluded(relative: Path) -> bool:
    if relative.name in {_PREBUILT_MANIFEST} or relative.suffix in {".pyc", ".pyo"}:
        return True
    blocked = {".crabwalk", ".git", "__pycache__", _NATIVE_DIRECTORY}
    return any(part in blocked for part in relative.parts)


def _wheel_file_allowed(relative: Path, patterns: tuple[str, ...]) -> bool:
    if relative.suffix in {".py", ".pyi"} or relative.name == "py.typed":
        return True
    normalized = PurePosixPath(*relative.parts)
    return any(normalized.match(pattern) for pattern in patterns)


def _sensitive_package_file(relative: Path) -> bool:
    name = relative.name.casefold()
    stem = relative.stem.casefold()
    if name in {".env", "credentials", "credentials.json", "id_rsa", "id_ed25519"}:
        return True
    if relative.suffix.casefold() in {".key", ".pem", ".p12", ".pfx"}:
        return True
    return any(token in stem for token in ("credential", "private_key", "secret"))


def _prebuilt_manifest(
    compilation: CompilationResult,
    artifact_relative: PurePosixPath,
) -> bytes:
    import json

    artifact = compilation.artifact
    if artifact is None:
        raise AssertionError("wheel compilation has no artifact")
    build_inputs = compilation.build_inputs or {}
    cargo_policy = build_inputs.get("cargo_policy")
    dependency_lock_hash = build_inputs.get("dependency_lock_hash")
    if not (
        isinstance(cargo_policy, dict)
        and isinstance(cargo_policy.get("locked"), bool)
        and isinstance(cargo_policy.get("offline"), bool)
        and isinstance(dependency_lock_hash, str)
        and len(dependency_lock_hash) == 64
        and all(character in "0123456789abcdef" for character in dependency_lock_hash)
    ):
        _fail(
            "CRAB508",
            "Wheel build provenance is incomplete",
            "The compilation result does not contain a Cargo policy and dependency-lock hash.",
            "Build the wheel through Crabwalk's CompilationService.",
        )
    value = {
        "schema_version": PREBUILT_MANIFEST_SCHEMA_VERSION,
        "crabwalk_version": __version__,
        "runtime_abi_version": RUNTIME_ABI_VERSION,
        "generated_wrapper_abi_version": GENERATED_WRAPPER_ABI_VERSION,
        "runtime_compatibility_specifier": RUNTIME_COMPATIBILITY_SPECIFIER,
        "module_name": compilation.ir.module_name,
        "source_hash": compilation.ir.source_hash,
        "compiler_input_hash": compilation.ir.compiler_input_hash,
        "wheel_source_integrity_hash": (compilation.ir.wheel_source_integrity_hash),
        "fingerprint": compilation.fingerprint,
        "extension_name": compilation.extension_name,
        "artifact": str(artifact_relative),
        "artifact_sha256": sha256_file(artifact),
        "cargo_policy": {
            "locked": cargo_policy["locked"],
            "offline": cargo_policy["offline"],
        },
        "dependency_lock_hash": dependency_lock_hash,
    }
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _wheel_tags() -> tuple[str, str, str]:
    interpreter = f"cp{sys.version_info.major}{sys.version_info.minor}"
    platform = re.sub(r"[-. ]+", "_", sysconfig.get_platform())
    return interpreter, interpreter, platform


def _normalized_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "_", value)


def _metadata(name: str, version: str) -> bytes:
    return (
        "Metadata-Version: 2.1\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        "Summary: A Python package with native functions compiled by Crabwalk\n"
        "Requires-Python: >=3.11\n"
        f"Requires-Dist: {RUNTIME_DISTRIBUTION_REQUIREMENT}\n"
        "\n"
    ).encode("utf-8")


def _wheel_metadata(tag: str) -> bytes:
    return (
        "Wheel-Version: 1.0\n"
        f"Generator: crabwalk {__version__}\n"
        "Root-Is-Purelib: false\n"
        f"Tag: {tag}\n"
        "\n"
    ).encode("utf-8")


def _record(entries: dict[str, bytes], record_name: str) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name in sorted(entries):
        if name == record_name:
            continue
        payload = entries[name]
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
        writer.writerow((name, f"sha256={digest.decode('ascii')}", len(payload)))
    writer.writerow((record_name, "", ""))
    return output.getvalue().encode("utf-8")


def _write_archive(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, entries[name])


def _fail(
    code: str,
    title: str,
    message: str,
    help_text: str | None = None,
) -> NoReturn:
    raise CrabwalkCompilationError(Diagnostic(code, title, message, help=help_text))
