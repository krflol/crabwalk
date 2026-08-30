from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.capabilities import capability_contract
from crabwalk.compiler.frontend import analyze_path
from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.ir import ClosureIR, MethodCallIR, ReturnIR
from crabwalk.diagnostics import CrabwalkCompilationError


CLOSURE_CONTRACT_SOURCE = """from crabwalk import rust

@rust.fn
def transform(
    values: rust.Ref[rust.Vec[rust.u64]],
    delta: rust.u64,
) -> rust.Vec[rust.u64]:
    return values.iter().map(
        rust.closure(
            lambda value: (rust.println(value), value + delta),
            kind="fn",
            capture="move",
        )
    ).collect_vec()
"""


@capability_contract("closures.capture-contracts", native=False)
def test_explicit_move_fn_closure_with_block_body_lowers(tmp_path: Path) -> None:
    source = tmp_path / "closures.py"
    source.write_text(CLOSURE_CONTRACT_SOURCE, encoding="utf-8")

    function = analyze_path(source).functions[0]
    returned = function.body[0]
    assert isinstance(returned, ReturnIR)
    collect = returned.value
    assert isinstance(collect, MethodCallIR)
    mapped = collect.receiver
    assert isinstance(mapped, MethodCallIR)
    closure = mapped.arguments[0]
    assert isinstance(closure, ClosureIR)
    assert closure.capture_mode == "move"
    assert closure.call_trait == "Fn"
    assert len(closure.prefix) == 1


def test_parallel_fn_mut_contract_is_rejected_before_rustc(tmp_path: Path) -> None:
    source = tmp_path / "invalid_closure.py"
    source.write_text(
        """from crabwalk import rust
rayon = rust.crate("rayon", version="1.12.0")

@rust.fn
def invalid(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.Vec[rust.u64]:
    return values.par_iter().copied().map(
        rust.closure(lambda value: value + 1, kind="fn_mut")
    ).collect_vec()
""",
        encoding="utf-8",
    )

    with pytest.raises(
        CrabwalkCompilationError, match="Parallel closure must implement Fn"
    ):
        generate_project(analyze_path(source), "_invalid_closure")
