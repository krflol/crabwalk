---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-23
tags:
  - project/crabwalk
  - docs/security
---

# Crabwalk Security and Limitations

## Trust boundary

Crabwalk's Python frontend is static: analyzing a package does not import it,
execute `__init__.py`, evaluate annotations, or call runtime crate objects.
Compilation is different. Cargo dependencies, build scripts, procedural macros,
rustc wrappers, linkers, and configured external tools can execute code with the
developer's permissions. Crabwalk does not sandbox them.

Treat building an untrusted Crabwalk project exactly like building an untrusted
Rust project:

- review `rust.crate` declarations, lock changes, path dependencies, Git revisions,
  build scripts, and proc macros;
- prefer `--locked`; use `--offline` only after the required registry/git content is
  prepared and trusted;
- isolate CI builds with least-privilege credentials and filesystem/network policy;
- do not expose broad Cargo credentials to projects that do not need them;
- inspect generated `Cargo.toml`, `Cargo.lock`, and the exact command with
  `crabwalk inspect`/`expand`.

External diagnostics are stripped of terminal control sequences, bounded in
length, and redact URL credentials, common secret query parameters, and values of
secret-like environment variables. This reduces accidental disclosure; it is not
a proof that arbitrary third-party build output contains no sensitive derived data.

## Native safety boundary

Generated user code uses safe Rust by default. The Rust Book teaching surface adds
several explicit, reviewed unsafe operations: raw reads/writes of named Copy locals,
a bounds-checked split-slice demonstration, guarded C `abs`, and an atomic global
counter example. The C call rejects `i32::MIN` before FFI because its positive
magnitude is not representable; the counter uses a checked `AtomicU64` update.
Their generated `unsafe` blocks are inspectable and deliberately do not form a
general raw-Rust or arbitrary-FFI escape hatch. PyO3 wrappers:

- range/type check exported values in Python before native entry;
- contain Rust panics with `catch_unwind` and raise `CrabwalkPanicError`; generated
  release profiles and Cargo invocation force `panic = "unwind"`;
- translate exported `Result::Err` into `CrabwalkRustError`;
- enforce Rust-backed move and borrow state before taking native references;
- derive GIL policy from both ABI-safe primitive signatures and typed effects;
- keep/reacquire the GIL for Python runtime, global mutation, unsafe-memory, and
  unsafe-FFI effects;
- keep the GIL and the exporter lease alive for every `BorrowedBuffer` call.

`rust.Buffer[T]` never turns Python-owned storage into `&[T]`. The generated
wrapper retains PyO3's `PyBuffer<T>` lease and exposes its
`ReadOnlyCell<T>` elements through copied reads, preserving the fact that external
aliases may exist. Runtime and generated preflights require a read-only,
one-dimensional, C-contiguous, native-endian numeric exporter before any owned
argument is moved. Buffer views cannot escape the call or enter spawned/Rayon
closures.

Typed effects propagate across ordinary calls, methods, traits, operators, and
function-pointer targets. Pre-codegen placement validation rejects Python runtime
work in workers and generated contexts whose current Rust signature cannot carry a
`PyResult`, including methods, operators, native async helpers, and iterator
closures. Receiver capability is also semantic: shared references cannot satisfy
mutable or consuming methods, while the root ownership of nested field/index
places is retained. These checks produce source-spanned diagnostics before rustc.

Generated Rust names are component-injective and checked across value, type,
method-glue, Cargo-dependency, and crate-binding namespaces. Mandatory PyO3 and the
narrow C `abs` declaration use isolated internal identities, preventing user names
such as `abs`, `String`, or `pyo3` from changing compiler/runtime resolution.
Parameters, locals, closure/pattern bindings, fields, and variants reject Rust
2024 strict/reserved keywords and compiler-reserved `__cw_*` names before code
generation. Generated pyclass, Python owned-handle, and enum-marker member
collisions are rejected at their source declarations. Contextual weak keywords are
allowed only in the emitted contexts where Edition 2024 accepts them. Rust strings
and chars accept Unicode scalar text only; escaped lone surrogates fail at both
literal lowering and Python runtime boundaries.

The generated ThreadPool catches each worker job, records the first failure, and
reports it through explicit `finish()`. Its `Drop` path closes and joins without
propagating a join panic, including while an outer native function is unwinding.

Safe generated Rust does not eliminate ABI, compiler, dependency, or handwritten
runtime bugs. The native test matrix remains a release requirement.

