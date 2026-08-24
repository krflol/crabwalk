# Changelog

All notable Crabwalk changes are recorded here.

## [Unreleased]

### Changed

- Post-release development builds now identify themselves as `1.0.2.dev0`,
  keeping `main` distinct from the immutable 1.0.1 artifacts.
- The typed quality boundary now includes the shared Python-wrapper namespace
  contract used by both frontend validation and runtime regression tests.
- Opaque external crate calls now also carry `MayPanic` and conservatively keep
  the GIL attached until a future typed adapter declares their actual effects.
- Version tags now run an immutable release workflow that reuses the complete CI
  gate, builds distributions once, smoke-installs the exact files, publishes via
  PyPI Trusted Publishing, and attaches artifacts plus hashes to GitHub.
- Python/native conversion is now described by one typed boundary codec shared by
  exported functions, owned construction, domain constructors and fields, enum
  payloads, and `to_python`. `Vec[u8]` deliberately converts to Python `bytes`;
  other supported vectors convert to new lists.
- Direct expression effects now have an exhaustive compiler rule table. Indexing,
  signed negation, and integer `HashMap.add` correctly carry `MayPanic`.
- CI and release actions use reviewed full commit SHAs, the Rust 1.97.0 toolchain,
  pinned Python build tooling, verified release inventories, and GitHub provenance
  attestations.

### Fixed

- Source binding validation now follows the complete Rust 2024 strict and
  reserved keyword sets, including `_` and `gen`, while allowing contextual weak
  keywords such as `union` in Crabwalk's supported emitted positions.
- Struct fields, enum payload fields, and enum variants can no longer shadow the
  Python owned-value wrapper or `RustType` enum-marker APIs; collisions fail as
  source-spanned `CRAB210` diagnostics.
- Trait implementations with parameters after the shared receiver now fail as
  `CRAB211` before code generation, matching the current no-argument trait shape.
- Cache pruning carries uncertainty through post-inventory changes, lock races,
  and failed deletion, so its byte remainder and limit status are never presented
  as exact from a stale snapshot.
- Exported functions that both reach Python and return `rust.Result[T, E]` now
  unwrap the nested `PyResult` outside the panic-catching closure, preserving the
  intended `CrabwalkRustError` and `CrabwalkPanicError` boundaries.
- Direct value bindings can no longer collide with the Rust prelude constructors
  `Some`, `Ok`, or `Err`; compiler-owned uses are fully qualified and generated
  value/type prefixes are consistent.
- Generic type and lifetime parameters can no longer shadow Crabwalk built-in or
  generated runtime types. A rustc-backed oracle covers every supported weak
  keyword across Crabwalk's emitted identifier positions.
- Ownership wrappers preflight every argument before extracting any `Owned` value,
  so a moved later argument cannot partially consume earlier valid handles.
- Struct constructors, field setters, and enum payload constructors now apply the
  same exact primitive policy as exported functions, including rejecting `bool`
  for Rust integer fields.
- Struct and enum markers retain their compilation fingerprint and resolve their
  native class and schema through that identity, so stale markers remain stable
  across hot reloads.
- Cargo dependency-lock replanning is iterative and bounded; a graph that changes
  during three consecutive plans now fails as `CRAB308` instead of recursing.

## [1.0.1] - 2026-08-23

### Fixed

- Generated application wheels now require the published `crabwalk-lang`
  distribution instead of the nonexistent pre-rename `crabwalk` project.
- Mixed-wheel smoke installation resolves the runtime dependency through pip
  without `--no-deps` or an explicitly supplied runtime wheel path.
- Parameters, locals, loop/pattern/closure bindings, fields, and enum variants now
  reject Rust keywords and compiler-reserved names before rustc; generated pyclass
  member collisions receive source-spanned diagnostics.
- Exported source parameters named `py` no longer collide with the wrapper's
  compiler-owned Python token.
- Trait implementations are checked for unknown, duplicate, missing, and
  return-type-incompatible methods before Rust emission.
- Escaped lone surrogates are rejected as invalid Rust string/char values during
  lowering and at Python runtime boundaries.
- Cache pruning no longer reports an exact byte remainder or satisfied ceiling
  when busy entries could not be inventoried, and stale lease cleanup no longer
  trusts reusable process IDs over the lease lock.

### Changed

- Declared external crate calls now carry `OpaqueCrateCall`, making the limit of
  Crabwalk's effect inference explicit and transitively inspectable.
- Project metadata reads the package version from `crabwalk._version`, keeping
  source, wheel dependency, manifest, CLI, and distribution identity aligned.
- Removed stale links to deleted planning files and refreshed public documentation
  for schema v18 and the 1.x release line.

### Migration notes

Application wheels generated by Crabwalk 1.0.0 contain an incorrect
`Requires-Dist: crabwalk==1.0.0` entry and should be rebuilt with 1.0.1. As a
temporary workaround, install `crabwalk-lang==1.0.0` explicitly and install the
old application wheel with `--no-deps`.

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
