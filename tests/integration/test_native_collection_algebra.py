from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from crabwalk.compiler.capabilities import capability_contract
from tests.unit.test_collection_algebra import COLLECTION_ALGEBRA_SOURCE


@capability_contract(
    "collections.result-pattern-algebra",
    "collections.hashmap-iteration",
    "collections.hashmap-split-local",
    "collections.hashable-map-return",
)
def test_collections_results_and_string_etl_run_natively(tmp_path: Path) -> None:
    source = tmp_path / "collection_algebra.py"
    source.write_text(
        COLLECTION_ALGEBRA_SOURCE
        + """
print(classify(7), classify(0))
print(increment_checked(4), increment_checked(0))
print(sorted(word_counts().items()))
print(sorted(count_keys()))
print(sorted(rebuilt_counts().items()))
print(normalize_fields("  ALPHA|Beta||  "))
print(parse_amount(" 12.5 "))
print(join_fields())
print(tuple_keyed())
print(map_loop_total())
print(sorted(split_map_keys()))
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
        "7 0",
        "5 0",
        "[('python', 1), ('rust', 2)]",
        "['python', 'rust']",
        "[('python', 1), ('rust', 2)]",
        "['alpha', 'beta']",
        "12.5",
        "alpha,beta",
        "{('key', b'\\x01\\x02'): 3}",
        "8",
        "['active', 'inactive']",
    ]
