---
type: risk-and-decision-register
project: Crabwalk
status: active
created: 2026-08-21
updated: 2026-08-21
tags:
  - project/crabwalk
  - area/risk
  - area/decisions
---

# Crabwalk Risks and Decisions

> [!warning] Planning posture
> Crabwalk’s largest risks are semantic and lifecycle risks, not AST traversal. Scope control, native-module loading, source mapping, crate-path resolution, and ownership across Python must be retired with explicit vertical evidence before broad syntax is added.

## Risk scale

- Likelihood: 1 rare → 5 expected
- Impact: 1 minor → 5 threatens product correctness/viability
- Score: likelihood × impact
- Critical: 20–25
- High: 12–19
- Medium: 6–11
- Low: 1–5

## Risk register

| ID | Risk | L | I | Score | Leading indicator | Mitigation / contingency | Owner role | Review |
|---|---|---:|---:|---:|---|---|---|---|
| R-001 | The broad vision becomes an unbounded language implementation before one slice works. | 5 | 5 | 25 | New syntax/types enter M1–M3 without replacing scope. | Enforce [[Crabwalk Product Contract]], milestone gates, feature-promotion rule, and XL task splitting. Stop active work that lacks a contract fixture. | Project + language | Every planning/PR review |
| R-002 | Python-looking expressions have surprising Rust semantics. | 5 | 5 | 25 | Repeated questions/bugs around division, truthiness, overflow, rebinding, or exceptions. | Publish semantic-difference table, reject ambiguous forms, require explicit conversions, pair every feature with negative tests. | Language | Each milestone |
| R-003 | Compile-at-decoration creates import recursion, partial-module, latency, or error-recovery problems. | 4 | 5 | 20 | Lifecycle spike cannot reliably build/reuse from first decorator across packages/OSes. | ADR-001 spike in M0; source-driven whole-unit compilation; scoped coordinator/lock. Contingency: explicit prebuild, then later import hook research. | Runtime/compiler | M0, M1 |
| R-004 | Native extension versions cannot reload/coexist safely in development. | 3 | 5 | 15 | Second fingerprint collides in sys.modules, PyInit name, classes, or native global state. | Content-address filename/PyO3 name, immutable artifact entries, two-version process test, protocol namespace. Avoid in-place overwrite/unload assumptions. | Runtime | M0, M1, M5 |
| R-005 | rustc errors cannot be mapped precisely to generated-from-Python expressions. | 4 | 5 | 20 | Primary diagnostics frequently fall back to generated files/functions. | SourceSpan in IR from day one; range-recording writer; Cargo/rustc JSON; M0 remap spike; mapping fitness tests. Narrow initial lowering. | Compiler/diagnostics | M0–M3 |
| R-006 | “Existing crates are first class” is mistaken for automatic reflection over arbitrary Rust APIs/macros. | 5 | 4 | 20 | M4 design requires discovering all modules/items/traits/macros before regex works. | Begin with syntactic path/method lowering and rustc as authority; narrow crate demo; defer general macros/metadata. | Language/compiler | M2–M4 |
| R-007 | Ownership wrappers across Python become unsound due to aliasing, reentrancy, exceptions, GC, or threads. | 4 | 5 | 20 | Design relies on Python refcount uniqueness or returns raw borrowed views. | Separate native Owned/Ref/Mut from Python wrapper milestone; explicit state machine/guards; concrete generated types; reject escaping borrows; adversarial/Miri/sanitizer testing. | Runtime/safety | Before and during M5 |
| R-008 | Cross-platform Python/Rust ABI and wheel complexity consumes the roadmap. | 4 | 4 | 16 | Local success but repeated Windows/macOS/linker/wheel failures; support claims exceed CI. | M0 multi-OS smoke, interpreter-specific ABI first, maturin wheel prototype, explicit Tier matrix, no untested support claim. | Release/runtime | Every milestone |
| R-009 | Cargo dependencies, build scripts, or proc macros execute untrusted code during Crabwalk build. | 4 | 5 | 20 | Users assume Python-like import safety or compile untrusted vault/repository content. | Treat build as code execution; warn; expose dependency graph/command; locked/offline options; credential hygiene; no claim of sandboxing. | Security/product | M3, M4, releases |
| R-010 | Cache returns wrong/incompatible/tampered native artifacts. | 3 | 5 | 15 | Rare ABI crashes, stale behavior, or manifest/artifact mismatch. | Comprehensive fingerprint, artifact hashes, versioned schema/protocol, atomic publish, scoped locks, verify before load, corruption tests. | Build/runtime/security | M1–M3 |
| R-011 | Python AST/annotation/import behavior changes across supported Python versions. | 3 | 4 | 12 | Source spans, annotations, or loader tests diverge by Python version. | Parse annotations statically; minimum/latest CI; source-span compatibility layer; version-gated AST handling; explicit support window. | Frontend/release | M0 onward |
| R-012 | Free-threaded CPython invalidates GIL, PyO3, wrapper, or borrow assumptions. | 4 | 4 | 16 | Code treats all CPython builds as the same ABI/thread model. | Explicitly support GIL-enabled CPython first; fingerprint ABI flags; separate abi3/abi3t and Send/Sync decision; dedicated tests before promotion. | Runtime/release | M3, M5 |
| R-013 | PyO3/maturin/Cargo evolution makes pinned implementation assumptions stale. | 4 | 3 | 12 | Tool upgrades break build flags/module macros/artifact location. | Use documented structured interfaces; isolate adapters; record tool versions in fingerprints; MSRV/current CI; upgrade notes and compatibility tests. | Build/release | Scheduled |
| R-014 | Generated Rust is technically correct but too opaque to debug. | 4 | 4 | 16 | Users must inspect line 400 of helpers; diagnostics lack boundary/source context. | Human-readable deterministic output, symbol-focused show, effect inspect, source-first errors, generated details secondary. | Diagnostics/product | M1 onward |
| R-015 | Compile latency makes ordinary import unusable. | 4 | 4 | 16 | Cold imports dominate development; small changes rebuild dependencies/package. | Content cache, shared Cargo target, conservative correctness first then dependency-aware invalidation, timing breakdown, explicit build workflow option. | Build/performance | M1–M3 |
| R-016 | Python runtime calls spread through native code and erase performance/safety value. | 4 | 4 | 16 | Most call graphs contain `PythonRuntime`; users cannot see why. | Typed effects, warn/deny policy, inspect counts, GIL access only at boundaries, native alternatives in diagnostics/docs. | Language/product | M3 onward |
| R-017 | Valid-Python constraint conflicts with proposed Rust vocabulary/syntax. | 3 | 4 | 12 | Examples use rust.None, macro bang syntax, lifetimes, pub/let, or keyword attributes. | Parse every API example with CPython in docs CI; use contextual None and valid helper spellings; syntax ADR before publication. | Language/docs | Every feature |
| R-018 | Python module façades and one Cargo crate create symbol collisions or cycles. | 3 | 4 | 12 | Same names/re-exports/cycles generate duplicate or inaccessible Rust items. | Stable SymbolId, collision-free internal names, explicit visibility, package graph cycle policy, cross-module fixtures. | Frontend/codegen | M2 |
| R-019 | Result/panic/Python exception semantics become inconsistent. | 4 | 4 | 16 | Same error panics, returns wrapper, or raises depending on path/profile. | Accept one exported Result policy, prevent ABI unwind, stable exception hierarchy, boundary matrix and panic tests. | Language/runtime | M0, M2–M3 |
| R-020 | Packaging generated user Rust requires a custom PEP 517 flow that conflicts with existing Python backends. | 4 | 4 | 16 | Wheel prototype works only with manual local steps or replaces user packaging unexpectedly. | Prove explicit Crabwalk/maturin wheel path first; isolate build service; research backend composition after v0.1; document supported project layouts. | Packaging/product | M3 |
| R-021 | Crate resolution is reproducible only while disposable .crabwalk state survives. | 3 | 4 | 12 | Deleting cache changes transitive versions or offline behavior. | Stable committable Cargo lock policy before M4; lock participates in fingerprint; locked/offline tests. | Build | M4 |
| R-022 | Team capacity/bus factor is insufficient for compiler + runtime + packaging + support. | 3 | 4 | 12 | One person owns all critical systems and roadmap estimates continually slip. | Small milestones, executable docs, ADRs, clear seams, reviewable PRs; set alpha support expectations; recruit/reassign based on M1 evidence. | Project owner | Monthly/milestones |

