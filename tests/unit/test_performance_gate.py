from __future__ import annotations

import json
from pathlib import Path

from benchmarks.run_release_gate import _violations
from crabwalk.compiler.capabilities import capability_contract
from crabwalk.telemetry import process_rss_bytes


def _report() -> dict[str, object]:
    sizes = {
        str(size): {
            "construct_seconds": 0.01,
            "native_call_seconds": 0.001,
            "retained_rss_growth_bytes": 1024,
            "construction": {"boundary_crossings": 1, "native_clones": 0},
            "call": {"boundary_crossings": 1, "native_clones": 0},
        }
        for size in (10, 1_000, 100_000)
    }
    return {
        "cold_process_seconds": 1.0,
        "warm_process_seconds": 0.5,
        "warm": {"sizes": sizes},
    }


@capability_contract("build.performance-budgets", native=False)
def test_release_performance_budget_schema_and_enforcement() -> None:
    root = Path(__file__).resolve().parents[2]
    budget = json.loads(
        (root / "benchmarks" / "performance_budgets.json").read_text(encoding="utf-8")
    )
    assert budget["schema_version"] == 1
    assert _violations(_report(), budget) == []

    failed = _report()
    failed["cold_process_seconds"] = 10_000.0
    assert "cold process" in _violations(failed, budget)[0]


def test_process_rss_probe_is_bounded_when_available() -> None:
    rss = process_rss_bytes()
    assert rss is None or rss > 0
