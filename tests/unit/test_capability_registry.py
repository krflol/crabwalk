from __future__ import annotations

import ast
from pathlib import Path

from crabwalk.compiler.capabilities import (
    CAPABILITIES,
    Maturity,
    render_capability_markdown,
)


def test_capability_registry_has_unique_keys_and_evidence() -> None:
    assert len({value.key for value in CAPABILITIES}) == len(CAPABILITIES)
    assert all(value.evidence and value.limits for value in CAPABILITIES)
    declared = [contract for value in CAPABILITIES for contract in value.contracts]
    assert len(declared) == len(set(declared))
    minimum_contracts = {
        Maturity.PROOF: 1,
        Maturity.BOUNDED: 2,
        Maturity.COMPOSITIONAL: 3,
        Maturity.PRODUCTION: 4,
    }
    assert all(
        len(value.contracts) >= minimum_contracts[value.maturity]
        for value in CAPABILITIES
    )
    assert next(value for value in CAPABILITIES if value.key == "rayon").maturity == (
        Maturity.COMPOSITIONAL
    )


def test_every_capability_contract_is_bound_to_a_discovered_test() -> None:
    root = Path(__file__).resolve().parents[2]
    evidenced: dict[str, str] = {}
    for path in (root / "tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not (
                node.name.startswith("test_")
            ):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                function = decorator.func
                name = (
                    function.id
                    if isinstance(function, ast.Name)
                    else function.attr
                    if isinstance(function, ast.Attribute)
                    else ""
                )
                if name != "capability_contract":
                    continue
                for argument in decorator.args:
                    assert isinstance(argument, ast.Constant) and isinstance(
                        argument.value, str
                    )
                    previous = evidenced.setdefault(
                        argument.value,
                        f"{path.relative_to(root)}::{node.name}",
                    )
                    assert previous == f"{path.relative_to(root)}::{node.name}"

    declared = {
        contract for capability in CAPABILITIES for contract in capability.contracts
    }
    assert evidenced.keys() == declared
    assert (
        next(value for value in CAPABILITIES if value.key == "native-futures").maturity
        == Maturity.PROOF
    )


def test_language_reference_capability_table_is_generated() -> None:
    root = Path(__file__).resolve().parents[2]
    document = (root / "Docs" / "Crabwalk Language Reference.md").read_text(
        encoding="utf-8"
    )
    start = "<!-- crabwalk-capabilities:start -->"
    end = "<!-- crabwalk-capabilities:end -->"
    assert document.partition(start)[2].partition(end)[0].strip() == (
        render_capability_markdown()
    )