## Immediate risk burn-down order

1. **R-003 lifecycle** — ADR-001 hand-written extension/decorator spike.
2. **R-005 source mapping** — ADR-002 generated span/rustc JSON spike.
3. **R-001 scope** — accept M1 contract before scaffold expands.
4. **R-004 module coexistence** — two fingerprints in one process.
5. **R-002 semantics** — ratify division/overflow/truthiness/None/Result before M2.
6. **R-010 cache integrity** — artifact verification before import-time caching is relied upon.
7. **R-008 packaging portability** — wheel prototype no later than M3.
8. **R-006 crate expectations** — publish static-path limitation before M4.
9. **R-007 ownership soundness** — formal state-machine review before wrapper implementation.

## Constraints already settled by the architecture brief

These are not reopened casually:

| Decision | Settled position |
|---|---|
| DEC-V001 | Source remains valid Python. |
| DEC-V002 | Canonical user namespace is from crabwalk import rust. |
| DEC-V003 | Python owns packages, modules, imports, and re-exports. |
| DEC-V004 | rust.fn compiles to Rust or fails; no silent fallback. |
| DEC-V005 | Rust types denote real Rust choices. |
| DEC-V006 | Cargo is the dependency resolver. |
| DEC-V007 | rustc is the authority for Rust semantics. |
| DEC-V008 | Generated Rust is inspectable. |
| DEC-V009 | Python runtime and conversion boundaries are visible. |
| DEC-V010 | Initial interop uses PyO3. |
| DEC-V011 | Initial package architecture is one generated Cargo crate per Crabwalk-enabled Python distribution. |
| DEC-V012 | Unsafe authoring is not in the MVP. |
| DEC-V013 | Async/concurrency follow semantic stability. |

