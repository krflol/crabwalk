from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from crabwalk import rust
from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import CrabwalkCompilationError


def test_rayon_parallel_iterator_requires_declaration_and_generates_native_rust(
    tmp_path: Path,
) -> None:
    source = tmp_path / "parallel.py"
    source.write_text(
        """\
from crabwalk import rust

rayon = rust.crate("rayon", version="1")

@rust.fn
def parallel_sum(stop: rust.u64) -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([])
    for value in range(stop):
        values.push(value)
    return values.par_iter().copied().sum()
""",
        encoding="utf-8",
    )
    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_parallel_test")
    assert 'rayon = { version = "1" }' in generated.cargo_toml
    assert "use rayon::prelude::*;" in generated.rust_source
    assert ".par_iter().copied().sum()" in generated.rust_source

    missing = tmp_path / "missing_rayon.py"
    missing.write_text(
        source.read_text(encoding="utf-8").replace(
            'rayon = rust.crate("rayon", version="1")\n', ""
        ),
        encoding="utf-8",
    )
    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(missing)
    assert captured.value.diagnostics[0].code == "CRAB176"


def test_async_call_rejects_ordinary_python_functions() -> None:
    async def run() -> None:
        with pytest.raises(TypeError, match="compiled @rust.fn"):
            await rust.async_call(lambda: 1)

    asyncio.run(run())
