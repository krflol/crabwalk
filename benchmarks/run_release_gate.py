"""Run Crabwalk's versioned 10/1k/100k boundary and lifecycle budget gate."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCHEMA_VERSION = 1
SIZES = (10, 1_000, 100_000)

FIXTURE = r"""from __future__ import annotations

import gc
import json
import time

from crabwalk import rust
from crabwalk.telemetry import process_rss_bytes

@rust.struct
class Term:
    text: rust.String

@rust.struct
class Metadata:
    source: rust.String

@rust.struct
class Row:
    terms: rust.Vec[Term]
    metadata: rust.Option[Metadata]

@rust.fn
def total_terms(rows: rust.Ref[rust.Vec[Row]]) -> rust.usize:
    return rows.iter_ref().map(lambda row: row.terms.len()).sum()

measurements = {}
for size in (10, 1_000, 100_000):
    gc.collect()
    before = process_rss_bytes()
    source = [
        {
            "terms": [{"text": "rust"}, {"text": "python"}],
            "metadata": {"source": "release-gate"},
        }
        for _ in range(size)
    ]
    started = time.perf_counter()
    rows = rust.Vec[Row](source)
    constructed = time.perf_counter()
    del source
    gc.collect()
    retained = process_rss_bytes()
    result, call = total_terms.call_with_telemetry(rows)
    called = time.perf_counter()
    assert result == size * 2
    construction = rows.boundary_telemetry
    assert construction is not None
    measurements[str(size)] = {
        "construct_seconds": constructed - started,
        "native_call_seconds": called - constructed,
        "rss_before_bytes": before,
        "rss_retained_bytes": retained,
        "retained_rss_growth_bytes": (
            None if before is None or retained is None else max(0, retained - before)
        ),
        "construction": construction.to_dict(),
        "call": call.to_dict(),
    }
    del rows
    gc.collect()

print(json.dumps({"schema_version": 1, "sizes": measurements}, sort_keys=True))
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--budgets",
        type=Path,
        default=Path(__file__).with_name("performance_budgets.json"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-enforce", action="store_true")
    arguments = parser.parse_args(argv)
    repository = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository / "src")
    environment["CRABWALK_PROGRESS"] = "never"
    with tempfile.TemporaryDirectory(prefix="crabwalk-release-gate-") as value:
        root = Path(value)
        source = root / "boundary_gate.py"
        source.write_text(FIXTURE, encoding="utf-8", newline="\n")
        cold = _run(source, root, environment)
        warm = _run(source, root, environment)
    report = {
        "schema_version": SCHEMA_VERSION,
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "rustc": _tool_version("rustc"),
            "cargo": _tool_version("cargo"),
        },
        "cold_process_seconds": cold[0],
        "warm_process_seconds": warm[0],
        "cold": cold[1],
        "warm": warm[1],
    }
    budgets = json.loads(arguments.budgets.read_text(encoding="utf-8"))
    violations = _violations(report, budgets)
    report["budget_file_schema_version"] = budgets.get("schema_version")
    report["budget_violations"] = violations
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(encoded, encoding="utf-8", newline="\n")
    print(encoded, end="")
    return 0 if arguments.no_enforce or not violations else 1


def _run(
    source: Path,
    cwd: Path,
    environment: dict[str, str],
) -> tuple[float, dict[str, object]]:
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-u", str(source)],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    payload = json.loads(completed.stdout.splitlines()[-1])
    if not isinstance(payload, dict):
        raise TypeError("release fixture returned a non-object payload")
    return elapsed, payload


def _violations(
    report: dict[str, object],
    budget_document: dict[str, object],
) -> list[str]:
    budget = budget_document["budgets"]
    assert isinstance(budget, dict)
    failures: list[str] = []

    def maximum(label: str, actual: float | int | None, key: str) -> None:
        limit = budget[key]
        if actual is None or not isinstance(limit, (int, float)) or actual > limit:
            failures.append(f"{label}: {actual!r} exceeds {limit!r}")

    maximum(
        "cold process",
        _number(report["cold_process_seconds"]),
        "cold_process_seconds_max",
    )
    maximum(
        "warm process",
        _number(report["warm_process_seconds"]),
        "warm_process_seconds_max",
    )
    warm = report["warm"]
    assert isinstance(warm, dict)
    sizes = warm["sizes"]
    assert isinstance(sizes, dict)
    largest = sizes["100000"]
    assert isinstance(largest, dict)
    maximum(
        "100k construct",
        _number(largest["construct_seconds"]),
        "construct_100k_seconds_max",
    )
    maximum(
        "100k native call",
        _number(largest["native_call_seconds"]),
        "native_call_100k_seconds_max",
    )
    maximum(
        "100k retained RSS growth",
        _number(largest["retained_rss_growth_bytes"]),
        "retained_rss_growth_100k_bytes_max",
    )
    for size in SIZES:
        measurement = sizes[str(size)]
        assert isinstance(measurement, dict)
        for phase in ("construction", "call"):
            telemetry = measurement[phase]
            assert isinstance(telemetry, dict)
            for key, budget_key in (
                ("boundary_crossings", "boundary_crossings_exact"),
                ("native_clones", "native_clones_exact"),
            ):
                if telemetry[key] != budget[budget_key]:
                    failures.append(
                        f"{size} {phase} {key}: {telemetry[key]!r} != {budget[budget_key]!r}"
                    )
    return failures


def _number(value: object) -> float | int | None:
    return value if isinstance(value, (int, float)) else None


def _tool_version(name: str) -> str | None:
    try:
        completed = subprocess.run(
            [name, "--version"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


if __name__ == "__main__":
    raise SystemExit(main())
