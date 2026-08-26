"""Cargo manifest, build script, and dependency-identity emission."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .ir import PackageIR
from .naming import PYO3_CARGO_ALIAS, cargo_dependency_key

PYO3_VERSION = "0.29.2"


def render_cargo_toml(
    ir: PackageIR,
    extension_name: str,
    cargo_package_identity: str | None = None,
) -> str:
    dependencies = _cargo_dependencies(ir)
    package_name = _generated_package_name(cargo_package_identity or ir.module_name)
    return (
        "[package]\n"
        f'name = "{package_name}"\n'
        'version = "0.0.0"\n'
        'edition = "2024"\n'
        "publish = false\n\n"
        "[lib]\n"
        f'name = "{extension_name}"\n'
        'crate-type = ["cdylib"]\n\n'
        "[dependencies]\n"
        f'{PYO3_CARGO_ALIAS} = {{ package = "pyo3", version = "={PYO3_VERSION}", '
        'features = ["extension-module"] }\n'
        f"{dependencies}\n"
        "[build-dependencies]\n"
        f'pyo3-build-config = {{ version = "={PYO3_VERSION}" }}\n\n'
        "[profile.release]\n"
        "overflow-checks = true\n"
        'panic = "unwind"\n'
    )


def _generated_package_name(compilation_unit: str) -> str:
    """Give every generated workspace a distinct Cargo package identity.

    Multiple standalone Crabwalk modules can intentionally share one project
    target directory. Cargo keys build-script and unit state partly by package
    identity, so a constant package name allowed one module to spuriously relink
    another on MSVC. The project-relative compilation-unit path is stable across
    dependency-lock bootstrap, fingerprint replanning, and normal builds while
    distinguishing unrelated single-file modules that are both named ``app``.
    Hashing it keeps the local package name short and Cargo-safe without creating
    a lock/fingerprint cycle.
    """

    digest = hashlib.sha256(compilation_unit.encode("utf-8")).hexdigest()[:24]
    return f"crabwalk-generated-{digest}"


def render_build_rs(extension_name: str) -> str:
    return (
        f"// Crabwalk extension unit: {extension_name}\n"
        'fn main() {\n    println!("cargo:rerun-if-changed=build.rs");\n'
        "    // MSVC otherwise embeds wall-clock PE/PDB identity when Cargo relinks.\n"
        '    #[cfg(all(target_os = "windows", target_env = "msvc"))]\n'
        '    println!("cargo:rustc-link-arg=/Brepro");\n'
        "    pyo3_build_config::add_extension_module_link_args();\n}\n"
    )


def cargo_dependency_specification(ir: PackageIR) -> dict[str, object]:
    """Return every generated Cargo dependency input in fingerprintable form."""

    return {
        "mandatory": [
            {
                "binding": PYO3_CARGO_ALIAS,
                "package": "pyo3",
                "version": f"={PYO3_VERSION}",
                "features": ["extension-module"],
            }
        ],
        "mandatory_build": [
            {
                "package": "pyo3-build-config",
                "version": f"={PYO3_VERSION}",
            }
        ],
        "declared": [
            {
                "binding": crate.binding,
                "cargo_key": cargo_dependency_key(crate.package, crate.binding),
                "package": crate.package,
                "version": crate.version,
                "features": list(crate.features),
                "path": crate.path,
                "git": crate.git,
                "rev": crate.rev,
            }
            for crate in sorted(ir.crates, key=lambda value: value.binding)
        ],
    }


def _cargo_dependencies(ir: PackageIR) -> str:
    lines: list[str] = []
    for dependency in sorted(ir.crates, key=lambda value: value.binding):
        cargo_key = cargo_dependency_key(dependency.package, dependency.binding)
        fields: list[str] = []
        if cargo_key != dependency.package:
            fields.append(f"package = {_toml_string(dependency.package)}")
        if dependency.version is not None:
            fields.append(f"version = {_toml_string(dependency.version)}")
        if dependency.path is not None:
            fields.append(f"path = {_toml_string(Path(dependency.path).as_posix())}")
        if dependency.git is not None:
            fields.append(f"git = {_toml_string(dependency.git)}")
        if dependency.rev is not None:
            fields.append(f"rev = {_toml_string(dependency.rev)}")
        if dependency.features:
            features = ", ".join(_toml_string(value) for value in dependency.features)
            fields.append(f"features = [{features}]")
        lines.append(f"{cargo_key} = {{ {', '.join(fields)} }}")
    return "\n".join(lines)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
