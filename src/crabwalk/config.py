"""Static, bounded project configuration discovery."""

from __future__ import annotations

import hashlib
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
    supported = {"packages", "python-boundaries"}
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
        if not (package / "__init__.py").is_file():
            _fail(
                "CRAB010",
                "Configured package is not a regular Python package",
                f"{package} has no __init__.py.",
            )
        packages.append(package)
    policy = table.get("python-boundaries", "allow")
    if policy not in {"allow", "warn", "deny"}:
        _fail(
            "CRAB010",
            "Invalid Python-boundary policy",
            "python-boundaries must be 'allow', 'warn', or 'deny'.",
        )
    return ProjectConfig(
        root=root,
        pyproject=pyproject.resolve(),
        packages=tuple(packages),
        python_boundaries=str(policy),
        content_hash=hashlib.sha256(raw).hexdigest(),
    )


def _fail(code: str, title: str, message: str) -> None:
    raise CrabwalkCompilationError(Diagnostic(code, title, message))
