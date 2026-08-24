from __future__ import annotations

from pathlib import Path

from crabwalk.compiler.capabilities import (
    CAPABILITIES,
    ContractEvidence,
    ContractKind,
    Maturity,
    capability_contract,
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


def test_capability_decorator_attaches_execution_metadata() -> None:
    @capability_contract(
        "rayon.unindexed-order-rejected",
        native=False,
        kind=ContractKind.NEGATIVE,
    )
    def evidence() -> None:
        pass

    assert evidence.__crabwalk_capability_contracts__ == (
        "rayon.unindexed-order-rejected",
    )
    assert evidence.__crabwalk_capability_evidence__ == ContractEvidence(
        ("rayon.unindexed-order-rejected",),
        False,
        ContractKind.NEGATIVE,
    )
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
