from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_enum_variants_match_and_move_state_are_native(tmp_path: Path) -> None:
    source = tmp_path / "enum_app.py"
    source.write_text(
        """\
from crabwalk import CrabwalkMoveError, rust

@rust.enum
class Status:
    Pending = rust.variant()
    Running = rust.variant(progress=rust.u8)
    Failed = rust.variant(rust.String)

@rust.enum
class Heterogeneous:
    Text = rust.variant(rust.String)
    Number = rust.variant(rust.u64)

@rust.fn
def score(status: rust.Ref[Status]) -> rust.u8:
    match status:
        case Status.Pending:
            return 0
        case Status.Running(progress=value):
            return value
        case Status.Failed(_):
            return 255

@rust.fn
def consume(status: rust.Owned[Status]) -> rust.u8:
    match status:
        case Status.Pending:
            return 0
        case Status.Running(progress=value):
            return value
        case Status.Failed(_):
            return 255

pending = Status.Pending()
running = Status.Running(progress=7)
failed = Status.Failed("oops")
text = Heterogeneous.Text("crab")
number = Heterogeneous.Number(42)

print(pending.to_python())
print(running.to_python(), running.progress)
print(failed.to_python())
print(text.to_python(), number.to_python())
print(score(pending), score(running), score(failed))
alias = running
print(consume(running))
print(running.moved, alias.moved)
try:
    print(alias.progress)
except CrabwalkMoveError as error:
    print(type(error).__name__, "moved into consume()" in str(error))
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")

    result = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "{'variant': 'Pending'}",
        "{'variant': 'Running', 'progress': 7} 7",
        "{'variant': 'Failed', '_0': 'oops'}",
        "{'variant': 'Text', '_0': 'crab'} {'variant': 'Number', '_0': 42}",
        "0 7 255",
        "7",
        "True True",
        "CrabwalkMoveError True",
    ]


def test_non_exhaustive_enum_match_maps_rustc_error_to_python(tmp_path: Path) -> None:
    source = tmp_path / "non_exhaustive.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.enum
class Choice:
    First = rust.variant()
    Second = rust.variant()

@rust.fn
def score(value: rust.Ref[Choice]) -> rust.u8:
    match value:
        case Choice.First:
            return 1
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")

    result = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )

    assert result.returncode != 0
    assert "CRAB301 Rust compilation failed" in result.stderr
    assert "non-exhaustive patterns" in result.stderr
    assert "non_exhaustive.py:10" in result.stderr