Changing one requires a product-level architecture revision, not an implementation convenience.

## Provisional defaults

These defaults let planning proceed, but each has an acceptance point.

| ID | Default | Rationale | Accept by | Revisit trigger |
|---|---|---|---|---|
| DEC-P001 | Python compiler frontend through v0.1 | Fast iteration; native output already carries performance work | End M1 | Frontend materially dominates cached/cold latency |
| DEC-P002 | Eager compile at first rust.fn decorator | Closest to intended edit/import/compile flow without an import hook | M0 ADR-001 | Partial import, cycles, reload, or latency cannot be controlled |
| DEC-P003 | Content-addressed native module name | Coexistence and immutable cache safety | M0 ADR-001 | Platform loader/PyO3 evidence disproves it |
| DEC-P004 | Explicit file in M1; pyproject/package discovery in M2 | Keeps proof small without changing PackageIR shape | M0 | M1 decorator cannot derive stable identity |
| DEC-P005 | Direct Cargo for check/build; maturin for wheel prototype | Structured build data without runtime maturin dependency | M0/M3 | Cross-platform artifact handling is unreliable |
| DEC-P006 | Interpreter-specific PyO3 build first | Lowest initial ABI uncertainty | M3 | Wheel matrix cost becomes blocking and API inventory supports stable ABI |
| DEC-P007 | Contextual Python None means Option::None | Valid Python and idiomatic source | SPEC-001 | Ambiguity cannot be diagnosed from expected type |
| DEC-P008 | Conditions require rust.bool | Avoid hidden Python truthiness | SPEC-001 | None expected |
| DEC-P009 | Rust typed division; Python // initially unsupported | Explicit Rust semantics; avoids false equivalence | SPEC-001 | User evidence supports an explicit alternative |
| DEC-P010 | Overflow checks enabled in all early profiles | Predictable behavior across dev/release | SPEC-001 | Performance evidence and explicit wrapping/checked API mature |
| DEC-P011 | Static analysis never imports user modules | Determinism and safety | M1 | A required feature cannot be statically expressed and owner accepts execution risk |
| DEC-P012 | Package-wide invalidation first | Correctness before incremental graph complexity | M2 | Measured rebuild pain justifies finer dependencies |
| DEC-P013 | Deterministic internal formatting before rustfmt | Preserve exact source ranges | M1 | Reliable post-rustfmt source-map reconstruction exists |
| DEC-P014 | General third-party Python calls are post-v0.1; print proves the first boundary | Keeps error/type/import surface bounded | M3 | Product priority explicitly replaces other v0.1 scope |
| DEC-P015 | Static crate path lowering before general crate metadata/reflection | Makes regex proof feasible | M4 | Path syntax cannot produce adequate diagnostics |
| DEC-P016 | Rust-owned Python wrappers are generated per concrete type | Preserves real monomorphized types/state | M5 | ABI/design spike produces a safer general mechanism |

## Decision queue

### Blocking M0/M1

- [ ] **DEC-001 — Project governance and license**
  - Recommended: permissive open-source license compatible with Rust/Python ecosystems, explicit maintainer/security policy.
  - Owner: project owner
  - Evidence: intended community/commercial model.

- [x] **DEC-002 — Exact M1 supported syntax**
  - Recommended: accept the narrow Fibonacci contract verbatim.
  - Owner: language/product
  - Evidence: SPEC-001 reviewed examples and negative cases.

