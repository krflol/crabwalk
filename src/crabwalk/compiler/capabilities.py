"""Single source of truth for Crabwalk capability maturity claims."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, TypeVar, cast


class Maturity(StrEnum):
    PROOF = "Proof"
    BOUNDED = "Bounded"
    COMPOSITIONAL = "Compositional"
    PRODUCTION = "Production"


class ContractKind(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


@dataclass(frozen=True, slots=True)
class Capability:
    key: str
    name: str
    maturity: Maturity
    contract: str
    evidence: str
    limits: str
    contracts: tuple[str, ...] = ()


_TestFunction = TypeVar("_TestFunction", bound=Callable[..., object])


@dataclass(frozen=True, slots=True)
class ContractEvidence:
    contract_ids: tuple[str, ...]
    native: bool | None
    kind: ContractKind


def capability_contract(
    *contract_ids: str,
    native: bool | None = None,
    kind: ContractKind = ContractKind.POSITIVE,
) -> Callable[[_TestFunction], _TestFunction]:
    """Bind an executable test to public capability-contract identifiers."""

    if not contract_ids or any(not value.strip() for value in contract_ids):
        raise ValueError("capability contracts require non-empty identifiers")
    if len(set(contract_ids)) != len(contract_ids):
        raise ValueError("capability contract identifiers must be unique per test")

    def decorate(function: _TestFunction) -> _TestFunction:
        setattr(function, "__crabwalk_capability_contracts__", tuple(contract_ids))
        setattr(
            function,
            "__crabwalk_capability_evidence__",
            ContractEvidence(tuple(contract_ids), native, kind),
        )
        return cast(_TestFunction, function)

    return decorate


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "compiler",
        "Static compiler pipeline",
        Maturity.COMPOSITIONAL,
        "Source-spanned typed IR, validation, deterministic Rust/PyO3 emission",
        "unit, native, package, diagnostic, and generated-Rust tests",
        "an explicit Python subset; rustc remains authoritative",
        (
            "compiler.package-native",
            "compiler.generated-identities",
            "compiler.pattern-identity",
        ),
    ),
    Capability(
        "ownership",
        "Ownership boundary",
        Maturity.COMPOSITIONAL,
        "Owned/Ref/Mut, move state, borrows, reload and fingerprint identity",
        "multi-argument, alias, reload, thread, domain, and vector tests",
        "handles are thread-affine; no retained cross-call borrows",
        (
            "ownership.failure-atomic",
            "ownership.reload-fingerprint",
            "ownership.domain-schema",
        ),
    ),
    Capability(
        "build-cache",
        "Cargo build and cache",
        Maturity.COMPOSITIONAL,
        "locks, complete modeled fingerprints, hashing, leases, atomic publish",
        "dependency, corruption, replan, prune, race, and wheel tests",
        "trusted build scripts may require declared extra inputs",
        (
            "cache.corruption-repair",
            "cache.concurrent-publication",
            "cache.prune-load-lease",
        ),
    ),
    Capability(
        "iterators",
        "Sequential iterators",
        Maturity.COMPOSITIONAL,
        "owned/shared items; map/filter/filter_map/fold/reduce/collect and queries",
        "Copy, String, &str, tuple, domain, one- and three-stage native pipelines",
        "expression lambdas only; no retained iterator boundary",
        (
            "iterator.copy-inline",
            "iterator.string-inline",
            "iterator.string-split-local",
            "iterator.opaque-shadow",
            "iterator.borrowed-for-loop",
            "iterator.borrowed-for-loop-native",
        ),
    ),
    Capability(
        "rayon",
        "Rayon iterators",
        Maturity.COMPOSITIONAL,
        "typed par_iter with borrowed items, adapters, collect, sum and reduce",
        "u64, Vec<String>, and Vec<domain> multi-adapter native tests",
        "requires an explicit Rayon dependency; no arbitrary Rayon API reflection",
        (
            "rayon.string-split-local",
            "rayon.domain-filter-map-collect",
            "rayon.indexed-enumerate",
            "rayon.indexed-zip",
            "rayon.unindexed-order-rejected",
            "rayon.explicit-find-semantics",
        ),
    ),
    Capability(
        "structured-data",
        "Structured native data",
        Maturity.COMPOSITIONAL,
        "recursive vectors, domain rows, nested domains, owned domain returns",
        "Python mappings/handles through Vec<Row>, nested struct/enum round trips",
        "allocating explicit input; direct recursive domain cycles are invalid Rust",
        (
            "structured.vector-domain-input",
            "structured.nested-domain-roundtrip",
            "structured.owned-domain-return",
        ),
    ),
    Capability(
        "buffer-boundary",
        "Read-only numeric buffer boundary",
        Maturity.BOUNDED,
        (
            "call-scoped zero-copy input from one-dimensional, C-contiguous, "
            "native-endian Python buffers"
        ),
        "native array/memoryview track-plan test and negative shape/format tests",
        (
            "primitive numeric inputs only; GIL held; no writable, strided, "
            "retained, parallel, or output buffers"
        ),
        (
            "buffer.readonly-numeric-native",
            "buffer.invalid-input-rejected",
        ),
    ),
    Capability(
        "collections",
        "String, HashMap, Option/Result",
        Maturity.COMPOSITIONAL,
        "parse-transform-group-iterate-return algebra with typed errors",
        "native delimited parsing and structured filter-group-emit acceptance",
        "documented method table is finite, not the complete Rust standard library",
        (
            "collections.result-pattern-algebra",
            "collections.hashmap-iteration",
            "collections.hashmap-split-local",
            "collections.hashable-map-return",
        ),
    ),
    Capability(
        "crate-adapters",
        "Typed crate adapters",
        Maturity.BOUNDED,
        "external types/functions, borrow signatures, closures, declared effects",
        "real path-crate value and generic callback native test",
        "no trait/builder manifest generation or automatic crate API discovery",
        (
            "crate.typed-value",
            "crate.typed-callback",
        ),
    ),
    Capability(
        "traits-generics",
        "Traits, generics, operators",
        Maturity.BOUNDED,
        "generic helpers, shared no-argument traits, Add implementations",
        "Rust Book and focused native conformance tests",
        "not a general Rust trait or operator declaration language",
        (
            "traits.dynamic-dispatch",
            "generics.concrete-export",
        ),
    ),
    Capability(
        "native-futures",
        "std-only native futures",
        Maturity.PROOF,
        "Future/await/join/select lowering through a teaching executor",
        "focused Rust Book subprocess tests",
        "busy-polling; no reactor, cancellation, Tokio, or Python future ABI",
        ("futures.split-local-block-on",),
    ),
    Capability(
        "threadpool-tcp",
        "Thread pool and TCP",
        Maturity.PROOF,
        "finite unit-job pool and loopback HTTP teaching operations",
        "panic-containment and Rust Book web-server subprocess tests",
        "no general server, task handles, backpressure, TLS, or cancellation",
        ("threadpool.loopback-http",),
    ),
    Capability(
        "advanced-intrinsics",
        "Advanced and unsafe intrinsics",
        Maturity.PROOF,
        "audited operations for individual Rust Book concepts",
        "subprocess panic/unsafe and exact code-generation tests",
        "not general inline Rust, FFI, unsafe, macro, or pointer support",
        ("advanced.audited-intrinsics",),
    ),
)


def render_capability_markdown() -> str:
    """Render the public table from the same registry tests inspect."""

    lines = [
        "| Capability | Maturity | Supported contract | Evidence | Important limit |",
        "|---|---|---|---|---|",
    ]
    for capability in CAPABILITIES:
        lines.append(
            "| "
            + " | ".join(
                (
                    capability.name,
                    capability.maturity.value,
                    capability.contract,
                    (
                        capability.evidence
                        + "<br>Contracts: "
                        + ", ".join(f"`{value}`" for value in capability.contracts)
                    ),
                    capability.limits,
                )
            )
            + " |"
        )
    return "\n".join(lines)
