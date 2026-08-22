---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-22
tags:
  - project/crabwalk
  - docs/testing
---

# Crabwalk Compatibility and Verification

## Advertised alpha matrix

| Dimension | Policy |
|---|---|
| Python | CPython 3.11–3.14; interpreter-specific extension ABI |
| Rust | current stable toolchain; local evidence: rustc/Cargo 1.97.0 |
| PyO3 | pinned to 0.29.2 with `extension-module` plus `pyo3-build-config` link setup |
| OS | Windows, Linux, macOS are CI targets; Windows x86-64 is locally verified |
| Profile | Cargo release profile with overflow checks enabled |
| Package | regular Python package or standalone module for source use |

The range is a test target, not a promise that an unrun platform works. A release
requires green CI artifacts for every advertised OS/Python pair.

## Test layers

```text
tests/unit/
  AST discovery and rejection
  typed IR, complete dispatch effects, and boundary-placement rejection
  deterministic Rust/Cargo generation
  parent-initializer package graph and crate lowering
  semantic receiver/place ownership, domain, and match lowering
  generated namespace uniqueness and mandatory-lock identity
  diagnostics, fingerprints, cache pruning, inspection, wheel format

tests/integration/
  native Fibonacci and cache reuse
  package/re-export/crates.io, path, feature, and pinned Git extensions
  crate API and dependency-resolution source mapping
  move/borrow, reload, GC, thread, reentrancy, and rustc ownership failures
  structs/Serde and enums/exhaustiveness
  panic, conversion, Result error, and GIL behavior
  unsafe FFI/global/thread-pool subprocess containment
  corruption, simultaneous publication, prune/build/load stress, and mapped-DLL leases
  complete-fingerprint ownership/load-order identity
  generated-name collision smoke through rustc/PyO3
  Rayon and Python async boundary
  clean Crabwalk + regex application wheel install without Rust/Cargo
```

Run the fast compiler suite:

```powershell
python -m pytest tests/unit -q
```

Run one native area:

```powershell
python -m pytest tests/integration/test_native_abi.py -q
```

Run the release-level local suite:

```powershell
crabwalk doctor
python -m pytest -q
```

Record an isolated performance sample with:

```powershell
python benchmarks/run_baseline.py
```

The benchmark policy and promotion requirements are in
[[Planning/Crabwalk Performance Baseline]].

## Evidence rules

- Native execution is proven by loaded extension symbols, direct generated Rust
  call edges, zero traced Python frames for recursive bodies, and GIL-progress
  tests—not timing alone.
- Cache hits are validated with the manifest/artifact hash and second-process
  behavior. Corruption must rebuild; simultaneous processes must publish one valid
  artifact.
- A compile failure passes only when the primary diagnostic maps to Python source
  and retains relevant rustc detail/code.
- Wheel evidence uses a new venv, installs a normal Crabwalk wheel and a mixed user
  wheel, removes source `PYTHONPATH` and Rust/Cargo discovery, runs primitive,
  struct, and regex calls, and verifies no consumer build workspace appears.
- Unsupported syntax needs a stable diagnostic and an actionable alternative.

## Known local result

On 2026-08-22, the invariant-hardened worktree was exercised on CPython 3.11.8 and Windows
x86-64 with rustc/Cargo 1.97.0:

- the complete repository suite passed **124 tests in 812.82 seconds** on the
  formatted, linted, scoped-mypy-clean worktree;
- the final focused unit pass passed **89 tests in 8.62 seconds**, and the five
  Chapter 11 teaching tests passed in **3.70 seconds**;
- the single native Rust Book package passed its Chapter 1–21 assertions;
- locked checking of `examples/the_rust_book` passed with fingerprint
  `9394c710f14a05e0`;
- dispatch/placement, semantic receiver/place, generated-namespace, mandatory-lock,
  repaired-cache-age, and parent-initializer-cycle regressions passed, including a
  real native `abs`/`String`/`pyo3` collision smoke;
- unsafe `i32::MIN`, atomic concurrency, worker/outer/double-panic, and ambient
  `panic=abort` cases passed in isolated subprocesses;
- cache evidence covered corruption, interrupted/simultaneous publication,
  same-process path-asset invalidation, process-lifetime load leases, and a second
  crate-backed process validating without replacing the mapped DLL;
- the clean mixed wheel installed beside the Crabwalk runtime wheel and imported
  with Rust/Cargo removed from `PATH`;
- `ruff format` accepted all 108 Python files unchanged, Ruff lint, scoped mypy, and
  Python byte-compilation passed for `src`, `tests`, and `examples`;
- rustfmt parsed/stabilized the generated Rust Book project and Clippy's
  correctness lint group passed;
- forced progress output reported analysis, fingerprinting, lock, cache, Cargo,
  load, and ready phases on stderr; and
- expanded Rust was inspected for real operator impls, UFCS, bounded unsafe
  blocks, closure trait objects, TCP binding, and graceful thread-pool Drop.

The mypy gate intentionally covers 13 hardening/build/compiler modules, including
the generated-name and code-generation modules; the large frontend, runtime binder,
and CLI remain explicit typing debt.
These are local candidate results, not release artifacts; the GitHub OS/Python
matrix has not yet run.

The deeper release checklist remains in
[[Planning/Crabwalk Verification and Release]].
