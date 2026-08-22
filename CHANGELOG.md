# Changelog

All notable Crabwalk changes are recorded here.

## [Unreleased]

No changes yet.

## [1.0.0] - 2026-08-22

### Added

- Static package-wide analysis for explicitly decorated Rust functions.
- Source-spanned schema-v18 IR and deterministic Rust, PyO3, Cargo, and source-map
  generation.
- Checked primitive/string/container boundaries, explicit Python-runtime effects,
  panic and `Result` exception mapping, and eligible GIL release.
- Regular-package imports and re-exports plus crates.io, path, feature, and pinned
  Git dependency support with persisted Cargo locks.
- Verified content-addressed build cache, inspection commands, bounded pruning,
  and clean consumer wheels containing a hash-bound native extension.
- `Owned`, `Ref`, and `Mut` handles with move, borrow, thread, GC, reentrancy, and
  reload protections.
- Rust structs, enums, exhaustive match, narrow derives/Serde, Rayon iteration,
  and the explicit Python-executor `rust.async_call` bridge.
- Interactive implicit-build progress with durable non-TTY phase output and
  `CRABWALK_PROGRESS` control.
- Native async helpers and std-only executor composition; inherent methods, trait
  implementations/objects, Add operator implementations, and fully qualified calls.
- General typed patterns with ranges, guards, rest, nested domain payloads, and
  at-bindings; recursively checked tuple ABI inputs.
- Focused auditable unsafe/advanced teaching operations, function pointers, boxed
  closures, native loopback TCP, and a finite channel-backed ThreadPool with Drop.
- A source-linked, one-crate adaptation of all 21 Rust Book chapters under
  `examples/the_rust_book` with focused unit/native evidence and a coverage plan.
- Typed native, conversion, Python runtime, blocking, threading, global mutation,
  unsafe-memory, unsafe-FFI, and panic effects plus pre-codegen IR validation.
- A Python quality gate with Ruff, scoped mypy coverage of the hardening/build
  boundary, generated-project rustfmt parsing, and Clippy correctness lints.
- Dispatch-aware method/trait/operator/function-pointer effects, Python-boundary
  placement validation, and semantic receiver/place ownership diagnostics.
- Component-injective generated symbols, structural owned-wrapper identities, an
  isolated FFI module, and pre-codegen value/type/method/dependency uniqueness.

### Changed

- Owned-value construction now resolves an exact caller/compilation identity,
  raises on ambiguity, and supports `rust.from_python(..., for_=compiled_function)`.
- In-process native reuse is keyed by the complete artifact fingerprint and shared
  across compilation services; source analysis and tool versions use input-aware
  caches that still invalidate on content/toolchain changes.
- Normal Cargo builds can maintain a persisted dependency lock; `--locked` is the
  explicit strict mode. Projects may declare `extra-files` and `extra-env` inputs.
- Cache pruning uses access markers and coordinated prune/build/load locks.
- Native-only decorators return compiler sentinels instead of executable Python
  fallbacks. Package cycles and star imports are rejected by the current contract.
- Mixed wheels enforce a runtime ABI version and include only Python/type files by
  default; extra data requires `wheel-include`.
- Every compilation unit now fingerprints and persists the complete generated
  dependency graph and lock, including mandatory PyO3; Cargo validates every cache
  hit, and lock changes cannot publish beneath a stale fingerprint.
- Repaired cache entries refresh their access age, and package-cycle analysis now
  includes every parent initializer Python executes for a child import.
- Generated PyO3 dependencies enable `extension-module` and use
  `pyo3-build-config` linker setup so macOS leaves Python ABI symbols for the
  interpreter to resolve; wheel smoke builds use isolated backend requirements
  consistently across the advertised Python matrix.
- The bounded HTTP teaching server treats post-response socket shutdown as
  best-effort, avoiding macOS `ENOTCONN` panics after a client half-closes while
  retaining flush-and-drop connection cleanup.
- The generated PyO3 linker build script watches only itself and requests
  reproducible MSVC linking, preserving byte-identical Windows DLLs when Cargo
  relinks while switching generated modules in a shared target directory.

### Security

- Replaced the teaching `static mut` counter with a checked atomic increment.
- Guarded C `abs` against `i32::MIN`, for which C cannot represent the magnitude.
- Made ThreadPool destruction non-panicking, caught worker failures, added explicit
  `finish()`, and forced Cargo's release panic strategy to `unwind`.
- Added isolated subprocess regressions for unsafe boundaries and combined panic
  paths, plus common credential/private-key refusal during wheel construction.

### Migration notes

This is the first public release and has no prior stable release to migrate from.
The PyPI distribution is named `crabwalk-lang`; its import package and CLI remain
`crabwalk`.
Generated artifacts, IR, source maps, cache manifests, and embedded-wheel manifests
are versioned internal protocols and may change between releases. Applications
should commit `crabwalk-locks/` but not `.crabwalk/`.

### Release verification

- Apache-2.0 licensing, maintainer-led governance, and private vulnerability
  reporting are documented in the repository.
- The supported CPython and operating-system matrix is a required release gate.
- Published distributions are checked, hashed, and smoke-installed in clean
  environments before upload.
- Showcase timings remain illustrative local measurements; they are not release
  performance guarantees.
