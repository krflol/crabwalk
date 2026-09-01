from __future__ import annotations

from pathlib import Path

import pytest

from crabwalk.compiler.codegen import generate_project
from crabwalk.compiler.frontend import analyze_path
from crabwalk.diagnostics import CrabwalkCompilationError


BORROWED_RETURN_SOURCE = """\
from crabwalk import rust

a = rust.lifetime("a")

@rust.struct
class Budget:
    marker: rust.u64

@rust.method(Budget, name="watch_vec")
def budget_watch_vec(
    budget: rust.Ref[Budget],
    values: rust.Ref[rust.Vec[rust.i64]],
) -> rust.Ref[rust.Vec[rust.i64]]:
    return values

@rust.struct
class VecObserver:
    marker: rust.u8

@rust.method(VecObserver, name="watch_vec")
def observer_watch_vec(
    observer: rust.Owned[VecObserver],
    values: rust.Ref[rust.Vec[rust.i64]],
) -> rust.Ref[rust.Vec[rust.i64]]:
    return values

@rust.method(VecObserver, name="watch_borrowed_vec", type_parameters=[a])
def watch_borrowed_vec(
    observer: rust.Owned[VecObserver],
    values: rust.Borrow[a, rust.Vec[rust.i64]],
) -> rust.Borrow[a, rust.Vec[rust.i64]]:
    return values

@rust.fn
def observe_lengths() -> rust.usize:
    budget: Budget = Budget(marker=1)
    values: rust.Vec[rust.i64] = rust.Vec([1, 2, 3])
    observed: rust.Ref[rust.Vec[rust.i64]] = budget.watch_vec(values)
    named: rust.Ref[rust.Vec[rust.i64]] = VecObserver(marker=2).watch_borrowed_vec(observed)
    named_owned: rust.Ref[rust.Vec[rust.i64]] = VecObserver(marker=3).watch_borrowed_vec(values)
    nested: rust.Ref[rust.Vec[rust.i64]] = VecObserver(marker=3).watch_borrowed_vec(
        VecObserver(marker=4).watch_vec(values)
    )
    slot: rust.Option[rust.Vec[rust.i64]] = rust.Some(rust.Vec([4, 5, 6]))
    option_observed: rust.Ref[rust.Vec[rust.i64]] = VecObserver(
        marker=5
    ).watch_borrowed_vec(slot.as_ref().unwrap())
    return (
        observed.len()
        + named.len()
        + named_owned.len()
        + nested.len()
        + option_observed.len()
    )
"""


def test_borrowed_collection_return_keeps_lifetime_and_autoborrows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "borrowed_returns.py"
    source.write_text(BORROWED_RETURN_SOURCE, encoding="utf-8")

    ir = analyze_path(source)
    generated = generate_project(ir, "_crabwalk_borrowed_returns")

    budget_method = next(
        value for value in ir.functions if value.name == "budget_watch_vec"
    )
    assert budget_method.return_type.display().startswith("rust.Borrow[")
    assert "<'cw_return>" in generated.rust_source
    assert "values: &'cw_return Vec<i64>" in generated.rust_source
    assert "-> &'cw_return Vec<i64>" in generated.rust_source
    assert "watch_borrowed_vec(&observed)" not in generated.rust_source
    assert "watch_borrowed_vec(observed)" in generated.rust_source
    assert "watch_borrowed_vec(&values)" in generated.rust_source
    assert ".watch_vec(&values)" in generated.rust_source
    assert ": &Vec<i64> =" in generated.rust_source


def test_ambiguous_borrowed_collection_return_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "ambiguous_borrowed_return.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Owner:
    marker: rust.u8

@rust.method(Owner, name="choose")
def choose(
    owner: rust.Ref[Owner],
    left: rust.Ref[rust.Vec[rust.u64]],
    right: rust.Ref[rust.Vec[rust.u64]],
) -> rust.Ref[rust.Vec[rust.u64]]:
    return left
""",
        encoding="utf-8",
    )

    with pytest.raises(CrabwalkCompilationError) as captured:
        analyze_path(source)

    diagnostic = captured.value.diagnostics[0]
    assert diagnostic.code == "CRAB183"
    assert "ambiguous" in diagnostic.title.lower()
