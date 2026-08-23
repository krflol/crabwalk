"""Command-line interface for Crabwalk."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path
from typing import Sequence

from crabwalk import __version__
from crabwalk.diagnostics import CrabwalkCompilationError
from crabwalk.service import default_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="crabwalk")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check Python and Rust build readiness")
    for name in ("expand", "check", "build"):
        command = commands.add_parser(name)
        command.add_argument("path", type=Path)
        command.add_argument("--module-name")
        command.add_argument("--project", type=Path)
        command.add_argument("--locked", action="store_true")
        command.add_argument("--offline", action="store_true")
    inspect_command = commands.add_parser(
        "inspect",
        help="classify compiled functions and build inputs",
    )
    inspect_command.add_argument("path", type=Path)
    inspect_command.add_argument("--module-name")
    inspect_command.add_argument("--project", type=Path)
    inspect_command.add_argument("--json", action="store_true")
    inspect_command.add_argument("--locked", action="store_true")
    inspect_command.add_argument("--offline", action="store_true")
    show_command = commands.add_parser(
        "show",
        help="show generated Rust for one function",
    )
    show_command.add_argument("path", type=Path)
    show_command.add_argument("symbol")
    show_command.add_argument("--module-name")
    show_command.add_argument("--project", type=Path)
    show_command.add_argument("--locked", action="store_true")
    show_command.add_argument("--offline", action="store_true")
    wheel_command = commands.add_parser(
        "wheel",
        help="build a platform wheel with an embedded native extension",
    )
    wheel_command.add_argument("path", type=Path)
    wheel_command.add_argument("--output-dir", type=Path, default=Path("dist"))
    wheel_command.add_argument("--name")
    wheel_command.add_argument("--version", default="0.0.0")
    wheel_command.add_argument("--locked", action="store_true")
    wheel_command.add_argument("--offline", action="store_true")
    cache_command = commands.add_parser("cache", help="inspect or prune artifact cache")
    cache_commands = cache_command.add_subparsers(dest="cache_command", required=True)
    cache_status = cache_commands.add_parser(
        "status", help="show cache state for source"
    )
    cache_status.add_argument("path", type=Path)
    cache_status.add_argument("--module-name")
    cache_status.add_argument("--project", type=Path)
    cache_status.add_argument("--json", action="store_true")
    cache_status.add_argument("--locked", action="store_true")
    cache_status.add_argument("--offline", action="store_true")
    cache_prune = cache_commands.add_parser(
        "prune", help="remove old/bounded artifacts"
    )
    cache_prune.add_argument("path", type=Path, nargs="?", default=Path.cwd())
    cache_prune.add_argument("--max-bytes", type=int, default=2 * 1024 * 1024 * 1024)
    cache_prune.add_argument("--max-age-days", type=float, default=30.0)
    cache_prune.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "doctor":
        return _doctor()
    if arguments.command == "wheel":
        from crabwalk.wheel import build_wheel

        try:
            result = build_wheel(
                arguments.path,
                arguments.output_dir,
                distribution_name=arguments.name,
                version=arguments.version,
                locked=arguments.locked,
                offline=arguments.offline,
            )
        except CrabwalkCompilationError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(result.path)
        return 0
    if arguments.command == "cache":
        return _cache(arguments)
    try:
        mode = (
            "expand" if arguments.command in {"inspect", "show"} else arguments.command
        )
        result = default_service.compile_path(
            arguments.path,
            module_name=arguments.module_name,
            mode=mode,
            load=False,
            locked=arguments.locked,
            offline=arguments.offline,
            project=arguments.project,
        )
    except CrabwalkCompilationError as error:
        print(str(error), file=sys.stderr)
        return 1
    if arguments.command == "inspect":
        _inspect(result, arguments.json)
    elif arguments.command == "show":
        return _show(result, arguments.symbol)
    elif arguments.command == "expand":
        print(result.generated_dir / "src" / "lib.rs")
    elif arguments.command == "check":
        print(f"checked {result.ir.module_name} ({result.fingerprint[:16]})")
    else:
        state = "cache hit" if result.cache_hit else "built"
        print(f"{state}: {result.artifact}")
    return 0


def _cache(arguments: argparse.Namespace) -> int:
    if arguments.cache_command == "status":
        try:
            result = default_service.compile_path(
                arguments.path,
                module_name=arguments.module_name,
                mode="expand",
                load=False,
                locked=arguments.locked,
                offline=arguments.offline,
                project=arguments.project,
            )
        except CrabwalkCompilationError as error:
            print(str(error), file=sys.stderr)
            return 1
        from crabwalk.inspection import compilation_inspection

        cache = compilation_inspection(result)["cache"]
        if arguments.json:
            print(json.dumps(cache, indent=2, sort_keys=True))
        else:
            print(f"{cache['status']}: {cache['artifact']}")
            if cache["reason"]:
                print(f"reason: {cache['reason']}")
        return 0

    from crabwalk.build.cache import prune_artifact_cache
    from crabwalk.service import find_project_root

    try:
        outcome = prune_artifact_cache(
            find_project_root(arguments.path) / ".crabwalk",
            max_bytes=arguments.max_bytes,
            max_age_seconds=arguments.max_age_days * 24 * 60 * 60,
            dry_run=arguments.dry_run,
        )
    except (OSError, ValueError) as error:
        print(f"CRAB305 Cache pruning failed\n\n{error}", file=sys.stderr)
        return 1
    action = "would remove" if outcome.dry_run else "removed"
    if outcome.bytes_remaining is None:
        remaining = (
            f"at least {outcome.bytes_remaining_known} known bytes; "
            f"{outcome.busy_entries} busy entries unmeasured"
        )
    else:
        remaining = f"{outcome.bytes_remaining} bytes"
    print(
        f"{action} {len(outcome.removed)} entries "
        f"({outcome.bytes_reclaimed} bytes); "
        f"{outcome.entries_remaining} entries remain "
        f"({remaining})"
    )
    if outcome.limit_satisfied is None and arguments.max_bytes is not None:
        print("byte limit status is unknown while cache entries are busy")
    elif outcome.limit_satisfied is False:
        print("byte limit is not satisfied because selected entries remain busy")
    for path in outcome.removed:
        print(path)
    return 0


def _inspect(result: object, as_json: bool) -> None:
    from crabwalk.service import CompilationResult
    from crabwalk.inspection import compilation_inspection

    if not isinstance(result, CompilationResult):
        raise TypeError("expected a CompilationResult")
    payload = compilation_inspection(result)
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"module: {payload['module']}")
    print(f"fingerprint: {payload['fingerprint']}")
    cache = payload["cache"]
    print(f"cache: {cache['status']} ({cache['artifact']})")
    print(f"sources: {len(payload['source_files'])}")
    if payload["build_command"]:
        print(f"build command: {' '.join(payload['build_command'])}")
    for crate in payload["crates"]:
        print(
            f"crate {crate['binding']}: {crate['package']} "
            f"{crate['version'] or crate['path'] or crate['git']}"
        )
    for function in payload["functions"]:
        parameters = ", ".join(
            f"{item['name']}: {item['type']}" for item in function["parameters"]
        )
        print(
            f"{function['name']}({parameters}) -> "
            f"{function['return_type']}: {', '.join(function['effects'])}"
        )
        print(f"  GIL: {function['gil']}")
        for parameter in function["parameters"]:
            conversion = parameter["conversion"]
            print(
                f"  input {parameter['name']}: {conversion['kind']} "
                f"({conversion['cost']})"
            )
        conversion = function["return_conversion"]
        print(f"  return: {conversion['kind']} ({conversion['cost']})")
        for call in function["python_calls"]:
            source = call["source"]
            print(f"  Python call: {call['name']} at {source['path']}:{source['line']}")


def _show(result: object, symbol: str) -> int:
    from crabwalk.service import CompilationResult
    from crabwalk.inspection import function_inspection

    if not isinstance(result, CompilationResult):
        raise TypeError("expected a CompilationResult")
    matches = [
        function
        for function in result.ir.functions
        if symbol in {function.name, function.qualified_name, function.rust_symbol}
    ]
    if len(matches) != 1:
        choices = ", ".join(function.qualified_name for function in result.ir.functions)
        reason = "ambiguous" if matches else "unknown"
        print(
            f"CRAB125 {reason} Rust function {symbol}; available: {choices}",
            file=sys.stderr,
        )
        return 1
    function = matches[0]
    details = function_inspection(function)
    source = (result.generated_dir / "src" / "lib.rs").read_text(encoding="utf-8")
    lines = source.splitlines()
    native = _rust_item(lines, f"fn __cw_native_{function.rust_symbol}(")
    wrapper = _rust_item(lines, f"fn {function.rust_symbol}(")
    print(f"// Python symbol: {function.qualified_name}")
    print(f"// Native symbol: {function.rust_symbol}")
    print(f"// Effects: {', '.join(details['effects'])}")
    print(f"// GIL: {details['gil']}")
    for parameter in details["parameters"]:
        conversion = parameter["conversion"]
        print(
            f"// Input {parameter['name']}: {conversion['detail']} "
            f"[{conversion['cost']}]"
        )
    conversion = details["return_conversion"]
    print(f"// Return: {conversion['detail']} [{conversion['cost']}]")
    print("\n// Native implementation")
    print("\n".join(native))
    print("\n// Python ABI wrapper")
    print("\n".join(wrapper))
    return 0


def _rust_item(lines: list[str], marker: str) -> list[str]:
    start = next(index for index, line in enumerate(lines) if marker in line)
    while start > 0 and lines[start - 1].lstrip().startswith("#["):
        start -= 1
    depth = 0
    opened = False
    selected: list[str] = []
    for line in lines[start:]:
        selected.append(line)
        if "{" in line:
            opened = True
        depth += line.count("{") - line.count("}")
        if opened and depth == 0:
            break
    return selected


def _doctor() -> int:
    failures = 0
    print(f"Crabwalk {__version__}")
    implementation = platform.python_implementation()
    print(f"Python {platform.python_version()} ({implementation})")
    print(f"executable: {sys.executable}")
    print(f"platform: {sysconfig.get_platform()}")
    print(f"SOABI: {sysconfig.get_config_var('SOABI') or 'unavailable'}")
    print(
        f"extension suffix: {sysconfig.get_config_var('EXT_SUFFIX') or 'unavailable'}"
    )
    if implementation != "CPython":
        print("CRAB006 unsupported interpreter: CPython is required", file=sys.stderr)
        failures += 1
    if sys.version_info < (3, 11):
        print("CRAB006 unsupported Python: version 3.11+ is required", file=sys.stderr)
        failures += 1
    for executable in ("rustc", "cargo"):
        resolved = shutil.which(executable)
        if resolved is None:
            print(f"CRAB003 missing tool: {executable}", file=sys.stderr)
            failures += 1
            continue
        try:
            output = subprocess.check_output(
                [resolved, "-vV"],
                text=True,
                stderr=subprocess.STDOUT,
                timeout=15,
            ).strip()
        except (OSError, subprocess.SubprocessError) as error:
            print(f"CRAB004 cannot run {executable}: {error}", file=sys.stderr)
            failures += 1
        else:
            print(output)
    include = Path(sysconfig.get_path("include"))
    python_header = include / "Python.h"
    if python_header.is_file():
        print(f"Python headers: {python_header}")
    else:
        print(f"CRAB007 missing Python headers: {python_header}", file=sys.stderr)
        failures += 1
    if shutil.which("rustc") is not None:
        probe_error = _linker_probe()
        if probe_error is None:
            print("native linker probe: ok")
        else:
            print(f"CRAB008 native linker probe failed: {probe_error}", file=sys.stderr)
            failures += 1
    temporary = Path(tempfile.gettempdir())
    writable = os.access(temporary, os.W_OK)
    print(
        f"temporary build directory: {temporary} ({'writable' if writable else 'not writable'})"
    )
    if not writable:
        failures += 1
    return 1 if failures else 0


def _linker_probe() -> str | None:
    try:
        with tempfile.TemporaryDirectory(prefix="crabwalk-doctor-") as value:
            directory = Path(value)
            source = directory / "probe.rs"
            source.write_text(
                'pub extern "C" fn crabwalk_doctor_probe() -> u8 { 1 }\n',
                encoding="utf-8",
            )
            suffix = (
                ".dll"
                if os.name == "nt"
                else ".dylib"
                if sys.platform == "darwin"
                else ".so"
            )
            output = directory / f"crabwalk_doctor_probe{suffix}"
            process = subprocess.run(
                ["rustc", "--crate-type", "cdylib", str(source), "-o", str(output)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            if process.returncode != 0:
                return (process.stderr or process.stdout).strip()
            if not output.is_file():
                return "rustc reported success without producing a cdylib"
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
