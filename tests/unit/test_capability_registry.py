from __future__ import annotations

from pathlib import Path

from crabwalk.compiler.capabilities import (
    CAPABILITIES,
    Maturity,
    render_capability_markdown,
)


def test_capability_registry_has_unique_keys_and_evidence() -> None:
    assert len({value.key for value in CAPABILITIES}) == len(CAPABILITIES)
    assert all(value.evidence and value.limits for value in CAPABILITIES)
    assert next(value for value in CAPABILITIES if value.key == "rayon").maturity == (
        Maturity.COMPOSITIONAL
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
