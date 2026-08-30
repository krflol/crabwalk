"""PEP 621 metadata used by Crabwalk's application build backend."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic

_EXTRA = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")


@dataclass(frozen=True, slots=True)
class ApplicationMetadata:
    """Validated application metadata preserved beside a native artifact."""

    name: str
    version: str
    summary: str | None
    requires_python: str | None
    dependencies: tuple[str, ...]
    optional_dependencies: tuple[tuple[str, tuple[str, ...]], ...]
    classifiers: tuple[str, ...]
    keywords: tuple[str, ...]
    authors: tuple[str, ...]
    maintainers: tuple[str, ...]
    urls: tuple[tuple[str, str], ...]
    readme: str | None
    readme_content_type: str | None
    license_expression: str | None
    license_text: str | None
    license_files: tuple[tuple[str, bytes], ...]
    entry_points: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]

    def core_metadata(self, runtime_requirement: str) -> bytes:
        """Render deterministic Core Metadata 2.4 with merged dependencies."""

        lines = [
            "Metadata-Version: 2.4",
            f"Name: {self.name}",
            f"Version: {self.version}",
        ]
        _append_header(lines, "Summary", self.summary)
        _append_header(lines, "Requires-Python", self.requires_python)
        _append_header(lines, "License-Expression", self.license_expression)
        _append_header(lines, "License", self.license_text)
        for value in self.authors:
            lines.append(f"Author-email: {value}")
        for value in self.maintainers:
            lines.append(f"Maintainer-email: {value}")
        if self.keywords:
            lines.append(f"Keywords: {','.join(self.keywords)}")
        lines.extend(f"Classifier: {value}" for value in self.classifiers)
        lines.extend(f"Project-URL: {label}, {url}" for label, url in self.urls)
        requirements = list(self.dependencies)
        if runtime_requirement not in requirements:
            requirements.append(runtime_requirement)
        lines.extend(f"Requires-Dist: {value}" for value in requirements)
        for extra, dependencies in self.optional_dependencies:
            lines.append(f"Provides-Extra: {extra}")
            for dependency in dependencies:
                lines.append(
                    f"Requires-Dist: {_dependency_for_extra(dependency, extra)}"
                )
        for relative, _ in self.license_files:
            lines.append(f"License-File: {relative}")
        _append_header(lines, "Description-Content-Type", self.readme_content_type)
        lines.append("")
        if self.readme is not None:
            lines.append(self.readme.rstrip("\n"))
        lines.append("")
        return "\n".join(lines).encode("utf-8")

    def entry_points_text(self) -> bytes | None:
        if not self.entry_points:
            return None
        lines: list[str] = []
        for group, values in self.entry_points:
            lines.append(f"[{group}]")
            lines.extend(f"{name} = {target}" for name, target in values)
            lines.append("")
        return "\n".join(lines).encode("utf-8")


def read_application_metadata(pyproject: str | Path) -> ApplicationMetadata:
    """Read the static PEP 621 subset required by the 1.1 build backend."""

    path = Path(pyproject).resolve()
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        _fail("CRAB510", "Cannot read application metadata", str(error))
    project = document.get("project")
    if not isinstance(project, dict):
        _fail("CRAB510", "Application metadata is missing", "Add a [project] table.")
    dynamic = project.get("dynamic", [])
    if not isinstance(dynamic, list) or not all(
        isinstance(value, str) for value in dynamic
    ):
        _fail(
            "CRAB510",
            "Invalid dynamic metadata",
            "[project].dynamic must be a string array.",
        )
    unsupported_dynamic = sorted(set(dynamic) & {"name", "version"})
    if unsupported_dynamic:
        _fail(
            "CRAB510",
            "Native application identity must be static",
            f"Declare [project].{unsupported_dynamic[0]} directly for reproducible wheels.",
        )
    name = _required_text(project, "name")
    version = _required_text(project, "version")
    summary = _optional_text(project, "description")
    requires_python = _optional_text(project, "requires-python")
    dependencies = _string_array(project, "dependencies")
    classifiers = _string_array(project, "classifiers")
    keywords = _string_array(project, "keywords")
    optional = _optional_dependencies(project.get("optional-dependencies"))
    authors = _people(project.get("authors"), "authors")
    maintainers = _people(project.get("maintainers"), "maintainers")
    urls = _string_table(project.get("urls"), "urls")
    readme, content_type, readme_file = _readme(project.get("readme"), path.parent)
    license_expression, license_text, license_file = _license(
        project.get("license"), path.parent
    )
    license_files = _license_files(project.get("license-files"), path.parent)
    if license_file is not None and license_file not in license_files:
        license_files = (*license_files, license_file)
    entry_points = _entry_points(project)
    # Reading the declared files here also ensures they are inside the project.
    del readme_file
    return ApplicationMetadata(
        name=name,
        version=version,
        summary=summary,
        requires_python=requires_python,
        dependencies=dependencies,
        optional_dependencies=optional,
        classifiers=classifiers,
        keywords=keywords,
        authors=authors,
        maintainers=maintainers,
        urls=urls,
        readme=readme,
        readme_content_type=content_type,
        license_expression=license_expression,
        license_text=license_text,
        license_files=tuple(sorted(license_files)),
        entry_points=entry_points,
    )


def project_metadata_input_files(pyproject: str | Path) -> tuple[Path, ...]:
    """Return readme/license inputs that must be included in an sdist."""

    path = Path(pyproject).resolve()
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    project = document.get("project")
    if not isinstance(project, dict):
        return ()
    results: set[Path] = set()
    readme = project.get("readme")
    if isinstance(readme, str):
        results.add(_contained_file(path.parent, readme))
    elif isinstance(readme, dict) and isinstance(readme.get("file"), str):
        results.add(_contained_file(path.parent, readme["file"]))
    license_value = project.get("license")
    if isinstance(license_value, dict) and isinstance(license_value.get("file"), str):
        results.add(_contained_file(path.parent, license_value["file"]))
    patterns = project.get("license-files", [])
    if isinstance(patterns, list):
        for pattern in patterns:
            if not isinstance(pattern, str):
                continue
            results.update(
                value.resolve()
                for value in path.parent.glob(pattern)
                if value.is_file() and value.resolve().is_relative_to(path.parent)
            )
    return tuple(sorted(results))


def _append_header(lines: list[str], name: str, value: str | None) -> None:
    if value is not None:
        lines.append(f"{name}: {_safe_header(value, name)}")


def _safe_header(value: str, name: str) -> str:
    if "\n" in value or "\r" in value:
        _fail("CRAB510", "Invalid application metadata", f"{name} contains a newline.")
    return value


def _required_text(project: dict[str, Any], name: str) -> str:
    value = project.get(name)
    if not isinstance(value, str) or not value:
        _fail(
            "CRAB510",
            "Application metadata is incomplete",
            f"[project].{name} is required.",
        )
    return _safe_header(value, name)


def _optional_text(project: dict[str, Any], name: str) -> str | None:
    value = project.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        _fail(
            "CRAB510", "Invalid application metadata", f"[project].{name} must be text."
        )
    return _safe_header(value, name)


def _string_array(project: dict[str, Any], name: str) -> tuple[str, ...]:
    value = project.get(name, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        _fail(
            "CRAB510",
            "Invalid application metadata",
            f"[project].{name} must be a string array.",
        )
    return tuple(_safe_header(item, name) for item in value)


def _optional_dependencies(value: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        _fail(
            "CRAB510",
            "Invalid optional dependencies",
            "Use a table of dependency arrays.",
        )
    result: list[tuple[str, tuple[str, ...]]] = []
    for name, dependencies in value.items():
        if not isinstance(name, str) or not _EXTRA.fullmatch(name):
            _fail("CRAB510", "Invalid optional dependency name", repr(name))
        if not isinstance(dependencies, list) or not all(
            isinstance(item, str) and item for item in dependencies
        ):
            _fail(
                "CRAB510",
                "Invalid optional dependencies",
                f"Extra {name!r} must be a string array.",
            )
        result.append(
            (name, tuple(_safe_header(item, "dependency") for item in dependencies))
        )
    return tuple(sorted(result))


def _people(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        _fail(
            "CRAB510",
            "Invalid people metadata",
            f"[project].{field} must be an array of tables.",
        )
    result: list[str] = []
    for person in value:
        if not isinstance(person, dict):
            _fail(
                "CRAB510",
                "Invalid people metadata",
                f"Each {field} item must be a table.",
            )
        name = person.get("name")
        email = person.get("email")
        if name is not None and not isinstance(name, str):
            _fail("CRAB510", "Invalid people metadata", f"{field} name must be text.")
        if email is not None and not isinstance(email, str):
            _fail("CRAB510", "Invalid people metadata", f"{field} email must be text.")
        if not name and not email:
            _fail(
                "CRAB510",
                "Invalid people metadata",
                f"Each {field} item needs name or email.",
            )
        rendered = f"{name} <{email}>" if name and email else str(name or email)
        result.append(_safe_header(rendered, field))
    return tuple(result)


def _string_table(value: object, field: str) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        _fail(
            "CRAB510",
            "Invalid application metadata",
            f"[project].{field} must be a string table.",
        )
    return tuple(
        sorted(
            (_safe_header(key, field), _safe_header(item, field))
            for key, item in value.items()
        )
    )


def _readme(value: object, root: Path) -> tuple[str | None, str | None, Path | None]:
    if value is None:
        return None, None, None
    if isinstance(value, str):
        path = _contained_file(root, value)
        return path.read_text(encoding="utf-8"), _content_type(path), path
    if not isinstance(value, dict):
        _fail("CRAB510", "Invalid readme metadata", "Use a file path or readme table.")
    content_type = value.get("content-type")
    if not isinstance(content_type, str):
        _fail(
            "CRAB510", "Invalid readme metadata", "A readme table needs content-type."
        )
    if isinstance(value.get("file"), str) and "text" not in value:
        path = _contained_file(root, value["file"])
        return path.read_text(encoding="utf-8"), content_type, path
    if isinstance(value.get("text"), str) and "file" not in value:
        return value["text"], content_type, None
    _fail(
        "CRAB510",
        "Invalid readme metadata",
        "Choose exactly one of readme.file or readme.text.",
    )


def _license(
    value: object, root: Path
) -> tuple[str | None, str | None, tuple[str, bytes] | None]:
    if value is None:
        return None, None, None
    if isinstance(value, str):
        return _safe_header(value, "license"), None, None
    if not isinstance(value, dict):
        _fail(
            "CRAB510",
            "Invalid license metadata",
            "Use an SPDX string or license table.",
        )
    if isinstance(value.get("file"), str) and "text" not in value:
        path = _contained_file(root, value["file"])
        return None, None, (path.name, path.read_bytes())
    if isinstance(value.get("text"), str) and "file" not in value:
        return None, value["text"], None
    _fail(
        "CRAB510",
        "Invalid license metadata",
        "Choose exactly one of license.file or license.text.",
    )


def _license_files(value: object, root: Path) -> tuple[tuple[str, bytes], ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        _fail(
            "CRAB510",
            "Invalid license-files metadata",
            "Use an array of relative glob patterns.",
        )
    result: dict[str, bytes] = {}
    for pattern in value:
        pattern_path = Path(pattern)
        if pattern_path.is_absolute() or ".." in pattern_path.parts:
            _fail("CRAB510", "License pattern escapes the project", pattern)
        for path in root.glob(pattern):
            resolved = path.resolve()
            if resolved.is_file() and resolved.is_relative_to(root):
                result[resolved.relative_to(root).as_posix()] = resolved.read_bytes()
    return tuple(sorted(result.items()))


def _entry_points(
    project: dict[str, Any],
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    groups: dict[str, tuple[tuple[str, str], ...]] = {}
    for field, group in (
        ("scripts", "console_scripts"),
        ("gui-scripts", "gui_scripts"),
    ):
        values = _string_table(project.get(field), field)
        if values:
            groups[group] = values
    raw = project.get("entry-points")
    if raw is not None:
        if not isinstance(raw, dict):
            _fail(
                "CRAB510",
                "Invalid entry points",
                "[project.entry-points] must contain tables.",
            )
        for group, values in raw.items():
            if not isinstance(group, str):
                _fail("CRAB510", "Invalid entry-point group", repr(group))
            groups[group] = _string_table(values, f"entry-points.{group}")
    return tuple(sorted(groups.items()))


def _dependency_for_extra(dependency: str, extra: str) -> str:
    if ";" in dependency:
        requirement, marker = dependency.split(";", 1)
        return f'{requirement.strip()}; ({marker.strip()}) and extra == "{extra}"'
    return f'{dependency}; extra == "{extra}"'


def _content_type(path: Path) -> str:
    return {
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".rst": "text/x-rst",
    }.get(path.suffix.casefold(), "text/plain")


def _contained_file(root: Path, value: str) -> Path:
    relative = Path(value)
    resolved = (root / relative).resolve()
    if (
        relative.is_absolute()
        or not resolved.is_relative_to(root)
        or not resolved.is_file()
    ):
        _fail("CRAB510", "Metadata file is unavailable", value)
    return resolved


def _fail(code: str, title: str, message: str) -> NoReturn:
    raise CrabwalkCompilationError(Diagnostic(code, title, message))
