---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-23
tags:
  - project/crabwalk
  - docs/testing
---

# Crabwalk Compatibility and Verification

## Supported release matrix

| Dimension | Policy |
|---|---|
| Python | CPython 3.11–3.14; interpreter-specific extension ABI |
| Rust | current stable toolchain; local evidence: rustc/Cargo 1.97.0 |
| PyO3 | pinned to 0.29.2 with `extension-module` plus `pyo3-build-config` link setup |
| OS | Windows, Linux, and macOS in the required GitHub Actions native matrix |
| Profile | Cargo release profile with overflow checks enabled |
| Package | regular Python package or standalone module for source use |

The CPython range and operating systems above are release-tested targets. Native
application artifacts remain interpreter-, operating-system-, and architecture-
specific; Crabwalk's own compiler/runtime distribution is pure Python.

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

Benchmark output is evidence only when it records the toolchain, interpreter,
machine, cold/warm boundary, and repeated samples beside the tested commit.

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

On 2026-08-23, the 1.0.2 development worktree was exercised on CPython 3.11.8 and
Windows x86-64 with rustc/Cargo 1.97.0:

- all **231 unit tests** passed;
- all **35 native integration tests** passed in four bounded batches, for **266
  tests total**;
- the Python-runtime plus `Result` subprocess proved that Python work executes,
  `Ok` returns normally, `Err` becomes `CrabwalkRustError`, and a panic becomes
  `CrabwalkPanicError`;
- the rustc identifier oracle accepted every supported Rust 2024 weak keyword in
  function, parameter, local, closure, pattern, field, variant, method, generic,
  lifetime, and crate-alias positions;
- cache corruption/concurrency, unsafe boundaries, ownership/load order, package
  graphs, async/threading, the Chapter 1–21 Rust Book package, TCP, and consumer
  wheel tests all passed through real native subprocesses;
- Ruff format/lint passed across 115 Python files, scoped mypy passed across 14
  hardening/build/compiler modules, and Python byte-compilation passed;
- rustfmt and Clippy correctness passed on the generated Rust Book Cargo project;
  and
- a no-cache public install fetched `crabwalk-lang==1.0.1` from PyPI, after which a
  second clean environment installed a generated application wheel through normal
  dependency resolution and executed its embedded native function.

The large frontend, runtime binder, and CLI remain explicit typing debt outside the
current scoped mypy boundary.

GitHub Actions
[run 32664652258](https://github.com/krflol/crabwalk/actions/runs/32664652258)
passed all nine jobs for reviewed head `be1fb7d` on 2026-08-23: the complete native
suite on Windows, Linux, and macOS for CPython 3.11 and 3.14, unit lanes for CPython
3.12 and 3.13, and the quality gate. Every subsequent release candidate must pass
the same matrix on its exact SHA.

The exact release candidate must pass this nine-job matrix before publication;
the repository changelog records candidate-specific fixes and migration notes.
