---
type: execution-plan
project: Crabwalk
status: in-progress
created: 2026-08-22
updated: 2026-08-22
reviewed-commit: af7726aab9491b29926bc768afbf43569e995569
tags:
  - project/crabwalk
  - area/safety
  - area/compiler
  - area/cache
  - area/release
---

# Crabwalk Invariant Hardening

This is the feature-freeze execution plan prompted by the static review of
`af7726aab9491b29926bc768afbf43569e995569`. It supersedes feature expansion as
the immediate queue. The Rust Book evolution suite remains the end-to-end
contract, now at [[../examples/the_rust_book/README|examples/the_rust_book]].

> [!important] Promotion rule
> No new language feature enters the alpha contract until every P0/P1 item below
> is closed, the interaction suite is green, and release evidence is archived.

## Outcomes

1. A safe Python caller cannot trigger Rust undefined behavior through a reviewed
   unsafe helper.
2. Every exported panic path unwinds into `CrabwalkPanicError`; destructors never
   introduce an abort through double panic.
3. GIL and ABI policy are derived from typed semantic effects, not a signature
   heuristic alone.
4. Native owned-value and loaded-extension identity are explicit and independent
   of module import order or a fixed Python stack depth.
5. Cache reuse is honest about modeled Cargo inputs, dependency-lock maintenance,
   loaded DLL lifetime, and pruning races.
6. Unsupported package/runtime semantics fail at a source span instead of silently
   approximating Python.
7. Wheels reject runtime-ABI mismatch and package only an explicit data boundary.
8. Every hardening claim has a unit, native, subprocess, multiprocess, or clean
   wheel oracle.

## Review finding register

| Finding | Disposition | Primary implementation | Required evidence | Status |
|---|---|---|---|---|
| P0-1 mutable static data race | Generate an `AtomicU64` checked increment; classify global mutation; keep the GIL for the current unsafe export | `compiler/codegen.py`, `compiler/frontend.py`, `compiler/ir.py` | concurrent subprocess calls, generated-source assertion | Complete locally |
| P0-2 C `abs(i32::MIN)` UB | Guard the C precondition before the unsafe call and map the panic | `compiler/codegen.py` | isolated `-2147483648` subprocess | Complete locally |
| P0-3 thread-pool double panic | Catch worker jobs, record first failure, expose `finish()`, make `Drop` non-panicking, force unwind profile | `compiler/codegen.py`, `build/cargo.py` | worker-only, outer-only, combined-panic, and abort-override subprocesses | Complete locally |
| P1-1 ambient owned identity | Remove latest-loaded fallback and fixed-depth stack walking; resolve caller-bound or sole candidate; add explicit `for_=` context | `runtime.py`, `rust.py` | two packages in both load orders plus ambiguity error | Complete locally |
| P1-2 weak in-process memo | Always derive the complete fingerprint; reuse loaded results by source anchor and complete fingerprint across service instances | `service.py`, `runtime.py`, `compiler/frontend.py` | same-process dependency change and loaded-DLL regression | Complete locally |
| P1-3 incomplete Cargo inputs | Hash complete path trees, project-local toolchain/config state, declared extra files/env, and validate crate cache hits with Cargo | `build/fingerprint.py`, `config.py`, `service.py` | `include_str!` asset reload, toolchain change, extra file/env tests | Complete for the declared-input contract |
| P1-4 lock update lifecycle | Default builds may update copied locks and atomically persist them; `--locked` is explicitly strict | `service.py` | fake-Cargo lock update and strict mode | Complete locally |
| P1-5 prune/build/load races | Global prune lock, nonblocking entry locks, access markers, post-lock revalidation, and process-lifetime load leases | `build/cache.py`, `service.py` | busy-entry, access-order, stale-selection, and multiprocess build/load/prune stress | Complete locally; matrix pending |
| P2-1 native-only Python fallback | Replace executable helper bodies with metadata-preserving sentinels | `rust.py` | every native-only decorator raises when called from Python | Complete locally |
| P2-2 cycle/star approximation | Reject internal import cycles and `import *` with source-spanned diagnostics for alpha | `compiler/frontend.py` | direct/indirect cycle and star-import fixtures | Complete locally |
| P2-3 wheel trust boundary | Enforce runtime ABI and exact alpha runtime version; allow Python/type files by default; require `wheel-include`; refuse common secret patterns | `wheel.py`, `runtime.py`, `config.py`, `_version.py` | manifest mismatch, allowlist, secret refusal, clean install/import | Complete locally; matrix pending |
| Maintainability: effect strings | Introduce `Effect` enum, transitive propagation, GIL consumption, and pre-codegen validation | `compiler/ir.py`, `compiler/frontend.py`, `compiler/validation.py` | inspection/GIL assertions and worker/Python rejection | Complete locally |
| Maintainability: compiler passes | Split the large frontend/codegen modules without semantic change | future refactor | byte-identical or intentionally versioned IR/Rust plus full suite | Deferred until safety release gate is green |

