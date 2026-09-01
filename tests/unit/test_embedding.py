from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import ModuleType

import pytest

import crabwalk
import crabwalk.embedding as embedding
from crabwalk.compiler.frontend import analyze_project_path
from crabwalk.compiler.capabilities import ContractKind, capability_contract
from crabwalk.diagnostics import CrabwalkCompilationError, Diagnostic, SourceSpan
from crabwalk.embedding import CompiledSource, GeneratedArtifacts, compile_source
from crabwalk.runtime import RustFunction
from crabwalk.service import CompilationResult


class _StaticCompiler:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def compile_path(self, path: Path, **options: object) -> CompilationResult:
        self.options = options
        module_name = str(options["module_name"])
        ir = analyze_project_path(
            path,
            module_name,
            crate_source_root=options.get("source_root"),
        )
        module = ModuleType(f"_native_{module_name}")
        for function in ir.functions:
            if function.name == "increment":
                setattr(module, function.rust_symbol, lambda value: value + 1)
        progress = options.get("progress")
        assert callable(progress)
        progress("Fake native build")
        generated_dir = path.parent / "generated"
        (generated_dir / "src").mkdir(parents=True, exist_ok=True)
        (generated_dir / "Cargo.toml").write_text(
            '[package]\nname = "embedded-test"\n',
            encoding="utf-8",
        )
        (generated_dir / "Cargo.lock").write_text("version = 4\n", encoding="utf-8")
        (generated_dir / "build.rs").write_text("fn main() {}\n", encoding="utf-8")
        (generated_dir / "src" / "lib.rs").write_text(
            "fn generated() {}\n",
            encoding="utf-8",
        )
        (generated_dir / "crabwalk-ir.json").write_text(
            json.dumps({"schema_version": 1}),
            encoding="utf-8",
        )
        (generated_dir / "crabwalk-source-map.json").write_text(
            json.dumps({"schema_version": 2, "entries": []}),
            encoding="utf-8",
        )
        (generated_dir / "crabwalk-build-inputs.json").write_text(
            json.dumps({"fingerprint": "a" * 64, "inputs": {}}),
            encoding="utf-8",
        )
        return CompilationResult(
            ir=ir,
            fingerprint="a" * 64,
            extension_name=module.__name__,
            project_root=path.parent,
            generated_dir=generated_dir,
            artifact=path.parent / "native.pyd",
            cache_hit=False,
            module=module,
            command=("cargo", "build"),
            cache_status="miss",
            build_inputs={
                "cargo_policy": {"locked": False, "offline": False},
            },
        )


def test_compile_source_binds_native_function_without_executing_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = _StaticCompiler()
    monkeypatch.setattr(embedding, "default_service", compiler)
    phases: list[str] = []
    source = """\
raise RuntimeError("top-level Python must not execute")

from crabwalk import rust

@rust.fn
def increment(value: rust.u64) -> rust.u64:
    return value + 1
"""

    compiled = compile_source(
        source,
        filename="recipe.py",
        cache_directory=tmp_path,
        progress=phases.append,
    )

    assert isinstance(compiled, CompiledSource)
    assert compiled.functions == ("increment",)
    assert compiled.source_path.read_text(encoding="utf-8") == source
    assert compiled.source_path.parent == tmp_path
    assert compiled.fingerprint == "a" * 64
    assert phases == [
        "Preparing source snapshot",
        "Fake native build",
        "Binding exported native functions",
    ]
    function = compiled.function("increment")
    assert isinstance(function, RustFunction)
    assert function(41) == 42
    assert function.__module__.startswith("crabwalk_source_")
    assert str(inspect.signature(function)) == "(value: 'rust.u64') -> 'rust.u64'"

    with pytest.raises(KeyError, match="available: increment"):
        compiled.function("missing")


def test_compile_source_is_public() -> None:
    assert crabwalk.compile_source is compile_source
    assert crabwalk.GeneratedArtifacts is GeneratedArtifacts


@capability_contract("embedding.generated-artifacts", native=False)
def test_compiled_source_exposes_generated_artifacts_without_filename_knowledge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = _StaticCompiler()
    monkeypatch.setattr(embedding, "default_service", compiler)
    compiled = compile_source(
        "from crabwalk import rust\n\n@rust.fn\ndef increment(value: rust.u64) -> rust.u64:\n    return value + 1\n",
        cache_directory=tmp_path,
    )

    artifacts = compiled.artifacts()

    assert isinstance(artifacts, GeneratedArtifacts)
    assert artifacts.schema_version == 1
    assert artifacts.rust_source == "fn generated() {}\n"
    assert artifacts.cargo_manifest.startswith("[package]")
    assert artifacts.cargo_lock == "version = 4\n"
    assert artifacts.build_script == "fn main() {}\n"
    assert artifacts.ir == {"schema_version": 1}
    assert artifacts.source_map == {"schema_version": 2, "entries": []}
    assert artifacts.build_inputs["fingerprint"] == "a" * 64


