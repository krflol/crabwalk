from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_structured_filter_group_and_emit_workload_runs_natively(
    tmp_path: Path,
) -> None:
    source = tmp_path / "etl_acceptance.py"
    source.write_text(
        """\
from crabwalk import rust

@rust.struct
class Row:
    customer_id: rust.u64
    status: rust.String
    amount: rust.f64

@rust.fn
def active_totals(
    rows: rust.Owned[rust.Vec[Row]],
) -> rust.HashMap[rust.String, rust.f64]:
    totals: rust.HashMap[rust.String, rust.f64] = rust.HashMap()
    for row in rows.iter_ref().filter(
        lambda row: row.status.to_lowercase().starts_with("active")
    ):
        totals.add(row.status.to_lowercase(), row.amount)
    return totals

rows = rust.Vec[Row]([
    {"customer_id": 7, "status": "ACTIVE", "amount": 12.5},
    {"customer_id": 8, "status": "inactive", "amount": 9.0},
    {"customer_id": 9, "status": "active", "amount": 3.5},
])
print(sorted(active_totals(rows).items()))
print(rows.moved)
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
    assert result.stdout.splitlines() == ["[('active', 16.0)]", "True"]
