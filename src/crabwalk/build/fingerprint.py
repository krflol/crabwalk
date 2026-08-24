"""Build fingerprint construction."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from functools import lru_cache
from pathlib import Path

from crabwalk import __version__
from crabwalk.compiler.codegen import (
    CODEGEN_SCHEMA_VERSION,
    PYO3_VERSION,
    cargo_dependency_specification,
)
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
    "OPENSSL_DIR",
    "OPENSSL_INCLUDE_DIR",
    "OPENSSL_LIB_DIR",
    "PATH",
    "PKG_CONFIG_PATH",
    "PYO3_CONFIG_FILE",
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
    project_root: Path | None = None,
    extra_files: tuple[Path, ...] = (),
    extra_env: tuple[str, ...] = (),
) -> tuple[str, dict[str, object]]:
    toolchain_root = (project_root or Path(ir.source_path).parent).resolve()
    toolchain_files_hash = _toolchain_files_hash(toolchain_root)
    payload: dict[str, object] = {
        "fingerprint_schema": 5,
        "crabwalk_version": __version__,
        "implementation_hash": _implementation_hash(),
        "ir_schema": ir.schema_version,
        "codegen_schema": CODEGEN_SCHEMA_VERSION,
        "compiler_input_hash": ir.compiler_input_hash,
        "source_path_identity": Path(ir.source_path).name,
        "module_name": ir.module_name,
        "python": {
            "implementation": platform.python_implementation(),
            "version": list(sys.version_info[:3]),
            "abiflags": getattr(sys, "abiflags", ""),
            "extension_suffix": sysconfig.get_config_var("EXT_SUFFIX"),
        },
        "rustc": _tool_version("rustc", toolchain_root, toolchain_files_hash),
        "cargo": _tool_version("cargo", toolchain_root, toolchain_files_hash),
        "toolchain_files": toolchain_files_hash,
        "pyo3": PYO3_VERSION,
        "generated_dependencies": cargo_dependency_specification(ir),
        "dependency_lock_hash": dependency_lock_hash,
        "cargo_policy": {"locked": locked, "offline": offline},
        "path_dependencies": {
            crate.binding: _path_dependency_hash(Path(crate.path))
            for crate in ir.crates
            if crate.path is not None
        },
        "profile": "release",
        "overflow_checks": True,
        "panic_strategy": "unwind",
        "build_environment": _build_environment_fingerprint(extra_env),
        "extra_files": {
            str(path.resolve()): _input_tree_hash(path)
            for path in sorted(extra_files, key=lambda value: str(value.resolve()))
        },
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
    return _input_tree_hash(root)


def _input_tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(str(root.resolve()).encode("utf-8"))
    digest.update(b"\0")
    if root.is_file():
        digest.update(root.read_bytes())
        return digest.hexdigest()
    if not root.is_dir():
        return "missing"
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in {".git", ".crabwalk", "target"} for part in relative.parts):
            continue
        if path.is_symlink():
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0symlink\0")
            digest.update(os.readlink(path).encode("utf-8"))
            digest.update(b"\0")
            continue
        if not path.is_file():
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _tool_version(
    command: str,
    cwd: Path,
    toolchain_files_hash: str | None = None,
) -> str:
    resolved_cwd = cwd.resolve()
    executable = shutil.which(command) or command
    executable_state = _file_state(Path(executable))
    local_toolchain_hash = (
        toolchain_files_hash
        if toolchain_files_hash is not None
        else _toolchain_files_hash(resolved_cwd)
    )
    return _cached_tool_version(
        command,
        str(resolved_cwd),
        executable,
        executable_state,
        local_toolchain_hash,
        _rustup_state_hash(command),
    )


@lru_cache(maxsize=256)
def _cached_tool_version(
    command: str,
    cwd: str,
    executable: str,
    executable_state: tuple[int, int, int] | None,
    toolchain_files_hash: str,
    rustup_state_hash: str,
) -> str:
    # The state arguments intentionally participate in the cache key. They make
    # this a project/toolchain-aware optimization rather than the old global
    # one-entry memo that could survive a local override or rustup update.
    del command, executable_state, toolchain_files_hash, rustup_state_hash
    try:
        return subprocess.check_output(
            [executable, "-vV"],
            cwd=Path(cwd),
            text=True,
            stderr=subprocess.STDOUT,
            timeout=15,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _file_state(path: Path) -> tuple[int, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _rustup_state_hash(command: str) -> str:
    digest = hashlib.sha256()
    for name in ("RUSTUP_TOOLCHAIN", "RUSTUP_HOME"):
        digest.update(name.encode("ascii"))
        digest.update(b"\0")
        digest.update(os.environ.get(name, "").encode("utf-8"))
        digest.update(b"\0")
    rustup_home_value = os.environ.get("RUSTUP_HOME")
    rustup_home = (
        Path(rustup_home_value).expanduser()
        if rustup_home_value
        else Path.home() / ".rustup"
    )
    settings = rustup_home / "settings.toml"
    if settings.is_file():
        digest.update(settings.read_bytes())
    executable_name = f"{command}.exe" if os.name == "nt" else command
    toolchains = rustup_home / "toolchains"
    if toolchains.is_dir():
        for directory in sorted(toolchains.iterdir(), key=lambda path: path.name):
            executable = directory / "bin" / executable_name
            state = _file_state(executable)
            if state is None:
                continue
            digest.update(directory.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(repr(state).encode("ascii"))
            digest.update(b"\0")
    return digest.hexdigest()


def _build_environment_fingerprint(
    extra_keys: tuple[str, ...] = (),
) -> dict[str, dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    names = set(_BUILD_ENVIRONMENT_KEYS) | set(extra_keys)
    names.update(name for name in os.environ if name.startswith("CARGO_PROFILE_"))
    # This variable is forced to unwind by CargoBuilder and must not let an
    # ambient abort request create a separate, misleading cache identity.
    names.discard("CARGO_PROFILE_RELEASE_PANIC")
    for name in sorted(names):
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


def _toolchain_files_hash(project_root: Path) -> str:
    digest = hashlib.sha256()
    candidates: list[Path] = []
    for directory in (project_root, *project_root.parents):
        for name in ("rust-toolchain.toml", "rust-toolchain"):
            candidate = directory / name
            if candidate.is_file():
                candidates.append(candidate)
        if candidates:
            break
    for path in candidates:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


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


def _implementation_hash() -> str:
    package_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(package_root.rglob("*.py")):
        digest.update(path.relative_to(package_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