@capability_contract("embedding.virtual-package", native=False)
def test_compile_source_accepts_content_addressed_virtual_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = _StaticCompiler()
    monkeypatch.setattr(embedding, "default_service", compiler)
    compiled = compile_source(
        {
            "__init__.py": "from .maths import increment\n",
            "maths.py": """\
from crabwalk import rust

@rust.fn
def increment(value: rust.u64) -> rust.u64:
    return value + 1
""",
        },
        module_name="embedded_recipe",
        entry="maths.py",
        cache_directory=tmp_path,
    )

    assert compiled.functions == ("maths.increment",)
    assert compiled.function("maths.increment")(41) == 42
    assert compiled.source_path.name == "maths.py"
    assert compiled.source_path.parent.name.startswith("v_")
    assert compiler.options["module_name"] == "embedded_recipe.maths"


def test_compile_source_virtual_package_rejects_escaping_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="contained relative"):
        compile_source({"../outside.py": ""}, cache_directory=tmp_path)


def test_compile_source_resolves_path_crates_from_authored_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = _StaticCompiler()
    monkeypatch.setattr(embedding, "default_service", compiler)
    authored_root = tmp_path / "authored"
    dependency = authored_root / "native"
    dependency.mkdir(parents=True)

    compiled = compile_source(
        """\
from crabwalk import rust
native = rust.crate("native", path="./native")

@rust.fn
def increment(value: rust.u64) -> rust.u64:
    return value + 1
""",
        filename="kernel.py",
        source_root=authored_root,
        cache_directory=tmp_path / "snapshots",
    )

    assert compiler.options["source_root"] == authored_root.resolve()
    assert compiled._compilation.ir.crates[0].path == str(dependency.resolve())


def test_compile_source_attaches_opaque_external_origin_to_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingCompiler:
        def compile_path(self, path: Path, **_options: object) -> CompilationResult:
            raise CrabwalkCompilationError(
                Diagnostic(
                    "CRAB115",
                    "Type mismatch",
                    "intentional",
                    SourceSpan(str(path.resolve()), 4, 5, 4, 10),
                )
            )

    monkeypatch.setattr(embedding, "default_service", _FailingCompiler())
    origin = {"node": "node-42", "pin": "output"}

    with pytest.raises(CrabwalkCompilationError) as raised:
        compile_source(
            "from crabwalk import rust\n\n@rust.fn\ndef value() -> rust.u64:\n    return 'bad'\n",
            filename="graph.py",
            cache_directory=tmp_path,
            origin_map={4: origin},
        )

    assert raised.value.diagnostics[0].external_origin == origin


@capability_contract(
    "embedding.phase-cancellation",
    kind=ContractKind.NEGATIVE,
)
def test_compile_source_cancellation_precedes_materialization(tmp_path: Path) -> None:
    with pytest.raises(
        CrabwalkCompilationError, match="Compilation cancelled"
    ) as raised:
        compile_source(
            "from crabwalk import rust\n\n@rust.fn\ndef value() -> rust.u64:\n    return 1\n",
            cache_directory=tmp_path,
            cancelled=lambda: True,
        )

    assert raised.value.diagnostics[0].code == "CRAB309"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "filename",
    ("recipe", "../recipe.py", "nested/recipe.py", "class.py"),
)
def test_compile_source_rejects_ambiguous_filenames(
    filename: str,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError):
        compile_source(
            "from crabwalk import rust\n",
            filename=filename,
            cache_directory=tmp_path,
        )


def test_snapshot_publication_retries_transient_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "snapshot.py"
    temporary = tmp_path / ".snapshot.py.tmp"
    payload = b"from crabwalk import rust\n"
    temporary.write_bytes(payload)
    real_replace = embedding.os.replace
    attempts = 0

    def transient_replace(source: Path, target: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("simulated Windows sharing violation")
        real_replace(source, target)

    monkeypatch.setattr(embedding.os, "replace", transient_replace)
    monkeypatch.setattr(embedding.time, "sleep", lambda _delay: None)

    embedding._publish_snapshot(temporary, destination, payload)

    assert attempts == 3
    assert destination.read_bytes() == payload
    assert not temporary.exists()


def test_snapshot_publication_accepts_identical_concurrent_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "snapshot.py"
    temporary = tmp_path / ".snapshot.py.tmp"
    payload = b"from crabwalk import rust\n"
    temporary.write_bytes(payload)

    def concurrent_winner(_source: Path, target: Path) -> None:
        target.write_bytes(payload)
        raise PermissionError("simulated competing publisher")

    monkeypatch.setattr(embedding.os, "replace", concurrent_winner)

    embedding._publish_snapshot(temporary, destination, payload)

    assert destination.read_bytes() == payload
    assert not temporary.exists()
