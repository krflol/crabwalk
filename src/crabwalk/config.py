"""Static, bounded project configuration discovery."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    root: Path
    pyproject: Path
    packages: tuple[Path, ...]
    python_boundaries: str
    source_locked: bool
    extra_files: tuple[Path, ...]
    extra_env: tuple[str, ...]
    wheel_include: tuple[str, ...]
    content_hash: str

    def resolve_entry(self, requested: Path) -> Path:
        requested = requested.resolve()
        if requested in {self.root, self.pyproject}:
            if len(self.packages) != 1:
                _fail(
                    "CRAB011",
                    "Configured project path is ambiguous",
                    (
                        f"{self.pyproject} declares {len(self.packages)} packages; "
                        "select one package or source file explicitly."
                    ),
                )
            return self.packages[0]
        if self.packages and not any(
            requested == package or requested.is_relative_to(package)
            for package in self.packages
        ):
            _fail(
                "CRAB012",
                "Source is outside configured Crabwalk packages",
                f"{requested} is not beneath a [tool.crabwalk].packages entry.",
            )
        return requested


def discover_project_config(
    path: str | Path,
    explicit_project: str | Path | None = None,
) -> ProjectConfig | None:
    """Find the nearest pyproject containing [tool.crabwalk]."""

    requested = Path(explicit_project or path).resolve()
    if explicit_project is not None:
        pyproject = requested if requested.is_file() else requested / "pyproject.toml"
        if not pyproject.is_file():
            _fail(
                "CRAB009",
                "Explicit Crabwalk project has no pyproject.toml",
                str(pyproject),
            )
        config = _read_config(pyproject, required=True)
        assert config is not None
        return config

    start = requested if requested.is_dir() else requested.parent
    for directory in (start, *start.parents):
        pyproject = directory / "pyproject.toml"
        if pyproject.is_file():
            config = _read_config(pyproject, required=False)
            if config is not None:
                return config
    return None


def configuration_hash(path: str | Path) -> str | None:
    config = discover_project_config(path)
    return config.content_hash if config is not None else None


def _read_config(pyproject: Path, *, required: bool) -> ProjectConfig | None:
    try:
        raw = pyproject.read_bytes()
        document = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        _fail("CRAB010", "Cannot read Crabwalk project configuration", str(error))
    tool = document.get("tool")
    table = tool.get("crabwalk") if isinstance(tool, dict) else None
    if table is None:
        if required:
            _fail(
                "CRAB009",
                "Explicit project has no [tool.crabwalk] table",
                str(pyproject),
            )
        return None
    if not isinstance(table, dict):
        _fail("CRAB010", "Invalid [tool.crabwalk] table", str(pyproject))
    supported = {
        "packages",
        "python-boundaries",
        "source-locked",
        "extra-files",
        "extra-env",
        "wheel-include",
    }
    unknown = sorted(set(table) - supported)
    if unknown:
        _fail(
            "CRAB010",
            "Unsupported Crabwalk project option",
            f"Unknown [tool.crabwalk] keys: {', '.join(unknown)}.",
        )
    package_values = table.get("packages", [])
    if not isinstance(package_values, list) or not all(
        isinstance(value, str) and value for value in package_values
    ):
        _fail(
            "CRAB010",
            "Invalid Crabwalk package list",
            "[tool.crabwalk].packages must be an array of non-empty relative paths.",
        )
    root = pyproject.parent.resolve()
    packages: list[Path] = []
    for value in package_values:
        relative = Path(value)
        package = (root / relative).resolve()
        if relative.is_absolute() or not package.is_relative_to(root):
            _fail(
                "CRAB010",
                "Configured package escapes the project",
                str(value),
            )
        if not package.is_dir() or not any(package.rglob("*.py")):
            _fail(
                "CRAB010",
                "Configured package has no Python sources",
                f"{package} must be a regular or namespace package directory.",
            )
        packages.append(package)
    policy = table.get("python-boundaries", "allow")
    if policy not in {"allow", "warn", "deny"}:
        _fail(
            "CRAB010",
            "Invalid Python-boundary policy",
            "python-boundaries must be 'allow', 'warn', or 'deny'.",
        )
    source_locked = table.get("source-locked", False)
    if not isinstance(source_locked, bool):
        _fail(
            "CRAB010",
            "Invalid source build policy",
            "[tool.crabwalk].source-locked must be true or false.",
        )
    extra_file_values = table.get("extra-files", [])
    if not isinstance(extra_file_values, list) or not all(
        isinstance(value, str) and value for value in extra_file_values
    ):
        _fail(
            "CRAB010",
            "Invalid extra build-file list",
            "[tool.crabwalk].extra-files must contain non-empty relative paths.",
        )
    extra_files: list[Path] = []
    for value in extra_file_values:
        relative = Path(value)
        resolved = (root / relative).resolve()
        if relative.is_absolute() or not resolved.is_relative_to(root):
            _fail("CRAB010", "Extra build file escapes the project", value)
        if not resolved.exists():
            _fail("CRAB010", "Extra build file does not exist", value)
        extra_files.append(resolved)
    extra_env_values = table.get("extra-env", [])
    if not isinstance(extra_env_values, list) or not all(
        isinstance(value, str)
        and value
        and value.replace("_", "a").isalnum()
        and not value[0].isdigit()
        for value in extra_env_values
    ):
        _fail(
            "CRAB010",
            "Invalid extra build-environment list",
            "[tool.crabwalk].extra-env must contain environment variable names.",
        )
    wheel_include_values = table.get("wheel-include", [])
    if not isinstance(wheel_include_values, list) or not all(
        isinstance(value, str)
        and value
        and not Path(value).is_absolute()
        and ".." not in Path(value).parts
        for value in wheel_include_values
    ):
        _fail(
            "CRAB010",
            "Invalid wheel package-data list",
            "[tool.crabwalk].wheel-include must contain scoped relative glob patterns.",
        )
    return ProjectConfig(
        root=root,
        pyproject=pyproject.resolve(),
        packages=tuple(packages),
        python_boundaries=str(policy),
        source_locked=source_locked,
        extra_files=tuple(extra_files),
        extra_env=tuple(extra_env_values),
        wheel_include=tuple(wheel_include_values),
        content_hash=_native_configuration_hash(
            packages=tuple(package_values),
            python_boundaries=str(policy),
            source_locked=source_locked,
            extra_files=tuple(extra_file_values),
            extra_env=tuple(extra_env_values),
        ),
    )


def _native_configuration_hash(
    *,
    packages: tuple[str, ...],
    python_boundaries: str,
    source_locked: bool,
    extra_files: tuple[str, ...],
    extra_env: tuple[str, ...],
) -> str:
    """Hash only project settings that can affect generated native output."""

    payload = {
        "schema": 1,
        "packages": packages,
        "python_boundaries": python_boundaries,
        "source_locked": source_locked,
        "extra_files": extra_files,
        "extra_env": extra_env,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fail(code: str, title: str, message: str) -> None:
    raise CrabwalkCompilationError(Diagnostic(code, title, message))
