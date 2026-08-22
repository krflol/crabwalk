---
aliases:
  - Rust Book Evolution Plan
  - Crabwalk Rust Book Plan
type: execution-plan
project: Crabwalk
status: verification
created: 2026-08-21
updated: 2026-08-21
tags:
  - project/crabwalk
  - area/compiler
  - area/examples
  - status/verification
---

# Rust Book End-to-End Evolution

> [!abstract] Outcome
> Maintain a runnable Crabwalk adaptation of all 21 chapters of *The Rust Programming Language*. Each chapter must link to its official source, explain the Python-to-Rust spelling, compile into the same native package, and drive missing Crabwalk features through IR, code generation, runtime, tests, documentation, and cache-version changes.

This plan is the execution companion to [[Crabwalk Roadmap]]. The runnable suite and its chapter-level evidence live in [examples/the_rust_book](../examples/the_rust_book/README.md); the exact coverage posture is in [COVERAGE.md](../examples/the_rust_book/COVERAGE.md).

## Source baseline

- Upstream: [The Rust Programming Language](https://doc.rust-lang.org/book/)
- Source repository: [rust-lang/book](https://github.com/rust-lang/book)
- Adaptation baseline commit: `917544888a55e4da7109bdba8c88c893c0da70f4`
- Baseline captured: 2026-08-21
- Edition represented by that snapshot: the current 21-chapter Book, including the dedicated async chapter and the final web-server project

The examples paraphrase and adapt the Book rather than reproducing its prose. Every example family carries a direct official documentation link. The two HTML assets in Chapter 21 reproduce the Book's sample pages and remain tied to their source listing.

## Definition of done

A chapter is complete only when all applicable gates are satisfied:

1. Its module is valid ordinary Python and imports only the canonical `rust` namespace.
2. Each represented example family has explanatory comments and a direct official source link.
3. The behavior is native Rust, not a Python fallback or a mocked result.
4. Any newly required syntax has source-spanned IR and deterministic code generation.
5. The feature has a focused frontend/codegen test and, where observable, a cold native integration test.
6. Misuse is rejected by Crabwalk or rustc rather than silently changing semantics.
7. The package-wide runner imports the chapter and asserts its boundary-visible behavior.
8. Compiler/codegen cache schemas are bumped whenever cached output semantics change.
9. Public docs identify supported syntax, deliberate adaptations, and remaining constraints.
10. Chapters 1 through the new chapter still compile together as one extension.

## Evolution loop

```mermaid
flowchart LR
    B[Book example] --> G[Identify semantic gap]
    G --> S[Design valid-Python spelling]
    S --> I[Typed, source-spanned IR]
    I --> R[Deterministic Rust generation]
    R --> N[Cold native proof]
    N --> P[Package-wide regression]
    P --> D[Docs and coverage]
    D --> B
```

The loop is intentionally vertical. A helper name without IR, a code generator branch without native evidence, or a passing isolated fixture that breaks the package does not count as progress.

## Workstreams

### WS1 — Source adaptation and provenance

- [x] Establish the pinned upstream baseline.
- [x] Create one chapter module for Chapters 1–21.
- [x] Add direct official links beside every example family.
- [x] Explain semantic substitutions forced by valid Python grammar.
- [x] Preserve the Chapter 21 HTML assets.
- [x] Add a chapter and feature coverage matrix.
- [ ] Re-audit links and headings when intentionally rebasing to a newer Book commit.

### WS2 — Core compiler evolution

- [x] Bindings, constants, shadowing, chars, tuples, arrays, indexing, and destructuring.
- [x] String, Vec, HashMap, Option, Result, `?`, and panic semantics.
- [x] Structs, unit/tuple/record enums, nested domain payloads, and construction.
- [x] Generics, trait bounds, named lifetimes, and native monomorphization.
- [x] Closures, iterator adapters, loops, and Vec-return boundaries.
- [x] Box, Rc, RefCell, Arc, Mutex, threads, and channels.
- [x] Native async functions, await, join/select, channels, and a std-only executor.
- [x] Inherent methods, trait implementations, trait objects, and dynamic dispatch.
- [x] General patterns: literals, or/ranges, guards, tuple/rest, nested domain patterns, and `@` bindings.
- [x] Advanced slices: audited unsafe operations, `Add<Rhs>`, UFCS trait calls, function pointers, closure trait objects, and local aliases.
- [x] TcpListener/TcpStream and a finite channel-backed ThreadPool with graceful Drop.

### WS3 — Runtime and ABI evolution

- [x] Checked scalar, string, Option, and Result boundaries.
- [x] Explicit Owned/Ref/Mut wrappers for Vec and domain objects.
- [x] Recursive fixed-tuple input validation.
- [x] Panic containment for ordinary, unsafe, and thread-pool construction paths.
- [x] GIL release for eligible native socket and compute work.
- [x] Compilation progress output on stderr with interactive and durable modes.
- [ ] Decide whether nested domain enum payloads should gain consuming Python constructors/getters; native compiled use is supported now.

### WS4 — Verification

- [x] Unit evidence for each delivered IR/codegen family.
- [x] Native evidence for patterns, advanced features, networking, and the pool.
- [x] One native package runner covering Chapters 1–21.
- [x] Chapter 11 pytest examples, including expected panic behavior.
- [x] Run the full repository suite after documentation reconciliation.
- [x] Run the configured formatter/linter and Python byte-compilation checks.
- [ ] Record Linux/macOS and CPython 3.12–3.14 evidence in [[Crabwalk Verification and Release]].

### WS5 — Product documentation

- [x] Add the example execution guide and coverage manifest.
- [x] Add this end-to-end evolution plan to the vault.
- [x] Reconcile the language reference, project hub, security notes, and changelog with the promoted surface.
- [x] Add generated-Rust evidence to the compatibility record after the full suite is green.

## Milestone history

| Wave | Chapters | Main compiler outcomes | Status |
|---|---:|---|---|
| A | 1–4 | primitives, control flow, ownership handles, strings | Complete |
| B | 5–9 | structs, enums, match, collections, Result/panic | Complete |
| C | 10–14 | generics, lifetimes, tests, package graph, crates | Complete |
| D | 15–18 | smart pointers, concurrency, async, methods, trait objects | Complete |
| E | 19 | general patterns, nested payloads, tuple ABI and loop patterns | Complete |
| F | 20 | explicit unsafe slices, advanced traits/operators/types/functions/macros | Complete with documented safety constraints |
| G | 21 | loopback HTTP, finite ThreadPool, validation, graceful Drop | Complete |
| H | all | docs reconciliation, full suite, cross-platform release evidence | Local verification complete; release matrix pending |

## Verification matrix

| Layer | Evidence | Required command |
|---|---|---|
| Python syntax | Every module compiles as Python | `python -m compileall -q examples/the_rust_book` |
| Frontend/codegen | Focused unit suite | `python -m pytest tests/unit -q` |
| Native vertical slices | Integration suite | `python -m pytest tests/integration -q` |
| Book package | All chapters in one extension | from `examples`: `python -m the_rust_book.run_all` |
| Chapter 11 teaching tests | pytest behavior and panic mapping | `python -m pytest examples/the_rust_book/test_ch11_automated_tests.py -q` |
| Generated output | Human inspection | `crabwalk expand examples/the_rust_book/__init__.py` |
| Cache/progress | Cold build and cache-hit runs | run once with `CRABWALK_PROGRESS=always`, then rerun unchanged |
| Reproducible dependencies | Locked package build | `crabwalk check examples/the_rust_book/__init__.py --locked` |

### Local verification snapshot

On Windows x86-64 with CPython 3.11.8 and rustc/Cargo 1.97.0 on
2026-08-22:

- `python -m pytest -q`: **124 passed in 812.82 seconds** on the final formatted worktree.
- `python -m pytest tests/unit -q`: **89 passed in 8.62 seconds** after final formatting.
- Chapter 11 teaching suite: **5 passed in 3.70 seconds**.
- The Chapters 1–21 native runner printed its all-assertions-passed marker.
- Locked `crabwalk check` completed after the package rename and invariant
  hardening with fingerprint `407206a49c3e33f0`.
- `ruff format` accepted all 108 Python files unchanged, `ruff check`, scoped mypy
  over 13 source modules, and `python -m compileall -q src tests examples` passed.
- Expanded Rust was inspected for the generated `Add` implementations, UFCS
  calls, bounded raw-pointer/slice blocks, closure trait objects, loopback
  `TcpListener`, job type, and joining `ThreadPool::drop` path.

The current mypy gate includes naming and code generation but intentionally leaves
the large frontend, runtime binder, and CLI as explicit typing debt.

## Risk register

| Risk | Consequence | Mitigation / gate |
|---|---|---|
| Example drift from upstream | Links or concepts stop matching | Pin the Book commit; rebase only as an explicit project change |
| Valid Python cannot spell a Rust construct | Misleading pseudo-Rust surface | Use a narrow compiler marker and show the emitted Rust spelling in comments/tests |
| High-level intrinsic hides safety obligations | “Unsafe” example becomes magic | Keep intrinsics bounded, emit auditable unsafe blocks, and test generated source |
| Isolated feature breaks package composition | Chapter test passes but suite fails | Require the single-crate Chapters 1–21 runner after every wave |
| Cache masks codegen edits | Stale native artifact produces false green | Increment IR/codegen schemas for semantic output changes |
| Socket test flakes or leaves a process | Unreliable CI or port conflicts | Bind `127.0.0.1:0`, serve one request, close streams, and join pool workers |
| Thread pool deadlocks during Drop | Hanging imports/tests | Drop sender before drain/join; use FIFO jobs and bounded integration timeouts |
| Examples overstate general support | Users depend on a teaching-only slice | Label constrained capabilities in coverage and the language reference |
| Unsafe API broadens accidentally | Undefined behavior reachable from ordinary data | No raw escape hatch; accept only checked local Copy values and bounded slice construction |

## Deliberate constraints

The suite demonstrates the Book end to end, but it does not claim Crabwalk is a complete Rust syntax frontend:

- Python has no `if let`, `while let`, `let ... else`, tuple function parameters, or Rust `@` spelling. The examples use exhaustive `match`, an explicit loop match, immediate destructuring, and `pattern as name` respectively.
- Unsafe support is a reviewed teaching surface, not arbitrary inline Rust. Arbitrary pointer dereference, unions, user-authored unsafe traits, and a general unsafe escape hatch remain unsupported.
- Trait declarations remain object-safe shared methods with concrete returns. Associated `Iterator::Item`, generic bounds, `Add<Rhs>`, and UFCS are delivered through focused typed paths.
- The closure examples produce real `fn` pointers and `Box<dyn Fn>` values inside generated Rust but do not export callable Rust closures as Python objects.
- Chapter 21 is a bounded loopback proof. It intentionally does not start a persistent production server, provide TLS, parse arbitrary HTTP, or expose an externally managed background service.

## Change protocol

For every new Book revision or Crabwalk capability:

1. Record the upstream commit and changed chapter/listing.
2. Classify the example as direct, syntax-adapted, compile-fail evidence, or explanatory-only.
3. Add or revise the smallest typed surface.
4. Update IR and codegen schemas if cached semantics change.
5. Add positive and misuse tests before adding the runner assertion.
6. Run the focused native test and then the all-chapter package.
7. Update [COVERAGE.md](../examples/the_rust_book/COVERAGE.md), the language reference, limitations, and changelog.
8. Promote the capability only after the full verification gate is green.

## Final acceptance

The evolution is ready for release evidence when:

- [x] Chapters 1–21 run together natively.
- [x] Every chapter module links to official source material.
- [x] New compiler slices have focused unit and native tests.
- [x] The final web server is bounded and cleans up all OS resources.
- [x] The full repository test suite is green from the current worktree.
- [x] Public docs and limitations match the implemented surface.
- [ ] Cross-platform CI evidence is recorded.
- [ ] The repository's governance/license decision permits distributing the adaptations.