- [x] **DEC-003 — Compile trigger and failure timing**
  - Recommended: eager on first decorator; explicit CLI uses same service; no meta-path hook in M1.
  - Alternatives: explicit prebuild only; lazy first call; import hook.
  - Evidence: ADR-001 on partial modules, recursion, reload, errors, latency, platforms.

- [x] **DEC-004 — Initial Python/Rust/OS support**
  - Recommended: GIL-enabled CPython only; latest stable CPython/current stable Rust for M1; choose v0.1 minimums from dependency and CI evidence.
  - Evidence: tool availability, PyO3 requirements, release capacity.

- [x] **DEC-005 — Generated/cache root and cleanup contract**
  - Recommended: project-local .crabwalk by default, configurable; generated and cache are disposable; no lock state is disposable once crates arrive.
  - Evidence: editable installs, read-only source trees, CI, monorepos.

- [x] **DEC-006 — Integer division and overflow**
  - Recommended: Rust / behavior; reject //; overflow checks in all early profiles.
  - Evidence: product expectation tests and benchmark only after correctness.

- [x] **DEC-007 — Panic and exported Result policy**
  - Recommended: contain panic as dedicated native-panic exception; Result::Err becomes CrabwalkRustError initially.
  - Evidence: ABI spike and user-facing ergonomics review.

- [x] **DEC-008 — Wrapper fallback introspection**
  - Recommended: preserve signature/docs but do not expose an executable original body via __wrapped__.
  - Evidence: inspect/help/framework compatibility versus strict no-fallback guarantee.

### Blocking M2/M3

- [x] **DEC-009 — Package root and import/re-export resolution policy**
- [x] **DEC-010 — Namespace packages and import cycles**
- [x] **DEC-011 — Exact v0.1 operator/type capability matrix**
- [x] **DEC-012 — String/Str boundary lifetime and allocation policy**
- [x] **DEC-013 — Explicit Vec conversion API spelling**
- [x] **DEC-014 — Python exception hierarchy and traceback presentation**
- [x] **DEC-015 — GIL release policy and free-threaded Python support statement**
- [x] **DEC-016 — Supported packaging layouts and wheel command/backend**
- [x] **DEC-017 — ABI strategy: interpreter-specific versus abi3/abi3t**
- [ ] **DEC-018 — Performance regression policy after baselines**

### Blocking M4

- [x] **DEC-019 — Stable user-committable Cargo.lock location**
- [x] **DEC-020 — Registry/path/Git dependency policy**
- [x] **DEC-021 — Locked/offline defaults**
- [x] **DEC-022 — Python spelling for Rust paths, associated items, keywords, and aliases**
- [x] **DEC-023 — Scope of crate API metadata and explicit raw-path escape hatch**
- [x] **DEC-024 — Build-script/procedural-macro trust warning and policy**

### Blocking M5/M6

- [x] **DEC-025 — Formal ownership wrapper state machine**
- [x] **DEC-026 — Reentrancy and borrow-guard policy**
- [x] **DEC-027 — Wrapper thread/Send/Sync policy**
- [x] **DEC-028 — Rust-owned type identity across recompilation**
- [x] **DEC-029 — Valid-Python enum/variant syntax**
- [x] **DEC-030 — Struct field ownership and Python mutation policy**
- [x] **DEC-031 — Pattern-matching subset and exhaustiveness behavior**
- [x] **DEC-032 — Narrow derive/macro support boundary**

## High-priority decision briefs

### DEC-003 — Compile trigger

| Option | Strength | Cost/risk |
|---|---|---|
| Eager first decorator | Natural import behavior; compile failure early; simple public story | Module is partially executing; package graph/reload/latency need control |
| Explicit prebuild | Deterministic and packaging-friendly; no import compiler surprise | Weakens immediate authoring experience; stale artifact handling needed |
| Lazy first call | Fast imports; only used functions build | Violates expected compile-failure timing; first-call latency; process races |
| Meta-path import hook | Can analyze before executing module | Highest import complexity, cycles, debugging, tool compatibility risk |

Recommended experiment: implement eager and explicit prebuild over one BuildCoordinator. Accept eager only if the same artifact/fingerprint is used, errors are deterministic, and two fingerprints coexist. Keep explicit prebuild regardless for CI/packaging.

### DEC-006 — Arithmetic semantics

The product cannot simultaneously promise Python’s operator behavior and “real Rust semantics” for explicit Rust types. Recommended:

- / maps to Rust typed division;
- // is rejected until an explicit mapping exists;
- conditions accept only bool;
- integers are range checked at the Python ABI;
- overflow checks are enabled in all initial build profiles;
- wrapping/saturating/checked operations arrive as explicit Rust APIs.

This should be prominent in documentation and diagnostic suggestions.

