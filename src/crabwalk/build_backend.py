"""PEP 517 backend for metadata-rich Crabwalk application distributions."""

from __future__ import annotations

import gzip
import io
import os
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

from crabwalk._version import RUNTIME_DISTRIBUTION_REQUIREMENT
from crabwalk.config import ProjectConfig, discover_project_config
from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic
from crabwalk.project_metadata import (
    ApplicationMetadata,
    project_metadata_input_files,
    read_application_metadata,
)
from crabwalk.wheel import (
    _normalized_distribution,
    _package_entries,
    _wheel_metadata,
    _wheel_tags,
    build_wheel as build_crabwalk_wheel,
)


def get_requires_for_build_wheel(
    config_settings: dict[str, Any] | None = None,
) -> list[str]:
    del config_settings
    return []


def get_requires_for_build_sdist(
    config_settings: dict[str, Any] | None = None,
) -> list[str]:
    del config_settings
    return []


def build_wheel(
    wheel_directory: str,
    config_settings: dict[str, Any] | None = None,
    metadata_directory: str | None = None,
) -> str:
    """Build one platform wheel while retaining ordinary project metadata."""

    del metadata_directory
    root, project, config, metadata = _project()
    locked = _setting_bool(config_settings, "crabwalk-locked", config.source_locked)
    offline = _setting_bool(config_settings, "crabwalk-offline", False)
    result = build_crabwalk_wheel(
        config.packages[0] if len(config.packages) == 1 else config.packages,
        wheel_directory,
        project=project,
        locked=locked,
        offline=offline,
        metadata=metadata,
    )
    del root
    return result.path.name


def prepare_metadata_for_build_wheel(
    metadata_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    """Prepare metadata without compiling the native extension."""

    del config_settings
    _, _, config, metadata = _project()
    normalized_name = _normalized_distribution(metadata.name)
    normalized_version = metadata.version.replace("-", "_")
    dist_info_name = f"{normalized_name}-{normalized_version}.dist-info"
    destination = Path(metadata_directory).resolve() / dist_info_name
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "METADATA").write_bytes(
        metadata.core_metadata(RUNTIME_DISTRIBUTION_REQUIREMENT)
    )
    tag = "-".join(_wheel_tags())
    (destination / "WHEEL").write_bytes(_wheel_metadata(tag))
    (destination / "top_level.txt").write_text(
        "".join(f"{package.name}\n" for package in config.packages),
        encoding="utf-8",
    )
    entry_points = metadata.entry_points_text()
    if entry_points is not None:
        (destination / "entry_points.txt").write_bytes(entry_points)
    for relative, payload in metadata.license_files:
        license_path = destination / "licenses" / Path(relative)
        license_path.parent.mkdir(parents=True, exist_ok=True)
        license_path.write_bytes(payload)
    return dist_info_name


def build_sdist(
    sdist_directory: str,
    config_settings: dict[str, Any] | None = None,
) -> str:
    """Build a deterministic source archive containing every native input."""

    del config_settings
    root, project, config, metadata = _project()
    normalized = _normalized_distribution(metadata.name).replace("_", "-")
    archive_name = f"{normalized}-{metadata.version}.tar.gz"
    prefix = PurePosixPath(f"{normalized}-{metadata.version}")
    entries: dict[str, bytes] = {
        "pyproject.toml": project.read_bytes(),
        "PKG-INFO": metadata.core_metadata(RUNTIME_DISTRIBUTION_REQUIREMENT),
    }
    for package in config.packages:
        source_prefix = package.parent.relative_to(root)
        for archive_path, payload in _package_entries(
            package, config.wheel_include
        ).items():
            entries[(source_prefix / Path(archive_path)).as_posix()] = payload
    for path in (*project_metadata_input_files(project), *config.extra_files):
        _add_sdist_input(entries, root, path)

    output = Path(sdist_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / archive_name
    temporary = output / f".{archive_name}.{os.getpid()}.tmp"
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
                with tarfile.open(
                    fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT
                ) as archive:
                    for relative in sorted(entries):
                        payload = entries[relative]
                        info = tarfile.TarInfo(str(prefix / PurePosixPath(relative)))
                        info.size = len(payload)
                        info.mode = 0o644
                        info.mtime = 0
                        info.uid = 0
                        info.gid = 0
                        info.uname = ""
                        info.gname = ""
                        archive.addfile(info, io.BytesIO(payload))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return archive_name


def _project() -> tuple[Path, Path, ProjectConfig, ApplicationMetadata]:
    root = Path.cwd().resolve()
    project = root / "pyproject.toml"
    config = discover_project_config(root, project)
    assert config is not None
    if not config.packages:
        _fail(
            "CRAB511",
            "Application backend needs a native package",
            "Declare at least one [tool.crabwalk].packages entry.",
        )
    metadata = read_application_metadata(project)
    return root, project, config, metadata


def _setting_bool(
    settings: dict[str, Any] | None,
    name: str,
    default: bool,
) -> bool:
    if not settings or name not in settings:
        return default
    value = settings[name]
    if isinstance(value, list):
        value = value[-1] if value else ""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.casefold() in {"1", "true", "yes", "on"}:
        return True
    if isinstance(value, str) and value.casefold() in {"0", "false", "no", "off"}:
        return False
    _fail("CRAB511", "Invalid build setting", f"{name} must be true or false.")


def _add_sdist_input(entries: dict[str, bytes], root: Path, path: Path) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        _fail("CRAB511", "Source-distribution input escapes project", str(path))
    if resolved.is_file():
        entries[resolved.relative_to(root).as_posix()] = resolved.read_bytes()
        return
    if resolved.is_dir():
        for candidate in sorted(resolved.rglob("*")):
            if candidate.is_file() and not candidate.is_symlink():
                entries[candidate.relative_to(root).as_posix()] = candidate.read_bytes()


def _fail(code: str, title: str, message: str) -> NoReturn:
    raise CrabwalkCompilationError(Diagnostic(code, title, message))
