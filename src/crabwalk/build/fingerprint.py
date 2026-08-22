"""Build fingerprint construction."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import sysconfig
from functools import lru_cache
from pathlib import Path

from crabwalk import __version__
from crabwalk.compiler.codegen import CODEGEN_SCHEMA_VERSION, PYO3_VERSION
from crabwalk.compiler.ir import PackageIR

_BUILD_ENVIRONMENT_KEYS = (
    "AR",
    "CC",
    "CFLAGS",
    "CXX",
    "CXXFLAGS",
    "CARGO_BUILD_TARGET",
    "CARGO_ENCODED_RUSTFLAGS",
    "CARGO_HOME",
    "LDFLAGS",
    "MACOSX_DEPLOYMENT_TARGET",
    "PATH",
    "PYO3_CROSS",
    "PYO3_CROSS_LIB_DIR",
    "PYO3_CROSS_PYTHON_VERSION",
    "RUSTC",
    "RUSTC_LINKER",
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "RUSTFLAGS",
    "SDKROOT",
)


def build_fingerprint(
    ir: PackageIR,
    dependency_lock_hash: str | None = None,
    *,
    locked: bool = False,
    offline: bool = False,
    project_config_hash: str | None = None,
) -> tuple[str, dict[str, object]]:
    payload: dict[str, object] = {
        "fingerprint_schema": 2,
        "crabwalk_version": __version__,
        "implementation_hash": _implementation_hash(),
        "ir_schema": ir.schema_version,
        "codegen_schema": CODEGEN_SCHEMA_VERSION,
        "source_hash": ir.source_hash,
        "source_path_identity": Path(ir.source_path).name,
        "module_name": ir.module_name,
        "python": {
            "implementation": platform.python_implementation(),
            "version": list(sys.version_info[:3]),
            "abiflags": getattr(sys, "abiflags", ""),
            "extension_suffix": sysconfig.get_config_var("EXT_SUFFIX"),
        },
        "rustc": _rustc_version(),
        "cargo": _cargo_version(),
        "pyo3": PYO3_VERSION,
        "dependency_lock_hash": dependency_lock_hash,
        "cargo_policy": {"locked": locked, "offline": offline},
        "path_dependencies": {
            crate.binding: _path_dependency_hash(Path(crate.path))
            for crate in ir.crates
            if crate.path is not None
        },
        "profile": "release",
        "overflow_checks": True,
        "build_environment": _build_environment_fingerprint(),
        "cargo_configuration_hash": _cargo_configuration_hash(Path(ir.source_path)),
        "project_config_hash": project_config_hash,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), payload


def _path_dependency_hash(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(str(root.resolve()).encode("utf-8"))
    digest.update(b"\0")
    if not root.is_dir():
        return "missing"
    selected = {"Cargo.toml", "Cargo.lock", "build.rs"}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in {".git", ".crabwalk", "target"} for part in relative.parts):
            continue
        if path.name not in selected and path.suffix != ".rs":
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _rustc_version() -> str:
    try:
        return subprocess.check_output(
            ["rustc", "-vV"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=15,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


@lru_cache(maxsize=1)
def _cargo_version() -> str:
    try:
        return subprocess.check_output(
            ["cargo", "-vV"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=15,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _build_environment_fingerprint() -> dict[str, dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    for name in _BUILD_ENVIRONMENT_KEYS:
        value = os.environ.get(name)
        if value is None:
            continue
        values[name] = {
            "set": True,
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
    target_specific = sorted(
        name
        for name in os.environ
        if name.startswith(("CARGO_TARGET_", "CC_", "CXX_", "AR_"))
        and name not in values
    )
    for name in target_specific:
        value = os.environ[name]
        values[name] = {
            "set": True,
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
    return values


def _cargo_configuration_hash(source_path: Path) -> str:
    digest = hashlib.sha256()
    start = source_path.resolve().parent
    candidates: list[Path] = []
    for directory in (start, *start.parents):
        for name in ("config.toml", "config"):
            candidate = directory / ".cargo" / name
            if candidate.is_file():
                candidates.append(candidate)
    cargo_home = os.environ.get("CARGO_HOME")
    home = Path(cargo_home).resolve() if cargo_home else Path.home() / ".cargo"
    for name in ("config.toml", "config"):
        candidate = home / name
        if candidate.is_file() and candidate not in candidates:
            candidates.append(candidate)
    for index, path in enumerate(candidates):
        digest.update(str(index).encode("ascii"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _implementation_hash() -> str:
    package_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(package_root.rglob("*.py")):
        digest.update(path.relative_to(package_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
