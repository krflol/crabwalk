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
        "source-embedding",
        "Non-executing source embedding",
        Maturity.BOUNDED,
        "content-addressed single-source/virtual-package compilation and direct native callable binding",
        "native cross-module non-execution, callable binding, and process cancellation tests",
        (
            "Cargo dependencies remain a trusted build boundary; virtual mappings "
            "are regularized into immutable package snapshots"
        ),
        (
            "embedding.nonexecuting-source-callable",
            "embedding.phase-cancellation",
            "embedding.virtual-package",
        ),
    ),
    Capability(
        "ownership",
        "Ownership boundary",
        Maturity.COMPOSITIONAL,
        "Owned/Ref/Mut plus immutable Shared, move state, borrows, reload and fingerprint identity",
        "multi-argument, alias, reload, thread, domain, and vector tests",
        "ordinary handles are thread-affine; Shared is immutable Send + Sync only; no retained cross-call borrows",
        (
            "ownership.failure-atomic",
            "ownership.reload-fingerprint",
            "ownership.domain-schema",
            "ownership.shared-send-sync",
            "ownership.audited-gil-release",
        ),
    ),
    Capability(
        "build-cache",
        "Cargo build and cache",
        Maturity.PRODUCTION,
        "locks, complete modeled fingerprints, hashing, leases, atomic publish, cancellation, and release budgets",
        "dependency, corruption, replan, prune, race, cancellation, wheel, and versioned performance gates",
        "trusted build scripts may require declared extra inputs",
        (
            "cache.corruption-repair",
            "cache.concurrent-publication",
            "cache.prune-load-lease",
            "build.hard-cancellation",
            "build.performance-budgets",
        ),
    ),
    Capability(
        "application-packaging",
        "Application packaging",
        Maturity.BOUNDED,
        "PEP 517 wheel/sdist metadata merging with regular, namespace, and multiple top-level packages",
        "clean dependency-resolving install of a native multi-package wheel without a Rust toolchain",
        "platform wheels remain CPython-specific and must be built per supported target",
        (
            "packaging.metadata-sdist",
            "packaging.pep517-multi-package",
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
            "iterator.vec-consuming",
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
            "structured.hashmap-input",
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
        (
            "native array/memoryview track-plan test, zero-length exporters, "
            "and negative shape/format/alignment tests"
        ),
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
        "text-column-boundary",
        "Owned UTF-8 text column boundary",
        Maturity.BOUNDED,
        "one-crossing bytes+offset construction with immutable native row access",
        "native UTF-8 lifecycle, malformed-layout rejection, and telemetry tests",
        "owned contiguous UTF-8 only; no writable or retained Python borrow",
        (
            "text-column.owned-native",
            "text-column.invalid-layout",
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
            "collections.hashmap-borrowed-string-key",
        ),
    ),
    Capability(
        "native-etl",
        "Native standard-library ETL",
        Maturity.BOUNDED,
        (
            "checked casts, isize, slices/chunks/windows, ordered/hash collections, "
            "sorting, numeric formatting, UTF-8 bytes, PathBuf, and buffered I/O"
        ),
        "native parse-validate-group-sort-format-emit application acceptance",
        "finite UTF-8/path surface; no arbitrary filesystem traversal policy",
        (
            "etl.native-standard-library",
            "etl.ordered-grouping",
        ),
    ),
    Capability(
        "filesystem-results",
        "Native filesystem results",
        Maturity.PROOF,
        "typed File::open and whole-file String reads with io::Error propagation",
        "native success, open-error, and read-error Result propagation test",
        "read-only whole-file teaching surface; no general path or filesystem API",
        ("filesystem.result-propagation",),
    ),
    Capability(
        "structured-errors",
        "Structured native errors",
        Maturity.BOUNDED,
        "declared From conversions, custom error enums, fields, and cause chains",
        "native file, parse, and validation errors through one application error",
        "error payloads are displayable scalar/string/io/error values; no arbitrary Error trait discovery",
        (
            "errors.from-structured",
            "errors.undeclared-from-rejected",
        ),
    ),
    Capability(
        "crate-adapters",
        "Typed crate adapters",
        Maturity.BOUNDED,
        "external types/functions/traits, borrow signatures, closures, declared effects",
        "real path-crate value, generic callback, buffer, and trait native tests",
        "no automatic crate API discovery or manifest generation",
        (
            "crate.typed-value",
            "crate.typed-callback",
            "crate.builder-method-error",
            "crate.buffer-adapter",
        ),
    ),
    Capability(
        "python-adapters",
        "Typed Python-call adapters",
        Maturity.BOUNDED,
        "static Python signatures, explicit effects, PyErr propagation, and checked return extraction",
        "native success/exception/invalid-return plus closure-placement diagnostics",
        "synchronous calls only; rejected in closures, trait/operator methods, workers, and async helpers",
        (
            "python-adapter.success-errors",
            "python-adapter.explicit-target",
            "python-adapter.method-placement",
            "python-adapter.invalid-placement",
        ),
    ),
    Capability(
        "traits-generics",
        "Traits, generics, operators",
        Maturity.BOUNDED,
        (
            "per-parameter generic bounds; typed trait arguments; ref/mut/owned "
            "receivers; generic and associated outputs; arithmetic operators"
        ),
        "focused lowering and native compositional conformance tests",
        "finite safe trait/operator surface; no unsafe traits or specialization",
        (
            "traits.dynamic-dispatch",
            "generics.concrete-export",
            "traits.arguments-receivers-associated",
            "traits.external-implementation",
            "closures.capture-contracts",
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
    Capability(
        "python-call-ergonomics",
        "Exported Python call ergonomics",
        Maturity.BOUNDED,
        "positional-or-keyword calls and lossless literal defaults",
        "native external and compiled-internal keyword/default contract",
        "no positional-only, keyword-only, or variadic signatures",
        ("calls.keywords-defaults", "calls.invalid-default"),
    ),
    Capability(
        "developer-tooling",
        "Watch, diagnostics, LSP, and Rust export",
        Maturity.BOUNDED,
        "versioned JSON diagnostics, stdio LSP, explain, watch, and deterministic crate export",
        "framing/schema/export/watch CLI contract tests",
        "LSP performs static Crabwalk analysis; watch uses polling; no completion/refactoring server",
        (
            "tooling.diagnostics-explain-lsp",
            "tooling.export-rust",
            "tooling.watch",
        ),
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
