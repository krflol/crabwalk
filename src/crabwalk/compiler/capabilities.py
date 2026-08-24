"""Single source of truth for Crabwalk capability maturity claims."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Maturity(StrEnum):
    PROOF = "Proof"
    BOUNDED = "Bounded"
    COMPOSITIONAL = "Compositional"
    PRODUCTION = "Production"


@dataclass(frozen=True, slots=True)
class Capability:
    key: str
    name: str
    maturity: Maturity
    contract: str
    evidence: str
    limits: str


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "compiler",
        "Static compiler pipeline",
        Maturity.COMPOSITIONAL,
        "Source-spanned typed IR, validation, deterministic Rust/PyO3 emission",
        "unit, native, package, diagnostic, and generated-Rust tests",
        "an explicit Python subset; rustc remains authoritative",
    ),
    Capability(
        "ownership",
        "Ownership boundary",
        Maturity.COMPOSITIONAL,
        "Owned/Ref/Mut, move state, borrows, reload and fingerprint identity",
        "multi-argument, alias, reload, thread, domain, and vector tests",
        "handles are thread-affine; no retained cross-call borrows",
    ),
    Capability(
        "build-cache",
        "Cargo build and cache",
        Maturity.COMPOSITIONAL,
        "locks, complete modeled fingerprints, hashing, leases, atomic publish",
        "dependency, corruption, replan, prune, race, and wheel tests",
        "trusted build scripts may require declared extra inputs",
    ),
    Capability(
        "iterators",
        "Sequential iterators",
        Maturity.COMPOSITIONAL,
        "owned/shared items; map/filter/filter_map/fold/reduce/collect and queries",
        "Copy, String, &str, tuple, domain, one- and three-stage native pipelines",
        "expression lambdas only; no retained iterator boundary",
    ),
    Capability(
        "rayon",
        "Rayon iterators",
        Maturity.COMPOSITIONAL,
        "typed par_iter with borrowed items, adapters, collect, sum and reduce",
        "u64, Vec<String>, and Vec<domain> multi-adapter native tests",
        "requires an explicit Rayon dependency; no arbitrary Rayon API reflection",
    ),
    Capability(
        "structured-data",
        "Structured native data",
        Maturity.COMPOSITIONAL,
        "recursive vectors, domain rows, nested domains, owned domain returns",
        "Python mappings/handles through Vec<Row>, nested struct/enum round trips",
        "allocating explicit input; direct recursive domain cycles are invalid Rust",
    ),
    Capability(
        "collections",
        "String, HashMap, Option/Result",
        Maturity.COMPOSITIONAL,
        "parse-transform-group-iterate-return algebra with typed errors",
        "native delimited parsing and structured filter-group-emit acceptance",
        "documented method table is finite, not the complete Rust standard library",
    ),
    Capability(
        "crate-adapters",
        "Typed crate adapters",
        Maturity.BOUNDED,
        "external types/functions, borrow signatures, closures, declared effects",
        "real path-crate value and generic callback native test",
        "no trait/builder manifest generation or automatic crate API discovery",
    ),
    Capability(
        "traits-generics",
        "Traits, generics, operators",
        Maturity.BOUNDED,
        "generic helpers, shared no-argument traits, Add implementations",
        "Rust Book and focused native conformance tests",
        "not a general Rust trait or operator declaration language",
    ),
    Capability(
        "native-futures",
        "std-only native futures",
        Maturity.PROOF,
        "Future/await/join/select lowering through a teaching executor",
        "focused Rust Book subprocess tests",
        "busy-polling; no reactor, cancellation, Tokio, or Python future ABI",
    ),
    Capability(
        "threadpool-tcp",
        "Thread pool and TCP",
        Maturity.PROOF,
        "finite unit-job pool and loopback HTTP teaching operations",
        "panic-containment and Rust Book web-server subprocess tests",
        "no general server, task handles, backpressure, TLS, or cancellation",
    ),
    Capability(
        "advanced-intrinsics",
        "Advanced and unsafe intrinsics",
        Maturity.PROOF,
        "audited operations for individual Rust Book concepts",
        "subprocess panic/unsafe and exact code-generation tests",
        "not general inline Rust, FFI, unsafe, macro, or pointer support",
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
                    capability.evidence,
                    capability.limits,
                )
            )
            + " |"
        )
    return "\n".join(lines)
