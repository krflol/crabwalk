"""Cargo subprocess integration using JSON build messages."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class CargoOutcome:
    command: tuple[str, ...]
    messages: tuple[dict[str, Any], ...]
    stdout: str
    stderr: str
    artifact: Path | None
    artifact_fresh: bool | None = None


class CargoBuildFailure(Exception):
    def __init__(
        self,
        command: tuple[str, ...],
        messages: tuple[dict[str, Any], ...],
        stdout: str,
        stderr: str,
        returncode: int | None,
        cause: BaseException | None = None,
    ):
        self.command = command
        self.messages = messages
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.cause = cause
        super().__init__(f"Cargo command failed ({returncode}): {' '.join(command)}")


class CargoBuildCancelled(Exception):
    """Raised after Crabwalk has terminated a running Cargo process tree."""

    def __init__(self, command: tuple[str, ...]) -> None:
        self.command = command
        super().__init__(f"Cargo command cancelled: {' '.join(command)}")


class CargoBuilder:
    @staticmethod
    def command_for(
        target_dir: Path,
        mode: Literal["check", "build"],
        *,
        locked: bool = False,
        offline: bool = False,
    ) -> tuple[str, ...]:
        return (
            "cargo",
            mode,
            "--release",
            "--message-format=json",
            "--target-dir",
            str(target_dir),
            *(("--locked",) if locked else ()),
            *(("--offline",) if offline else ()),
        )

    def generate_lockfile(
        self,
        project_dir: Path,
        *,
        offline: bool = False,
        cancelled: Callable[[], bool] | None = None,
    ) -> CargoOutcome:
        command = (
            "cargo",
            "generate-lockfile",
            *(("--offline",) if offline else ()),
        )
        environment = os.environ.copy()
        environment["CARGO_TERM_COLOR"] = "never"
        try:
            process = _run_command(
                command, project_dir, environment, cancelled=cancelled
            )
        except CargoBuildCancelled:
            raise
        except (OSError, subprocess.SubprocessError) as error:
            raise CargoBuildFailure(
                command,
                (),
                "",
                str(error),
                None,
                error,
            ) from error
        if process.returncode != 0:
            raise CargoBuildFailure(
                command,
                (),
                process.stdout,
                process.stderr,
                process.returncode,
            )
        return CargoOutcome(command, (), process.stdout, process.stderr, None)

    def run(
        self,
        project_dir: Path,
        target_dir: Path,
        extension_name: str,
        mode: Literal["check", "build"],
        *,
        locked: bool = False,
        offline: bool = False,
        cancelled: Callable[[], bool] | None = None,
    ) -> CargoOutcome:
        target_dir.mkdir(parents=True, exist_ok=True)
        command = self.command_for(
            target_dir,
            mode,
            locked=locked,
            offline=offline,
        )
        environment = os.environ.copy()
        environment["PYO3_PYTHON"] = sys.executable
        environment["PYO3_BUILD_EXTENSION_MODULE"] = "1"
        environment["CARGO_TERM_COLOR"] = "never"
        # Crabwalk's Python exception boundary relies on Rust unwinding. Cargo
        # profile environment variables outrank Cargo.toml, so force the same
        # invariant here rather than allowing an ambient `panic=abort` override.
        environment["CARGO_PROFILE_RELEASE_PANIC"] = "unwind"
        try:
            process = _run_command(
                command, project_dir, environment, cancelled=cancelled
            )
        except CargoBuildCancelled:
            raise
        except (OSError, subprocess.SubprocessError) as error:
            raise CargoBuildFailure(
                command,
                (),
                "",
                str(error),
                None,
                error,
            ) from error

        messages = tuple(_parse_messages(process.stdout))
        if process.returncode != 0:
            raise CargoBuildFailure(
                command,
                messages,
                process.stdout,
                process.stderr,
                process.returncode,
            )
        artifact_event = (
            _find_artifact_event(messages, extension_name) if mode == "build" else None
        )
        artifact = _artifact_path(artifact_event)
        if mode == "build" and artifact is None:
            raise CargoBuildFailure(
                command,
                messages,
                process.stdout,
                "Cargo succeeded but did not report the generated cdylib artifact.",
                process.returncode,
            )
        artifact_fresh = (
            artifact_event.get("fresh")
            if artifact_event is not None
            and isinstance(artifact_event.get("fresh"), bool)
            else None
        )
        return CargoOutcome(
            command,
            messages,
            process.stdout,
            process.stderr,
            artifact,
            artifact_fresh,
        )


def _run_command(
    command: tuple[str, ...],
    project_dir: Path,
    environment: dict[str, str],
    *,
    cancelled: Callable[[], bool] | None,
) -> subprocess.CompletedProcess[str]:
    """Run Cargo, optionally polling a hard-cancellation callback.

    The ordinary path deliberately retains ``subprocess.run`` so existing build
    integrations and tests keep their simple contract. Embedders that provide a
    callback receive a process-group-backed lifecycle: Crabwalk kills Cargo and
    every rustc/build-script child before reporting cancellation.
    """

    if cancelled is None:
        return subprocess.run(
            command,
            cwd=project_dir,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )

    creationflags = (
        int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        if os.name == "nt"
        else 0
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=project_dir,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    started = time.monotonic()
    while True:
        if cancelled():
            _terminate_process_tree(process)
            process.communicate()
            raise CargoBuildCancelled(command)
        remaining = 600.0 - (time.monotonic() - started)
        if remaining <= 0:
            _terminate_process_tree(process)
            stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(command, 600, stdout, stderr)
        try:
            stdout, stderr = process.communicate(timeout=min(0.1, remaining))
            return subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr
            )
        except subprocess.TimeoutExpired:
            continue


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate one exact Cargo process tree without touching unrelated work."""

    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=10,
        )
    else:
        kill_process_group = getattr(os, "killpg", None)
        if kill_process_group is None:
            process.terminate()
            return
        try:
            kill_process_group(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                kill_process_group(process.pid, getattr(signal, "SIGKILL", 9))
            except ProcessLookupError:
                pass


def _parse_messages(output: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            messages.append(value)
    return messages


def _find_artifact_event(
    messages: tuple[dict[str, Any], ...], extension_name: str
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for event in messages:
        if event.get("reason") != "compiler-artifact":
            continue
        target = event.get("target")
        if not isinstance(target, dict) or target.get("name") != extension_name:
            continue
        candidates.append(event)
    return candidates[-1] if candidates else None


def _artifact_path(event: dict[str, Any] | None) -> Path | None:
    if event is None:
        return None
    suffixes = {".dll", ".so", ".dylib"}
    candidates: list[Path] = []
    filenames = event.get("filenames")
    if not isinstance(filenames, list):
        return None
    for filename in filenames:
        path = Path(str(filename))
        if path.suffix.lower() in suffixes:
            candidates.append(path)
    return candidates[-1] if candidates else None
