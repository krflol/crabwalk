---
aliases:
  - Crabwalk Plan
  - Crabwalk Project
type: project
project: Crabwalk
status: active
phase: 1.1.1 release
created: 2026-08-21
updated: 2026-09-01
tags:
  - project/crabwalk
  - status/active
---

# Crabwalk Project Hub

> [!abstract] Current outcome
> Crabwalk is a published Apache-2.0 compiler/runtime that lowers an explicit,
> source-spanned Python subset into inspectable Rust and CPython extensions.
> Version 1.1.1 hardens embedding, external handles, native adapters, channels,
> integral operators, and borrowed-return composition against real Crabgraph QA.
> Its immutable tag is the source of every tested, attested, and published release
> artifact.

## Sources of truth

- [[crabwalk|Guiding architecture]]
- [[Docs/Crabwalk Getting Started|Getting started]]
- [[Docs/Crabwalk Language Reference|Language reference]]
- [[Docs/Crabwalk Ownership and Domain Types|Ownership and domain types]]
- [[Docs/Crabwalk Tooling Packaging and Cache|Tooling, packaging, and cache]]
- [[Docs/Crabwalk Security and Limitations|Security and limitations]]
- [[Docs/Crabwalk Compatibility and Verification|Compatibility and verification]]
- [[Docs/Release Process|Release process]]
- [[CHANGELOG|Changelog and migration notes]]
- [[GOVERNANCE|Governance]]
- [[SECURITY|Security policy]]

## Implemented release surface

- package-wide static analysis and source-spanned schema-v29 IR/codegen-v46;
- deterministic Rust, PyO3, Cargo, source-map, and mixed-wheel generation;
- typed effects, dispatch propagation, boundary-placement validation, and explicit
  opaque external-crate calls;
- primitive/string/container, structured-domain, borrowed-buffer, and bounded
  native-file boundaries; panic and `Result` translation; and effect-aware GIL
  detachment;
- persisted complete Cargo locks and content-addressed, integrity-checked artifacts;
- coordinated build/prune/load locks, mapped-artifact leases, and uncertainty-aware
  cache accounting;
- `Owned`, `Ref`, and `Mut` handles with move, borrow, reload, GC, and thread checks,
  plus immutable `Shared[T]` Arc handles for approved `Send + Sync` payloads;
- structs, enums, patterns, methods, traits, generics, Rayon, native async, focused
  unsafe demonstrations, TCP, and a finite thread pool;
- recursive nested domains, checked `HashMap` input, bulk 100k-row construction,
  `TextColumn`, explicit boundary telemetry, and owned domain returns;
- metadata-aware PEP 517 wheel/sdist builds for multiple regular/namespace packages;
- typed Python and Cargo adapters, structured application errors/`From`, richer
  traits/generics/operators/closures, and a complete native ETL acceptance path;
- non-executing virtual-package embedding, hard Cargo cancellation, JSON
  diagnostics, watch, explain, LSP, and deterministic Rust export;
- a source-linked adaptation of all 21 Rust Book chapters and end-to-end native
  integration tests;
- CPython 3.11–3.14 validation across Windows, Linux, and macOS.

## Release evidence

1. Generated application wheels resolve the `crabwalk-lang` runtime normally.
2. Release metadata, runtime manifests, CLI output, and distributions share one
   version identity.
3. Ownership, boundary, naming, traits, effects, iterators, patterns, and cache
   invariants have focused positive and negative tests.
4. Ruff, mypy, byte compilation, unit tests, generated Rust formatting/Clippy,
   clean artifact installs, and the complete native suite are release gates.
5. Every exact release tag reruns the complete Windows/Linux/macOS, Python
   3.11–3.14, quality, Miri, and performance gates before Trusted Publishing can
   reach PyPI.

## Guardrails

- Static analysis never imports target modules; Cargo execution is trusted build
  execution and is not sandboxed.
- rustc remains authoritative for Rust typing, ownership, exhaustiveness, and
  dependency APIs; Crabwalk adds Python source and boundary context.
- `.crabwalk/` is disposable; `crabwalk-locks/` is reproducible dependency state.
- External crate internals are opaque unless surfaced through supported operations;
  developers must audit their behavior and build scripts.
- Features are promoted only with semantics, diagnostics, cache/boundary evidence,
  documentation, and the supported platform matrix.

## Next architectural milestone

After 1.1.1, stabilize adoption rather than immediately expanding syntax: add PEP
660 application-editable support, deepen editor services beyond diagnostics,
continue extracting the stateful frontend/cross-boundary runtime, and use real
application telemetry to tune bulk construction and output representations.

Writable or strided buffers, retained cross-call borrows, general async runtimes,
arbitrary FFI, and free-threaded CPython remain deferred until their ownership and
lifecycle contracts can be made explicit.
