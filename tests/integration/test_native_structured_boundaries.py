from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.unit.test_structured_boundaries import STRUCTURED_BOUNDARY_SOURCE


def test_structured_vectors_and_owned_domain_returns_run_natively(
    tmp_path: Path,
) -> None:
    source = tmp_path / "structured_boundaries.py"
    source.write_text(
        STRUCTURED_BOUNDARY_SOURCE
        + """
rows = rust.Vec[Row]([
    {"customer_id": 7, "status": "active", "amount": 12.5},
    {"customer_id": 8, "status": "disabled", "amount": 9.0},
    Row(customer_id=9, status="active", amount=3.5),
])
print(active_customer_ids(rows))
print(rows.moved)

pairs = rust.Vec[rust.Tuple[rust.u64, rust.u64]]([(1, 2), (3, 4)])
print(pair_total(pairs))
optional = rust.Vec[rust.Option[rust.u64]]([1, None, 3])
print(present_count(optional))
nested = rust.Vec[rust.Vec[rust.u8]]([[1, 2], b"abc"])
print(nested_first_len(nested))

created = make_row(10, "active", 4.25)
print(created.to_python())
labels = make_labels()
print(labels.to_python())

address = Address(city="Chicago")
customer = Customer(customer_id=11, address=address)
print(customer.address.to_python())
print(customer.to_python())
customer.address = {"city": "Madison"}
print(customer.address.city)
created_customer = make_customer(12, "Milwaukee")
print(created_customer.to_python())
delivery = Delivery.Home(address={"city": "Evanston"})
print(delivery.address.to_python())
print(delivery.to_python())
created_delivery = make_delivery("Detroit")
print(created_delivery.to_python())
payload = Payload.AddressValue({"city": "Toledo"})
print(payload._0.to_python())
print(payload.to_python())
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
        "[7, 9]",
        "True",
        "10",
        "2",
        "2",
        "{'customer_id': 10, 'status': 'active', 'amount': 4.25}",
        "['alpha', 'beta']",
        "{'city': 'Chicago'}",
        "{'customer_id': 11, 'address': {'city': 'Chicago'}}",
        "Madison",
        "{'customer_id': 12, 'address': {'city': 'Milwaukee'}}",
        "{'city': 'Evanston'}",
        "{'variant': 'Home', 'address': {'city': 'Evanston'}}",
        "{'variant': 'Home', 'address': {'city': 'Detroit'}}",
        "{'city': 'Toledo'}",
        "{'variant': 'AddressValue', '_0': {'city': 'Toledo'}}",
    ]
