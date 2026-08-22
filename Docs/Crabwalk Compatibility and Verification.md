---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-21
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
| PyO3 | pinned to 0.29.2 in generated Cargo manifests |
| OS | Windows, Linux, macOS are CI targets; Windows x86-64 is locally verified |
| Profile | Cargo release profile with overflow checks enabled |
| Package | regular Python package or standalone module for source use |

The range is a test target, not a promise that an unrun platform works. A release
requires green CI artifacts for every advertised OS/Python pair.

## Test layers

```text
tests/unit/
  AST discovery and rejection
  typed IR and effect propagation
  deterministic Rust/Cargo generation
  package graph and crate lowering
  ownership/domain/match lowering
  diagnostics, fingerprints, cache pruning, inspection, wheel format

tests/integration/
  native Fibonacci and cache reuse
  package/re-export/crates.io, path, feature, and pinned Git extensions
  crate API and dependency-resolution source mapping
  move/borrow, reload, GC, thread, reentrancy, and rustc ownership failures
  structs/Serde and enums/exhaustiveness
  panic, conversion, Result error, and GIL behavior
  corruption and simultaneous-process cache publication
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

On 2026-08-21, the current worktree was exercised on CPython 3.11.8 and Windows
x86-64 with rustc/Cargo 1.97.0:

- the complete repository suite passed **74 tests in 510.42 seconds** on the
  final formatted worktree;
- the final post-format unit pass passed **45 tests in 1.57 seconds**;
- the Rust Book Chapter 11 teaching suite passed **5 tests in 9.42 seconds**;
- the single native Rust Book package passed its Chapter 1–21 assertions;
- locked package checking succeeded with fingerprint `bc77da16a1b9dcf6`;
- `ruff format --check` accepted all 99 Python files, `ruff check` passed, and
  Python byte-compilation passed for `src`, `tests`, and `examples`;
- forced progress output reported analysis, fingerprinting, lock, cache, Cargo,
  load, and ready phases on stderr; and
- expanded Rust was inspected for real operator impls, UFCS, bounded unsafe
  blocks, closure trait objects, TCP binding, and graceful thread-pool Drop.

No mypy configuration or executable is present, so this record does not claim a
mypy pass. Earlier local release-baseline evidence also covered the native linker
probe, clean two-wheel consumer, and runtime distribution inventory. These remain
local candidate results, not release artifacts; the GitHub OS/Python matrix has
not yet run.

The deeper release checklist remains in
[[Planning/Crabwalk Verification and Release]].
