---
aliases:
  - Crabwalk Plan
  - Crabwalk Project
type: project
project: Crabwalk
status: verification
phase: Alpha implementation and compatibility verification
created: 2026-08-21
updated: 2026-08-22
tags:
  - project/crabwalk
  - status/verification
---

# Crabwalk Project Hub

> [!warning] Invariant-hardening feature freeze
> The immediate target is [[Planning/Crabwalk Invariant Hardening]]. New language
> work is paused until the reviewed safety, identity, cache, lifecycle, and wheel
> invariants have interaction evidence and the release matrix is green.

> [!abstract] Intended outcome
> Ship a compiler/runtime toolchain that turns explicitly annotated, valid Python into real Rust, exposes ordinary Python-callable native objects, and makes every unsupported construct, conversion, ownership transition, and Python runtime crossing visible.

> [!important] Current target
> Stabilize the implemented M1–M6 surface and narrow M7 concurrency slice, run the advertised cross-platform/CPython matrix, and promote only behavior backed by clean source, cache, native ABI, crate, ownership, domain, Rayon, and wheel evidence.

## Project sources of truth

- [[Planning/Crabwalk Invariant Hardening|Invariant hardening]] — review-to-fix register, compiler invariants, and feature-freeze exit gate.

- [[crabwalk|Product vision and guiding architecture]] — durable goals and design principles.
- [[Planning/Crabwalk Product Contract|Product contract]] — the original release boundary and semantics.
- [[Planning/Crabwalk Architecture Plan|Architecture plan]] — lifecycle, IR, code generation, build, ABI, and cache design.
- [[Planning/Crabwalk Roadmap|Roadmap and work breakdown]] — milestone tasks and exit gates.
- [[Planning/Crabwalk Verification and Release|Verification and release plan]] — required test and release evidence.
- [[Planning/Rust Book End-to-End Evolution|Rust Book end-to-end evolution]] — chapter-driven compiler expansion, coverage, and gates.
- [[Planning/Crabwalk Alpha Artifact Inventory|Alpha artifact inventory]] — protocols, inputs, and still-required release outputs.
- [[Planning/Crabwalk Risks and Decisions|Risks and decisions]] — risk register and unresolved product choices.
- [[Docs/Crabwalk Getting Started|Getting started]] — the implemented user path.
- [[Docs/Crabwalk Language Reference|Language reference]] — accepted syntax and semantics today.
- [[Docs/Crabwalk Security and Limitations|Security and limitations]] — trust boundary and deferred behavior.

## Implementation snapshot

As of 2026-08-22, the repository contains a working vertical compiler/runtime in an invariant-hardening feature freeze:

- static, package-wide Python AST analysis and source-spanned schema-v17 IR;
- typed native, conversion, Python runtime, blocking, threading, mutation, unsafe, and panic effects;
- deterministic Rust/PyO3/Cargo generation and Python-mapped rustc diagnostics;
- native recursion, primitives, locals, control flow, String/Str, Vec, Option, and Result;
- runnable native adaptations of all 21 Rust Book chapters, including patterns, advanced features, and the bounded web-server project;
- package imports/re-exports plus crates.io, path, and Git Cargo dependencies and locks;
- checked ABI conversions, typed Result/panic errors, effect-driven GIL release, synchronized teaching state, guarded C FFI, and non-panicking ThreadPool destruction;
- verified concurrent artifact cache, complete-fingerprint loaded identity, corruption recovery, inspection, access-aware bounded pruning, and conventional Cargo lock maintenance;
- Owned/Ref/Mut values with Python-visible move and call-scoped borrow enforcement;
- structs, unit/tuple/record enums, match exhaustiveness, narrow derives, and Serde evidence;
- Rayon-native iteration and a restricted, explicit Python executor async boundary;
- clean Crabwalk and regex-backed user wheels running without Rust/Cargo on the consumer.

## North-star acceptance evidence

The original recursive Fibonacci scenario now passes all intended checks:

1. Source remains valid Python and uses the canonical `rust` namespace.
2. The body and recursive calls execute inside one generated Rust extension.
3. Exported values receive exact type/range checks with no Python fallback.
4. Generated Rust, ABI wrappers, effects, Cargo inputs, and fingerprints are inspectable.
5. A valid second-process cache hit launches no rebuild and verifies the artifact hash.
6. Unsupported Python syntax fails at its original source span.
7. rustc failures retain compiler detail and map back to Python.
8. Native panics are contained and eligible work releases the GIL.

The proof has expanded to package graphs, regex, ownership, domain models, Rayon,
cache races/corruption, and a toolchain-free wheel consumer. See
[[Docs/Crabwalk Compatibility and Verification]].

## Milestone posture

| Milestone | Implemented evidence | Remaining release work |
|---|---|---|
| M0 | contract, repository, doctor, fixture harness | governance/license decision |
| M1 | complete Fibonacci compile/load/cache/diagnostic slice | cross-platform confirmation |
| M2 | typed core and regular-package graph | explicit multi-package project config |
| M3 | effects, conversions, Python boundary, ABI/cache/CLI/wheel hardening | performance budgets and full CI matrix |
| M4 | Cargo declarations, locks, mapped resolution/API failures, crates.io/path/feature/pinned-Git native proofs | broaden external ecosystem/version coverage |
| M5 | Vec/domain ownership handles, moves, borrows, lifetime rejection | general Send/Sync/thread transfer remains deferred |
| M6 | structs, nested enum payloads, general patterns, methods, trait objects, derives, Serde | nested-domain Python constructor/getter conversion remains deferred |
| M7 | Rayon, native async teaching executor, threads/channels, loopback TCP, and finite ThreadPool | Tokio/reactor I/O, cancellation, and wrapper transfer remain research |

## Current execution queue

The detailed, status-bearing queue is maintained in
[[Planning/Crabwalk Invariant Hardening]]. Release work below follows its exit gate.

1. Run Windows/Linux/macOS × CPython 3.11/3.14 native CI and intermediate-version unit lanes.
2. Record repeated cold/warm/cache/call/conversion benchmarks and set evidence-based budgets.
3. Decide governance, license, release channel, support window, and PEP 517 backend direction.
4. Decide namespace-package and multiple-top-level-package configuration before widening discovery.
5. Run the release checklist, archive clean-install artifacts, then cut an alpha.

## Guardrails

- A feature is supported only with syntax, semantics, IR/effects, lowering, positive and negative evidence, diagnostics, cache coverage, and user documentation.
- rustc remains authoritative for Rust typing, ownership, exhaustiveness, dependencies, and safety checks; Crabwalk adds Python context.
- Static analysis never imports user modules. Cargo compilation is trusted code execution and is not sandboxed.
- Generated `.crabwalk/` state is disposable. Persisted `crabwalk-locks/` state is part of reproducible dependency resolution.
- Native timing alone is not evidence; generated call edges, wrapper policy, tracing, and ABI tests are.
- General Python object compilation, arbitrary unsafe/raw Rust, arbitrary macros/traits, namespace packages, Tokio, and cross-thread Python ownership wrappers remain outside the implemented contract.

## Project cadence

At each release increment:

1. Freeze the promoted contract.
2. Add the smallest complete vertical behavior.
3. Add positive, misuse, diagnostic, cache, boundary, and platform evidence.
4. Update decisions, risks, reference docs, and generated examples.
5. Run clean source and wheel demonstrations.
6. Promote only after the matching exit gate is green or explicitly waived.
