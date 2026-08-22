# Changelog

All notable Crabwalk changes will be recorded here. The project has not published
a release yet; the entries below describe the current `0.0.1` alpha candidate.

## [Unreleased]

### Added

- Static package-wide analysis for explicitly decorated Rust functions.
- Source-spanned schema-v17 IR and deterministic Rust, PyO3, Cargo, and source-map
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
  fallbacks. Package cycles and star imports are rejected for the alpha contract.
- Mixed wheels enforce a runtime ABI version and include only Python/type files by
  default; extra data requires `wheel-include`.

### Security

- Replaced the teaching `static mut` counter with a checked atomic increment.
- Guarded C `abs` against `i32::MIN`, for which C cannot represent the magnitude.
- Made ThreadPool destruction non-panicking, caught worker failures, added explicit
  `finish()`, and forced Cargo's release panic strategy to `unwind`.
- Added isolated subprocess regressions for unsafe boundaries and combined panic
  paths, plus common credential/private-key refusal during wheel construction.

### Migration notes

This is the first candidate and has no prior stable release to migrate from.
Generated artifacts, IR, source maps, cache manifests, and embedded-wheel manifests
are versioned internal protocols and may still change before the first published
alpha. Applications should commit `crabwalk-locks/` but not `.crabwalk/`.

### Release blockers

- Select and publish the project license/governance policy.
- Pass the advertised CPython and OS CI matrix.
- Establish repeated performance budgets.
- Produce, hash, inventory, and smoke-test the actual release artifacts.