## Typed effect contract

The current effect vocabulary is:

```text
NativeRust
ConversionBoundary
PythonRuntime
Blocking
ThreadSpawn
GlobalMutation
UnsafeMemory
UnsafeFfi
MayPanic
```

Effects are inferred directly, propagated through native calls, validated before
code generation, shown by inspection, and consumed by wrapper policy. The alpha
GIL rule is deliberately conservative: Python runtime, global mutation, unsafe
memory, and unsafe FFI prevent detachment. Primitive native blocking/thread work
may detach when no ownership handle or Python effect is present.

## Compiler invariants

| Invariant | Enforcement point | Failure mode |
|---|---|---|
| Python runtime work cannot enter a Rust worker closure | IR validation before emission | `CRAB206` at the offending call |
| Every direct unsafe/panic operation has its required typed effect | IR validation before emission | internal assertion; compiler defect |
| `python_boundary` agrees with `Effect.PYTHON_RUNTIME` | IR validation before emission | internal assertion; compiler defect |
| Global teaching state is synchronized | generated helper template | no `static mut`; atomic checked update |
| C `abs` precondition is satisfied | generated call site | contained panic for `i32::MIN` |
| Thread-pool `Drop` cannot propagate a worker panic | generated runtime helper | failure retained for explicit `finish()`; Drop joins quietly |
| Exported panic translation uses unwind | Cargo manifest and forced build env | ambient abort override is replaced with `unwind` |
| Loaded extension files are immutable for their process lifetime | complete-fingerprint process registry | no second Cargo publication/load for the same loaded identity |
| Owned wrapper choice is unambiguous | runtime constructor resolution | explicit ambiguity error with `for_=` guidance |

## Cache and Cargo contract

The fingerprint is content-addressed over Crabwalk's declared model:

- all package source and compiler implementation files;
- IR/codegen/fingerprint protocol versions and Python ABI;
- Cargo lock, complete regular-file path-dependency trees, Cargo configuration,
  project-local Rust toolchain selectors, resolved tool executable state, and PyO3;
- recognized compiler/linker/target/profile environment; and
- `[tool.crabwalk].extra-files` and `extra-env` for build-script inputs outside the
  default model.

Cargo is still invoked on external artifact hits for projects with user crates so
its own build-script and incremental dependency rules remain authoritative. A
project that depends on arbitrary undeclared files or environment is outside the
content-addressed contract; declare those inputs rather than relying on accidental
Cargo workspace state. Different Cargo output under an unchanged fingerprint is a
`CRAB306` error rather than an in-place mutation; mapped corrupt entries are held
for later recovery with `CRAB307`.

Lock semantics follow Cargo conventions:

- normal build: start from the committed lock, permit Cargo maintenance, persist
  an updated lock atomically, then recompute the artifact identity;
- `--locked`: require a lock and fail if Cargo would modify it;
- `--offline`: separately select Cargo's offline policy and fingerprint it.

## Wheel contract

The alpha wheel builder includes `.py`, `.pyi`, and `py.typed` by default. Other
package data must match `[tool.crabwalk].wheel-include`. Symlinks and common secret,
credential, and private-key names are rejected. The embedded manifest binds:

```text
manifest schema
Crabwalk version
runtime ABI version
module and source identity
artifact filename, extension init name, and SHA-256
```

The installed runtime checks these fields before native loading and never falls
back to Cargo from an installed mixed wheel.

## Execution phases

### H1 — Reachable UB and abort closure

- [x] Atomic counter and overflow behavior.
- [x] Guarded C `abs` edge.
- [x] Non-panicking pool `Drop` and explicit worker-failure collection.
- [x] Pinned/forced unwind strategy.
- [x] Subprocess safety regression suite.