### DEC-007 — Errors

Separate four categories:

1. Crabwalk compile/configuration error → CrabwalkCompilationError/CLI diagnostic.
2. Python→Rust conversion failure → TypeError/OverflowError with parameter path.
3. Native Result::Err → CrabwalkRustError initially.
4. Native panic → CrabwalkNativePanic, never an ABI unwind.

Python exceptions raised at explicit Python runtime boundaries propagate with boundary context. This separation prevents every Rust failure from becoming one opaque exception.

### DEC-017 — Stable ABI

Do not choose abi3 or abi3t merely to reduce wheel count. Inventory the PyO3 APIs actually used, measure performance, decide free-threaded support, and test the chosen ABI. Interpreter-specific builds are the conservative alpha default.

### DEC-023 — Crate metadata

Initial crate integration should not depend on a complete Rust reflection service. Mechanically lower resolvable paths and calls, then let rustc validate them. General macros, traits, re-exports, overloaded names, and documentation/type metadata remain a separate capability. If an escape hatch is needed, it must remain valid Python and explicit about unsafely bypassing Crabwalk-level validation (while still generating safe Rust unless otherwise allowed).

### DEC-025 — Ownership wrapper state

Before code:

- define states and atomic transitions;
- define alias visibility;
- define call-scoped guard lifetime;
- define exception and reentrancy cleanup;
- define GC/cycle behavior;
- define thread access;
- define recompilation/type identity;
- prove that no raw &T or &mut T is stored beyond its owner/guard.

If this cannot be proven, M5 must ship only native-island Owned/Ref/Mut and defer Python-crossing borrows.

## Assumptions requiring validation

| ID | Assumption | Validation | Deadline |
|---|---|---|---|
| A-001 | CPython AST spans are sufficient for expression-level maps across supported versions. | Unicode/CRLF/multiline spike | M0/M1 |
| A-002 | A content-addressed PyO3 extension can coexist with another version in one process. | Two-module lifecycle spike | M0 |
| A-003 | Direct Cargo JSON events reliably identify diagnostics and artifacts on all target OSes. | Cross-platform build runner spike | M0/M1 |
| A-004 | A Python frontend is fast enough compared with Cargo build time. | Stage-level profiles | M1/M3 |
| A-005 | One generated crate can preserve Python module/re-export behavior without excessive rebuilds. | Multi-module package fixture | M2 |
| A-006 | Static path lowering is enough for the first crates.io demonstration. | Regex spike | Early M4 |
| A-007 | PyO3 can implement the required conversion/GIL/panic policy without custom CPython ABI work. | ABI matrix tests | M3 |
| A-008 | Concrete wrapper state can preserve moves/borrows safely across Python aliases/reentrancy. | Formal review + adversarial prototype | Before M5 |
| A-009 | A practical wheel flow can integrate generated user code without requiring Rust on consumers. | Clean wheel prototype | M3 |

Failed assumptions trigger an ADR update and roadmap re-estimate; they are not worked around invisibly.

## Decision protocol

Use one record per material syntax, semantic, ABI, cache, packaging, or trust decision.

    # DEC-NNN — Title

    Status: Proposed | Accepted | Rejected | Superseded
    Date:
    Owner:
    Milestone:
    Related risks:

    ## Context
    What must be decided and why now?

    ## Constraints
    Which architectural rules and evidence bound the choice?

    ## Options
    Include “do nothing/defer” where real.

    ## Decision
    State the behavior precisely, including failure behavior.

    ## Consequences
    Benefits, costs, compatibility, security, and migration.

    ## Evidence
    Spike, fixture, benchmark, documentation, or review.

    ## Revisit trigger
    A concrete observation, not “later.”

Rules:

1. A source-syntax decision includes valid/invalid Python examples and CPython parse evidence.
2. A semantics decision includes IR/lowering and boundary effects.
3. An ABI decision includes cross-platform runtime evidence.
4. A cache decision lists fingerprint/invalidation impact.
5. A crate decision lists trust/reproducibility impact.
6. A rejected option remains recorded so the same debate is not repeated without new evidence.

## Risk review cadence

- Every PR: author states introduced/changed risks and decision IDs.
- Weekly during M0–M3: review Critical/High risks, indicators, and mitigation tasks.
- At milestone gate: rescore all risks, validate assumptions, close/split/add risks, and record waivers.
- Before release: security/runtime/packaging owners explicitly sign off their High risks.
- After incident or major dependency/toolchain change: immediate targeted review.

Close a risk only when the failure mode is impossible or fully accepted as ordinary operation. A passing happy-path test lowers uncertainty but does not automatically close a risk.
