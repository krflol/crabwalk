from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_iterators import NON_COPY_ITERATOR_SOURCE, SEARCH_SOURCE


def test_lines_iterator_and_vec_string_return_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "search.py"
    source.write_text(
        SEARCH_SOURCE
        + """
poem = "Rust:\\nsafe, fast, productive.\\nPick three.\\nTrust me."
print(search("duct", poem))
print(search_case_insensitive("rUsT", poem))
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
        "['safe, fast, productive.']",
        "['Rust:', 'Trust me.']",
    ]


@capability_contract(
    "iterator.string-split-local",
    "iterator.borrowed-for-loop-native",
)
def test_non_copy_three_stage_iterator_pipeline_runs_natively(tmp_path: Path) -> None:
    source = tmp_path / "non_copy_iterators.py"
    source.write_text(
        NON_COPY_ITERATOR_SOURCE
        + """
rows = rust.Vec[rust.String]([
    "1|ALICE|active|",
    "2|BOB|inactive|",
    "3|CAROL|active|",
])
print(normalize_active(rows))
print(normalize_active_split(rows))
print(normalize_for_loop(rows))
print(clone_active(rows))
print(has_active(rows))
print(rows.to_python())
tuple_rows = rust.Vec[rust.Tuple[rust.String, rust.u64]]([
    ("ALICE", 1),
    ("BOB", 2),
])
print(tuple_names(tuple_rows))
numbers = rust.Vec[rust.u64]([1, 2, 3, 4])
print(fold_total(numbers))
print(reduce_total(numbers))
""",
        encoding="utf-8",
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["CRABWALK_PROGRESS"] = "never"

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
        "['1|alice|active|', '3|carol|active|']",
        "['1|alice|active|', '3|carol|active|']",
        "['1|alice|active|', '2|bob|inactive|', '3|carol|active|']",
        "['1|ALICE|active|', '3|CAROL|active|']",
        "True",
        "['1|ALICE|active|', '2|BOB|inactive|', '3|CAROL|active|']",
        "['alice', 'bob']",
        "10",
        "10",
    ]
