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
from typing import NoReturn

from crabwalk._version import (
    RUNTIME_ABI_VERSION,
    RUNTIME_DISTRIBUTION,
    __version__,
)
from crabwalk.build.cache import sha256_file
from crabwalk.config import discover_project_config
from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic
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


def build_wheel(
    package: str | Path,
    output_directory: str | Path = "dist",
    *,
    distribution_name: str | None = None,
    version: str = "0.0.0",
    locked: bool = False,
    offline: bool = False,
    service: CompilationService | None = None,
) -> WheelResult:
    """Compile a regular Python package and place its native artifact in a wheel."""

    package_root = _regular_package_root(Path(package).resolve())
    name = distribution_name or package_root.name
    _validate_metadata(name, version)
    if sys.implementation.name != "cpython":
        _fail(
            "CRAB501",
            "Unsupported wheel interpreter",
            "Crabwalk currently builds interpreter-specific CPython wheels only.",
        )

    compiler = service or default_service
    compilation = compiler.compile_path(
        package_root,
        module_name=package_root.name,
        mode="build",
        load=False,
        locked=locked,
        offline=offline,
    )
    artifact = compilation.artifact
    if artifact is None or not artifact.is_file():
        _fail(
            "CRAB502",
            "Native wheel artifact is missing",
            "The package compilation completed without a loadable extension artifact.",
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

    config = discover_project_config(package_root)
    wheel_include = config.wheel_include if config is not None else ()
    entries = _package_entries(package_root, wheel_include)
    package_prefix = PurePosixPath(package_root.name)
    artifact_entry = package_prefix / _NATIVE_DIRECTORY / artifact.name
    manifest_entry = package_prefix / _PREBUILT_MANIFEST
    manifest = _prebuilt_manifest(
        compilation, artifact_entry.relative_to(package_prefix)
    )
    entries[str(artifact_entry)] = artifact.read_bytes()
    entries[str(manifest_entry)] = manifest

    dist_info = PurePosixPath(f"{normalized_name}-{normalized_version}.dist-info")
    entries[str(dist_info / "METADATA")] = _metadata(name, version)
    entries[str(dist_info / "WHEEL")] = _wheel_metadata(tag)
    entries[str(dist_info / "top_level.txt")] = f"{package_root.name}\n".encode()
    record_name = str(dist_info / "RECORD")
    entries[record_name] = _record(entries, record_name)

    try:
        _write_archive(temporary, entries)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return WheelResult(destination, compilation, name, version, tag)


def _regular_package_root(path: Path) -> Path:
    directory = path if path.is_dir() else path.parent
    if not (directory / "__init__.py").is_file():
        _fail(
            "CRAB500",
            "Wheel input is not a regular Python package",
            f"{path} is not inside a package containing __init__.py.",
            "Pass the package directory or one of its Python source files.",
        )
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
    value = {
        "schema_version": 3,
        "crabwalk_version": __version__,
        "runtime_abi_version": RUNTIME_ABI_VERSION,
        "module_name": compilation.ir.module_name,
        "source_hash": compilation.ir.source_hash,
        "compiler_input_hash": compilation.ir.compiler_input_hash,
        "wheel_source_integrity_hash": (compilation.ir.wheel_source_integrity_hash),
        "fingerprint": compilation.fingerprint,
        "extension_name": compilation.extension_name,
        "artifact": str(artifact_relative),
        "artifact_sha256": sha256_file(artifact),
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
        f"Requires-Dist: {RUNTIME_DISTRIBUTION}=={__version__}\n"
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
