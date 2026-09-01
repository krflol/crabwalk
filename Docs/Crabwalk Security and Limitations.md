---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-30
tags:
  - project/crabwalk
  - docs/security
---

# Crabwalk Security and Limitations

## Trust boundary

Crabwalk's Python frontend is static: analyzing a package does not import it,
execute `__init__.py`, evaluate annotations, or call runtime crate objects.
`crabwalk.compile_source()` extends that property through callable binding: it
materializes a content-addressed source snapshot, builds the native extension, and
constructs exported `RustFunction` wrappers directly from semantic IR without
importing or executing the authored Python module. The snapshot is required for
durable source spans and Cargo diagnostics.

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

Containment does not replace Rust's process-wide panic hook. A caught panic may
therefore still write its panic message to stderr before Crabwalk raises
`CrabwalkPanicError`. Expected validation, budget exhaustion, cancellation, and
other routine control outcomes should use typed `Result` values; Crabwalk does not
silence or globally replace an embedding application's panic hook.

An explicit `@rust.fn(release_gil=True)` can override conservative non-Python
effects for an audited long-running call. Validation still rejects reachable Python
runtime work and call-scoped `Buffer`, `Str`, `Ref`, or `Mut` inputs. Owned/shared
native values are extracted and their Python guards are dropped before detachment;
the adapter author is responsible for the declared external code's thread safety
and no-Python guarantee.

`rust.Buffer[T]` never turns Python-owned storage into `&[T]`. The generated
wrapper retains PyO3's `PyBuffer<T>` lease and exposes its
`ReadOnlyCell<T>` elements through copied reads, preserving the fact that external
aliases may exist. Runtime and generated preflights require a read-only,
one-dimensional, C-contiguous, native-endian numeric exporter before any owned
argument is moved. Buffer views cannot escape the call or enter spawned/Rayon
closures. A typed external adapter expecting `&[T]` receives a temporary copied
`Vec<T>` rather than an unsafe immutable view of aliasable exporter memory.

Typed effects propagate across ordinary calls, methods, traits, operators, and
function-pointer targets. Pre-codegen placement validation rejects Python runtime
work in workers and generated contexts whose current Rust signature cannot carry a
`PyResult`, including trait/operator methods, native async helpers, and iterator
closures. Inherent method glue is result-aware and supports synchronous Python
adapters. Receiver capability is also semantic: shared references cannot satisfy
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
runtime bugs. The native test matrix remains a release requirement. The release
workflow also runs the atomic counter, guarded C precondition, and non-panicking
thread-join contract through a pinned nightly Miri fixture.

## Installed artifacts

Development artifacts are content addressed over Crabwalk's declared input model,
manifest bound, hash verified, locked, and atomically published. Every compilation
unit persists and fingerprints the complete generated dependency lock, including
mandatory PyO3 even when no user crate is declared. Native loading is
performed under the fingerprint lock and retains a per-process reader lease for
the mapped lifetime; pruning uses a separate global lock, nonblocking entry locks,
access markers refreshed after publication/validation/load, and post-lock
revalidation. Prebuilt wheel
artifacts additionally bind the Python source, package identity, compiler
provenance, runtime ABI, generated-wrapper ABI, compatibility range, and manifest
schema. Compatible patch runtimes may load an older generator artifact only when
those protocol identities still match. Artifact paths are resolved inside the
installed package before loading. Wheel construction rejects package symlinks and
common credential or private-key names.

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
- Standalone filesystem auto-discovery begins from a regular package or module.
  Namespace packages and multiple top-level packages require explicit
  `[tool.crabwalk].packages`; the PEP 517 backend emits one native artifact per
  configured top-level package.
- Reachable declaration cycles are resolved to a fixed point. `import *` requires
  either literal static `__all__` or the compiler-visible leading-underscore rule;
  dynamic `__all__` and import-time mutation remain unsupported.
- No arbitrary Python objects, reflection, generators, dynamic imports, or
  exceptions-as-control-flow inside `@rust.fn`. Synchronous Python calls require a
  typed `@rust.python_adapter`; explicit `module=`/`name=` routing is supported.
  An adapter may name one native `on_error` observer that runs immediately before
  the original `PyErr` propagates. The observer must be synchronous, zero-argument,
  unit-returning, and free of reachable Python or panic effects.
  Python calls remain forbidden in native closures, trait/operator methods,
  workers, and async helpers whose signatures cannot carry `PyResult`.
- `compile_source` accepts one source or a virtual multi-module mapping and can
  terminate an active Cargo process tree, but it does not sandbox trusted build
  execution or preempt already-entered native user code. `source_root` affects only
  relative dependency resolution; `origin_map` metadata is host-supplied and should
  be JSON-compatible when emitted through JSON/LSP tooling.
- Exported calls support positional/keyword arguments and lossless literal
  defaults. Positional-only, keyword-only, variadic, and mutable/dynamic defaults
  remain unsupported. Direct Python ABI tuples are bounded to the 12-element
  conversion implemented by PyO3 0.29; native-only tuples may be larger. There is
  still no arbitrary crate reflection, inline Rust,
  arbitrary macros, raw address dereference, unions, user-authored unsafe traits,
  or general FFI declarations.
- `rust.Buffer[T]` is input-only and limited to read-only, one-dimensional,
  C-contiguous, native-endian primitive numeric storage. It retains the GIL and
  cannot be nested, retained, mutated, returned, or used directly with Rayon.
  Zero-length exporters use a canonical empty Rust slice after format and shape
  validation; pointer alignment remains mandatory for every non-empty buffer.
- Borrowed values cannot be returned or transferred through `async_call`. Explicit
  `Owned[Domain]`, `Owned[Vec[T]]`, `Owned[TextColumn]`, and
  `Owned[ExternalType]` returns produce move-aware handles. External handles are
  opaque and cannot be converted implicitly to Python; recursive mappings/sequences
  cross only through supported, explicitly allocating codecs.
- Ordinary ownership handles are thread-affine. `Shared[T]` is limited to immutable
  compiler-approved `Send + Sync` payloads, uses `Arc<T>`, and exposes no mutable
  operation or retained borrow.
- Native `@rust.async_fn` uses a small std-only teaching executor, not Tokio.
  `rust.async_call` remains a separate Python executor bridge; cancellation does not
  stop Rust work already running.
- Rayon is exposed through typed `Vec.par_iter()` adapters when the package
  explicitly declares Rayon. Copy and borrowed non-`Copy` items compose through
  the documented adapters, including filter/map/collect and reduction. Immutable
  `Shared[T]` is the only cross-thread Python handle; mutable sharing and arbitrary
  Rayon API reflection are not exposed.
- `TcpListener`, `TcpStream`, and `ThreadPool` provide a bounded loopback teaching
  slice, not a production server, TLS stack, general HTTP parser, or persistent
  externally controlled background service.
- The direct wheel command remains a focused single-package builder. The PEP 517
  backend merges static PEP 621 metadata and multiple packages, but does not yet
  implement editable PEP 660 application builds or arbitrary dynamic metadata.
  Non-Python package data still requires an explicit `wheel-include` pattern.
- Cross-platform CI must pass before a release is promoted; local evidence alone is
  not a portability claim.

Rejected behavior is intentional. A source form is not supported merely because
rustc could theoretically compile a related Rust expression.
