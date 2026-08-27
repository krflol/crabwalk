from __future__ import annotations

import inspect
from pathlib import Path
from types import ModuleType

import pytest

import crabwalk
import crabwalk.embedding as embedding
from crabwalk.compiler.frontend import analyze_project_path
from crabwalk.compiler.capabilities import ContractKind, capability_contract
from crabwalk.diagnostics import CrabwalkCompilationError
from crabwalk.embedding import CompiledSource, compile_source
from crabwalk.runtime import RustFunction
from crabwalk.service import CompilationResult


class _StaticCompiler:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def compile_path(self, path: Path, **options: object) -> CompilationResult:
        self.options = options
        module_name = str(options["module_name"])
        ir = analyze_project_path(path, module_name)
        module = ModuleType(f"_native_{module_name}")
        for function in ir.functions:
            if function.name == "increment":
                setattr(module, function.rust_symbol, lambda value: value + 1)
        progress = options.get("progress")
        assert callable(progress)
        progress("Fake native build")
        return CompilationResult(
            ir=ir,
            fingerprint="a" * 64,
            extension_name=module.__name__,
            project_root=path.parent,
            generated_dir=path.parent / "generated",
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