### H2 — Identity and lifecycle

- [x] Remove ambient latest-owned wrapper state.
- [x] Add explicit conversion context.
- [x] Replace weak runtime memo with complete-fingerprint loaded identity.
- [x] Share loaded identity across `CompilationService` instances.
- [x] Add source-content-keyed analysis reuse and project/toolchain-state-keyed
  version reuse without weakening invalidation.

### H3 — Cargo/cache correctness

- [x] Complete path-tree and declared external input hashing.
- [x] Project-relative toolchain resolution and update-aware caching.
- [x] Conventional lock maintenance.
- [x] Cache last-access marker and prune coordination.
- [x] Revalidate prune candidates after acquiring their entry lock.
- [x] Retain cross-process reader leases for the mapped extension lifetime.
- [x] Preserve mtimes for unchanged generated inputs and avoid republishing
  byte-identical Cargo output.
- [x] Run local repeated prune-versus-build and prune-versus-load process stress.
- [ ] Run repeated prune-versus-build and prune-versus-load process stress on all
  three CI operating systems.

### H4 — Semantic and distribution boundary

- [x] Native-only sentinels.
- [x] Cycle and star-import rejection policy.
- [x] Typed effects and IR validation.
- [x] Wheel runtime ABI and explicit package-data policy.
- [x] Re-run the isolated two-wheel build/install/import test after manifest schema
  2 and the allowlist changes, without Rust/Cargo on the consumer path.

### H5 — Release evidence

- [x] Ruff formatting/lint gate.
- [x] Initial mypy gate over the hardening/build boundary; frontend/codegen/runtime
  typing debt remains explicit.
- [x] Rustfmt parse/stability and Clippy correctness check for a generated project.
- [x] Full local suite on the final worktree: 101 tests in 687.20 seconds on
  Windows/CPython 3.11.
- [x] Final focused unit pass: 67 tests in 3.80 seconds; Chapter 11 teaching pass:
  5 tests in 2.11 seconds.
- [ ] Windows/Linux/macOS × CPython 3.11/3.14 native matrix.
- [ ] CPython 3.12/3.13 unit lanes.
- [ ] Miri or sanitizer harness for the focused unsafe helper crate.
- [x] Record one post-hardening performance smoke sample; keep budgets disabled.
- [ ] Repeated performance samples and budgets.
- [ ] License, governance, support, and release-channel decision.
- [ ] Build, hash, inventory, install, and archive actual release artifacts.

## Verification commands

```powershell
python -m ruff format --check src tests examples
python -m ruff check src tests examples
python -m mypy
python -m compileall -q src tests examples
python -m pytest tests/unit -q
python -m pytest tests/integration/test_native_safety_boundaries.py -q
python -m pytest tests/integration/test_native_ownership.py -q
python -m pytest tests/integration/test_cache_hardening.py -q
python -m pytest tests/integration/test_native_wheel.py -q
python -m pytest tests/integration/test_native_rust_book.py -q
python -m pytest -q
```

Generated Rust quality probe:

```powershell
$generated = crabwalk expand examples/the_rust_book/__init__.py
$manifest = Join-Path (Split-Path (Split-Path $generated -Parent) -Parent) 'Cargo.toml'
cargo fmt --manifest-path $manifest
cargo fmt --manifest-path $manifest -- --check
cargo clippy --quiet --manifest-path $manifest --release -- -A warnings -D clippy::correctness
```

## Exit gate

Hardening is complete only when:

1. Every P0 and P1 row is closed with interaction evidence.
2. The final full local suite is green from a clean generated/cache state and again
   with verified cache hits.
3. The clean wheel consumer proves no Rust/Cargo discovery or source-tree fallback.
4. The advertised CI matrix is green for the exact candidate commit.
5. The remaining release blockers have owners and are either resolved or explicitly
   removed from the advertised alpha claim.

## Source material for the safety decisions

- [Rust Reference: behavior considered undefined](https://doc.rust-lang.org/stable/reference/behavior-considered-undefined.html)
- [Rust `Drop` documentation](https://doc.rust-lang.org/stable/core/ops/trait.Drop.html)
- [Rust `catch_unwind` documentation](https://doc.rust-lang.org/std/panic/fn.catch_unwind.html)
- [C `abs` contract and representability edge](https://en.cppreference.com/w/c/numeric/math/abs)
