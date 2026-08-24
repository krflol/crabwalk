"""Execution-backed capability-contract evidence for the test suite."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crabwalk.compiler.capabilities import (
    CAPABILITIES,
    ContractEvidence,
)

_items: dict[str, dict[str, Any]] = {}
_unknown_contracts: set[str] = set()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("crabwalk capability evidence")
    group.addoption(
        "--enforce-capability-contracts",
        action="store_true",
        default=False,
        help="Require every public capability contract to have a passing test item.",
    )
    group.addoption(
        "--capability-evidence",
        type=Path,
        default=None,
        help="Write the execution-backed capability evidence manifest to this path.",
    )


def pytest_configure(config: pytest.Config) -> None:
    del config
    _items.clear()
    _unknown_contracts.clear()


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    del config
    declared = {
        contract for capability in CAPABILITIES for contract in capability.contracts
    }
    for item in items:
        function = getattr(item, "obj", None)
        evidence = getattr(function, "__crabwalk_capability_evidence__", None)
        if evidence is None:
            continue
        assert isinstance(evidence, ContractEvidence)
        inferred_native = "/integration/" in item.nodeid.replace("\\", "/")
        native = evidence.native if evidence.native is not None else inferred_native
        _items[item.nodeid] = {
            "nodeid": item.nodeid,
            "contracts": list(evidence.contract_ids),
            "native": native,
            "kind": evidence.kind.value,
            "outcome": "collected",
        }
        _unknown_contracts.update(set(evidence.contract_ids) - declared)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    evidence = _items.get(report.nodeid)
    if evidence is None:
        return
    was_xfail = getattr(report, "wasxfail", None) is not None
    if report.when == "call":
        if was_xfail:
            evidence["outcome"] = "xpassed" if report.passed else "xfailed"
        elif report.passed:
            evidence["outcome"] = "passed"
        elif report.skipped:
            evidence["outcome"] = "skipped"
        else:
            evidence["outcome"] = "failed"
    elif report.failed:
        evidence["outcome"] = "failed"
    elif report.skipped and evidence["outcome"] == "collected":
        evidence["outcome"] = "skipped"


def _rustc_version() -> str | None:
    try:
        completed = subprocess.run(
            ["rustc", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _manifest(*, enforced: bool) -> dict[str, Any]:
    declared = {
        contract: capability.key
        for capability in CAPABILITIES
        for contract in capability.contracts
    }
    contracts: dict[str, dict[str, Any]] = {}
    for contract, capability in sorted(declared.items()):
        evidence = [
            value for value in _items.values() if contract in value["contracts"]
        ]
        contracts[contract] = {
            "capability": capability,
            "satisfied": any(value["outcome"] == "passed" for value in evidence),
            "items": evidence,
        }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "enforced": enforced,
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "rustc": _rustc_version(),
        },
        "unknown_contracts": sorted(_unknown_contracts),
        "contracts": contracts,
    }


def pytest_sessionfinish(
    session: pytest.Session,
    exitstatus: int | pytest.ExitCode,
) -> None:
    del exitstatus
    config = session.config
    enforced = bool(config.getoption("--enforce-capability-contracts"))
    manifest = _manifest(enforced=enforced)
    output = config.getoption("--capability-evidence")
    if output is not None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if not enforced:
        return
    missing = [
        contract
        for contract, evidence in manifest["contracts"].items()
        if not evidence["satisfied"]
    ]
    if missing or _unknown_contracts:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter,
    exitstatus: pytest.ExitCode,
    config: pytest.Config,
) -> None:
    del exitstatus
    if not config.getoption("--enforce-capability-contracts"):
        return
    manifest = _manifest(enforced=True)
    missing = [
        contract
        for contract, evidence in manifest["contracts"].items()
        if not evidence["satisfied"]
    ]
    if not missing and not _unknown_contracts:
        terminalreporter.write_sep(
            "=",
            f"all {len(manifest['contracts'])} capability contracts passed",
        )
        return
    terminalreporter.write_sep("=", "capability contract evidence failed")
    if missing:
        terminalreporter.write_line("missing passing evidence: " + ", ".join(missing))
    if _unknown_contracts:
        terminalreporter.write_line(
            "unknown contract IDs: " + ", ".join(sorted(_unknown_contracts))
        )
