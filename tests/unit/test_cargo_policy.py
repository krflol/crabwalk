from __future__ import annotations

import json
import subprocess
import os
import time
from pathlib import Path
from types import ModuleType

import pytest

from crabwalk.build.cargo import CargoBuilder, CargoOutcome
from crabwalk.build.cache import prune_artifact_cache
from crabwalk.diagnostics import CrabwalkCompilationError
from crabwalk.service import CompilationService


def test_cargo_builder_records_the_reported_artifact_freshness(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    artifact = tmp_path / "fresh.dll"
    artifact.write_bytes(b"native")
    message = json.dumps(
        {
            "reason": "compiler-artifact",
            "target": {"name": "_crabwalk_test"},
            "filenames": [str(artifact)],
            "fresh": True,
        }
    )

    def fake_run(
        command: tuple[str, ...],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, message, "")

    monkeypatch.setattr(subprocess, "run", fake_run)  # type: ignore[attr-defined]

    outcome = CargoBuilder().run(
        tmp_path,
        tmp_path / "target",
        "_crabwalk_test",
        "build",
    )

    assert outcome.artifact == artifact
    assert outcome.artifact_fresh is True


def test_cargo_builder_overrides_abort_profile_for_panic_boundary(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    captured: dict[str, str] = {}

    def fake_run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        env: dict[str, str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del cwd
        captured.update(env)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setenv("CARGO_PROFILE_RELEASE_PANIC", "abort")  # type: ignore[attr-defined]
    monkeypatch.setattr(subprocess, "run", fake_run)  # type: ignore[attr-defined]

    CargoBuilder().run(
        tmp_path,
        tmp_path / "target",
        "_crabwalk_test",
        "check",
    )

    assert captured["CARGO_PROFILE_RELEASE_PANIC"] == "unwind"


class _RecordingCargo(CargoBuilder):
    def __init__(self) -> None:
        self.locked_values: list[bool] = []
        self.update_once = False
        self.generate_count = 0

    def generate_lockfile(
        self,
        project_dir: Path,
        *,
        offline: bool = False,
    ) -> CargoOutcome:
        del offline
        self.generate_count += 1
        (project_dir / "Cargo.lock").write_text(
            "version = 4\n# initial\n", encoding="utf-8"
        )
        return CargoOutcome(("cargo", "generate-lockfile"), (), "", "", None)

    def run(
        self,
        project_dir: Path,
        target_dir: Path,
        extension_name: str,
        mode: str,
        *,
        locked: bool = False,
        offline: bool = False,
    ) -> CargoOutcome:
        del target_dir, extension_name, mode, offline
        self.locked_values.append(locked)
        if self.update_once:
            (project_dir / "Cargo.lock").write_text(
                "version = 4\n# updated\n", encoding="utf-8"
            )
            self.update_once = False
        return CargoOutcome(("cargo", "check"), (), "", "", None)


def test_dependency_locks_update_by_default_and_locked_mode_is_explicit(
    tmp_path: Path,
) -> None:
    source = tmp_path / "dependency.py"
    source.write_text(
        """\
from crabwalk import rust
regex = rust.crate("regex", version="1")

@rust.fn
def matches(value: rust.Str) -> rust.bool:
    return regex.Regex.new("x").unwrap().is_match(value)
""",
        encoding="utf-8",
    )
    cargo = _RecordingCargo()
    service = CompilationService(cargo)

    first = service.compile_path(source, mode="check")
    assert cargo.locked_values == [False]
    assert first.planned_command is not None
    assert "--locked" not in first.planned_command

    cargo.update_once = True
    cargo.locked_values.clear()
    refreshed = service.compile_path(source, mode="check")
    assert cargo.locked_values == [False, False]
    assert refreshed.fingerprint != first.fingerprint

    cargo.locked_values.clear()
    locked = service.compile_path(source, mode="check", locked=True)
    assert cargo.locked_values == [True]
    assert locked.planned_command is not None
    assert "--locked" in locked.planned_command


def test_mandatory_pyo3_graph_is_locked_without_user_crates(tmp_path: Path) -> None:
    source = tmp_path / "mandatory.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    cargo = _RecordingCargo()
    service = CompilationService(cargo)

    first = service.compile_path(source, mode="check")
    cargo.locked_values.clear()
    second = service.compile_path(source, mode="check", locked=True)

    assert cargo.generate_count == 1
    assert first.build_inputs is not None
    assert first.build_inputs["dependency_lock_hash"] is not None
    assert first.build_inputs["generated_dependencies"]
    assert second.fingerprint != first.fingerprint
    assert cargo.locked_values == [True]


class _ArtifactCargo(CargoBuilder):
    def __init__(self) -> None:
        self.run_count = 0

    def generate_lockfile(
        self,
        project_dir: Path,
        *,
        offline: bool = False,
    ) -> CargoOutcome:
        del offline
        (project_dir / "Cargo.lock").write_text(
            "version = 4\n# fixed\n", encoding="utf-8"
        )
        return CargoOutcome(("cargo", "generate-lockfile"), (), "", "", None)

    def run(
        self,
        project_dir: Path,
        target_dir: Path,
        extension_name: str,
        mode: str,
        *,
        locked: bool = False,
        offline: bool = False,
    ) -> CargoOutcome:
        del target_dir, mode, locked, offline
        self.run_count += 1
        artifact = project_dir / f"{extension_name}.native"
        artifact.write_bytes(b"native test artifact")
        return CargoOutcome(("cargo", "build"), (), "", "", artifact)


def test_loaded_result_is_reused_only_after_complete_fingerprinting(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    source = tmp_path / "loaded.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    cargo = _ArtifactCargo()
    loaded_modules: list[ModuleType] = []

    def fake_load(extension_name: str, artifact: Path) -> ModuleType:
        assert artifact.is_file()
        module = ModuleType(extension_name)
        loaded_modules.append(module)
        return module

    monkeypatch.setattr("crabwalk.service.load_extension", fake_load)  # type: ignore[attr-defined]
    service = CompilationService(cargo)

    first = service.compile_path(source, load=True)
    # A separate service must share the process-wide loaded-extension identity;
    # otherwise it can attempt to replace an already mapped DLL on Windows.
    second = CompilationService(cargo).compile_path(source, load=True)

    assert first.fingerprint == second.fingerprint
    assert second.module is first.module
    assert second.cache_status == "in-process"
    assert cargo.run_count == 1
    assert len(loaded_modules) == 1


def test_no_user_crate_cache_hit_is_still_validated_by_cargo(tmp_path: Path) -> None:
    source = tmp_path / "validated.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    cargo = _ArtifactCargo()
    service = CompilationService(cargo)

    service.compile_path(source)
    second = service.compile_path(source)

    assert second.cache_hit
    assert cargo.run_count == 2


class _LockChangingArtifactCargo(_ArtifactCargo):
    def __init__(self) -> None:
        super().__init__()
        self.build_fingerprints: list[str] = []

    def run(
        self,
        project_dir: Path,
        target_dir: Path,
        extension_name: str,
        mode: str,
        *,
        locked: bool = False,
        offline: bool = False,
    ) -> CargoOutcome:
        del target_dir, mode, locked, offline
        self.run_count += 1
        self.build_fingerprints.append(project_dir.name)
        if self.run_count == 1:
            (project_dir / "Cargo.lock").write_text(
                "version = 4\n# updated\n", encoding="utf-8"
            )
        artifact = project_dir / f"{extension_name}.native"
        artifact.write_bytes(b"native updated graph")
        return CargoOutcome(("cargo", "build"), (), "", "", artifact)


def test_lock_update_never_publishes_under_the_old_fingerprint(
    tmp_path: Path,
) -> None:
    source = tmp_path / "lock_update_build.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    cargo = _LockChangingArtifactCargo()

    result = CompilationService(cargo).compile_path(source)

    assert cargo.run_count == 2
    old_fingerprint, new_fingerprint = cargo.build_fingerprints
    assert result.fingerprint == new_fingerprint
    assert old_fingerprint != new_fingerprint
    assert not (
        tmp_path / ".crabwalk" / "cache" / "artifacts" / old_fingerprint
    ).exists()


def test_dependency_lock_replanning_is_bounded(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    source = tmp_path / "unstable_lock.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    cargo = _ArtifactCargo()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "crabwalk.service._lock_hash_changed",
        lambda *_arguments: True,
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        CompilationService(cargo).compile_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB308"
    assert "3 build plans" in diagnostic.message
    assert cargo.run_count == 0


def test_repaired_entry_refreshes_access_before_pruning(tmp_path: Path) -> None:
    source = tmp_path / "repair.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    cargo = _ArtifactCargo()
    service = CompilationService(cargo)
    first = service.compile_path(source)
    service.compile_path(source)
    assert first.artifact is not None

    entry = first.artifact.parent
    first.artifact.write_bytes(b"corrupt")
    old = time.time() - 10_000
    for path in (
        first.artifact,
        entry / "artifact-manifest.json",
        entry / ".last-access",
    ):
        os.utime(path, (old, old))
    (entry / ".last-access").write_text(
        f"{int(old * 1_000_000_000)}\n", encoding="utf-8"
    )
    os.utime(entry / ".last-access", (old, old))

    repaired = service.compile_path(source)
    pruned = prune_artifact_cache(
        tmp_path / ".crabwalk",
        max_bytes=None,
        max_age_seconds=60,
    )

    assert repaired.artifact == first.artifact
    assert pruned.removed == ()
    assert first.artifact.is_file()


class _ChangingArtifactCargo(CargoBuilder):
    def __init__(self) -> None:
        self.run_count = 0

    def generate_lockfile(
        self,
        project_dir: Path,
        *,
        offline: bool = False,
    ) -> CargoOutcome:
        del offline
        (project_dir / "Cargo.lock").write_text(
            "version = 4\n# fixed\n", encoding="utf-8"
        )
        return CargoOutcome(("cargo", "generate-lockfile"), (), "", "", None)

    def run(
        self,
        project_dir: Path,
        target_dir: Path,
        extension_name: str,
        mode: str,
        *,
        locked: bool = False,
        offline: bool = False,
    ) -> CargoOutcome:
        del target_dir, mode, locked, offline
        self.run_count += 1
        artifact = project_dir / f"{extension_name}.native"
        artifact.write_bytes(f"native-{self.run_count}".encode())
        return CargoOutcome(("cargo", "build"), (), "", "", artifact)


def test_changed_cargo_output_under_same_fingerprint_is_rejected(
    tmp_path: Path,
) -> None:
    source = tmp_path / "undeclared.py"
    source.write_text(
        """\
from crabwalk import rust

dependency = rust.crate("example-dependency", version="1")

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    cargo = _ChangingArtifactCargo()
    service = CompilationService(cargo)
    service.compile_path(source)

    with pytest.raises(CrabwalkCompilationError) as captured:
        service.compile_path(source)

    assert captured.value.diagnostics[0].code == "CRAB306"
    assert cargo.run_count == 2


class _FreshChangingArtifactCargo(_ChangingArtifactCargo):
    def run(
        self,
        project_dir: Path,
        target_dir: Path,
        extension_name: str,
        mode: str,
        *,
        locked: bool = False,
        offline: bool = False,
    ) -> CargoOutcome:
        outcome = super().run(
            project_dir,
            target_dir,
            extension_name,
            mode,
            locked=locked,
            offline=offline,
        )
        return CargoOutcome(
            outcome.command,
            outcome.messages,
            outcome.stdout,
            outcome.stderr,
            outcome.artifact,
            artifact_fresh=True,
        )


def test_verified_cache_wins_when_cargo_reports_a_fresh_target_copy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "fresh_target.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.fn
def identity(value: rust.u64) -> rust.u64:
    return value
""",
        encoding="utf-8",
    )
    cargo = _FreshChangingArtifactCargo()
    service = CompilationService(cargo)

    first = service.compile_path(source)
    second = service.compile_path(source)

    assert first.artifact is not None
    assert second.artifact == first.artifact
    assert second.cache_hit is True
    assert first.artifact.read_bytes() == b"native-1"
    assert cargo.run_count == 2
