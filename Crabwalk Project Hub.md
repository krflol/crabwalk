---
aliases:
  - Crabwalk Plan
  - Crabwalk Project
type: project
project: Crabwalk
status: active
phase: 1.0.2 development
created: 2026-08-21
updated: 2026-08-23
tags:
  - project/crabwalk
  - status/active
---

# Crabwalk Project Hub

> [!abstract] Current outcome
> Crabwalk is a published Apache-2.0 compiler/runtime that lowers an explicit,
> source-spanned Python subset into inspectable Rust and CPython extensions.
> Version 1.0.1 is published; `main` now identifies as 1.0.2.dev0.

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

- package-wide static analysis and source-spanned schema-v18 IR;
- deterministic Rust, PyO3, Cargo, source-map, and mixed-wheel generation;
- typed effects, dispatch propagation, boundary-placement validation, and explicit
  opaque external-crate calls;
- primitive/string/container boundaries, panic and `Result` translation, and
  effect-aware GIL detachment;
- persisted complete Cargo locks and content-addressed, integrity-checked artifacts;
- coordinated build/prune/load locks, mapped-artifact leases, and uncertainty-aware
  cache accounting;
- `Owned`, `Ref`, and `Mut` handles with move, borrow, reload, GC, and thread checks;
- structs, enums, patterns, methods, traits, generics, Rayon, native async, focused
  unsafe demonstrations, TCP, and a finite thread pool;
- a source-linked adaptation of all 21 Rust Book chapters and end-to-end native
  integration tests;
- CPython 3.11–3.14 validation across Windows, Linux, and macOS.

## 1.0.1 release evidence

1. Generated wheels resolve `crabwalk-lang` normally through pip.
2. Release metadata, runtime manifests, CLI, and artifacts identify 1.0.1.
3. Local-name, pyclass-member, trait-contract, and Unicode-scalar diagnostics pass.
4. Busy cache entries never produce falsely exact size-limit claims.
5. Ruff, mypy, byte-compilation, unit tests, generated Rust formatting/Clippy, and
   the complete native suite pass.
6. The exact release commit passed all nine GitHub Actions jobs.
7. The wheel and sdist are published on PyPI and attached to GitHub release
   `v1.0.1`; public-index clean-install and SHA-256 checks pass.

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

Before another broad syntax expansion, split source and emitted identities for
parameters, locals, loops, closures, patterns, generic parameters, lifetimes, and
domain members. A compiler-owned gensym allocator should make emitted Rust names
injective without forcing natural Python spellings into an ever-growing denylist.

After that consolidation, prioritize a real PEP 517 packaging path and then a
narrow read-only, contiguous primitive buffer boundary. Writable/strided buffers,
general async runtimes, arbitrary FFI, and free-threaded CPython remain deferred.