## Installed artifacts

Development artifacts are content addressed over Crabwalk's declared input model,
manifest bound, hash verified, locked, and atomically published. Every compilation
unit persists and fingerprints the complete generated dependency lock, including
mandatory PyO3 even when no user crate is declared. Native loading is
performed under the fingerprint lock and retains a per-process reader lease for
the mapped lifetime; pruning uses a separate global lock, nonblocking entry locks,
access markers refreshed after publication/validation/load, and post-lock
revalidation. Prebuilt wheel
artifacts additionally bind the Python source, package identity, exact Crabwalk
runtime, and runtime ABI. Artifact paths are resolved inside the installed package
before loading. Wheel construction rejects package symlinks and common credential
or private-key names.

Arbitrary build scripts can consume inputs Cargo and Crabwalk cannot infer. Declare
those with `[tool.crabwalk].extra-files` and `extra-env`. Cargo is re-invoked for
every cache hit, but undeclared external inputs remain outside the
content-addressed fingerprint contract.

Declared-crate calls carry `OpaqueCrateCall`. Crabwalk cannot infer whether an
arbitrary dependency blocks, spawns threads, mutates global state, calls FFI, or
reacquires Python through PyO3. The visible effect list and `python-boundaries`
policy describe Crabwalk-lowered operations, not unaudited dependency internals.
Opaque calls also carry `MayPanic` and are not automatically detached from the GIL;
this remains conservative until a typed adapter can declare a dependency boundary's
actual effects.

SHA-256 detects accidental/stale corruption and local mismatch; by itself it does
not establish who produced a malicious wheel. Version-tag releases build once,
verify the checksum inventory after every artifact transfer, publish through PyPI
Trusted Publishing, and attach a GitHub/Sigstore SLSA provenance attestation to the
wheel and source distribution. Consumers should still apply their normal Python
index, dependency, and provenance policies.

## Current limitations

- CPython only; interpreter-specific wheels; free-threaded CPython is not advertised.
- Regular packages only; namespace packages and multiple configured top-level
  packages in one distribution are not supported.
- Internal package import cycles and `import *` are rejected in the reachable
  native compiler graph rather than approximated. Use explicit imports and an
  acyclic compiler-visible graph; unrelated Python-only modules remain outside it.
- No general Python calls, objects, reflection, exceptions-as-control-flow,
  generators, or dynamic imports inside `@rust.fn`. Closures are accepted only in
  statically typed iterator/thread/async/pool positions.
- No defaults, keyword calls, variadics, arbitrary crate reflection, inline Rust,
  arbitrary macros, raw address dereference, unions, user-authored unsafe traits, or
  general FFI declarations. Methods, generics, object-safe traits, focused Add/UFCS,
  and narrow unsafe intrinsics are supported as documented.
- No implicit complex/container graph conversion.
- `rust.Buffer[T]` is input-only and limited to read-only, one-dimensional,
  C-contiguous, native-endian primitive numeric storage. It retains the GIL and
  cannot be nested, retained, mutated, returned, or used directly with Rayon.
- Owned/borrowed values cannot be returned or transferred through `async_call`.
- Direct nested domain fields and enum payloads have fingerprint-bound Python
  constructors/getters and explicit deep-copy conversion. Container-wrapped nested
  domain fields are not yet part of that codec.
- Native `@rust.async_fn` uses a small std-only teaching executor, not Tokio.
  `rust.async_call` remains a separate Python executor bridge; cancellation does not
  stop Rust work already running.
- Rayon is exposed through typed `Vec.par_iter()` adapters when the package
  explicitly declares Rayon. Copy and borrowed non-`Copy` items compose through
  the documented adapters, including filter/map/collect and reduction. Broader
  `Send`/`Sync` Python-wrapper transfer and arbitrary Rayon API reflection are not
  exposed.
- `TcpListener`, `TcpStream`, and `ThreadPool` provide a bounded loopback teaching
  slice, not a production server, TLS stack, general HTTP parser, or persistent
  externally controlled background service.
- The wheel command is a focused mixed-wheel builder, not a general metadata-aware
  PEP 517 backend. It packages Python/type files by default; other package data
  requires an explicit `wheel-include` pattern.
- Cross-platform CI must pass before a release is promoted; local evidence alone is
  not a portability claim.

Rejected behavior is intentional. A source form is not supported merely because
rustc could theoretically compile a related Rust expression.
