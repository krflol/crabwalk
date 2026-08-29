# Changelog

All notable Crabwalk changes are recorded here.

## [Unreleased]

### Added

- `crabwalk.compile_source()` now compiles content-addressed source text and binds
  exported native functions directly from static IR without importing or executing
  the authored Python module. It exposes structured inspection, phase progress, and
  cooperative cancellation for embedding hosts.

### Changed

- Post-release development builds identify themselves as `1.0.9.dev0`, keeping
  `main` distinct from the immutable 1.0.8 artifacts.
- The Rust Book package now exercises the compositional language surface through
  inherent methods, owned domain factories, Option/Result patterns and adapters,
  String/HashMap pipelines, structured `Vec<Shoe>` ownership, and typed sequential
  and Rayon non-`Copy` iterator chains. A runnable structured ETL showcase adds a
  one-crossing `Vec<domain>`-to-`HashMap` example.

### Fixed

- `rust.Str` runtime inspection now reports the generated call-scoped `&str`
  borrow instead of incorrectly claiming a cloned native container and element copy.

## [1.0.8] - 2026-08-27

### Changed

- Fingerprint documentation now makes the conservative whole-`pyproject.toml`
  configuration hash explicit, including invalidation from Python-only metadata
  and comment changes.

## [1.0.7] - 2026-08-26

### Changed

- `crabwalk wheel` now accepts `--project`, honors the selected configuration and
  package containment policy, and can resolve a single configured package from the
  project directory just like neighboring build and inspection commands.
- `Vec[T]` now exposes consuming `into_iter()` and mutable `reserve()`, while
  `HashMap[String, V]` lookup operations accept borrowed `Str` keys and emit
  allocation-free `Borrow<str>` lookups.

### Fixed

- Leading function docstrings remain Python wrapper metadata without becoming
  executable `String::from(...)` statements in generated native Rust bodies.

## [1.0.6] - 2026-08-26

### Changed

- Inspection schema 3 reports recursive, cardinality-aware return conversion costs
  for strings and Python containers instead of labelling composite vector/map
  returns as constant-cost scalars.
- One package initialization now shares a single implicit-build progress lifecycle
  and loaded compilation across all of its runtime decorators; reloads still
  recompute the complete build fingerprint.
- Typed crate-adapter guidance now covers contract-specific numeric formatting,
  including the distinction between Rust display text and JavaScript-compatible
  floating-point rendering.

### Fixed

- Valid zero-length `rust.Buffer[T]` inputs no longer fail PyO3 pointer-alignment
  validation. Generated wrappers validate the untyped buffer contract first and
  use Rust's canonical empty slice when no elements exist, while preserving
  alignment checks for every non-empty numeric buffer.
- Independently generated modules now receive distinct Cargo package identities,
  preventing shared-target unit collisions and spurious `CRAB306` byte-change
  failures observed on Windows when modules were loaded in opposite orders.
- Feature branches now run the pull-request matrix once instead of launching an
  identical branch-push matrix whose duplicate check could block a green PR; direct
  `main` pushes and reusable release calls remain covered.

## [1.0.5] - 2026-08-25

### Added

- `rust.Buffer[T]` provides a bounded, read-only, one-dimensional,
  C-contiguous, native-endian numeric input boundary for `memoryview`, `array`,
  and compatible NumPy storage. Generated wrappers retain a PyO3 buffer lease and
  read through alias-aware cells without constructing a Rust `Vec` or copying
  elements; inspection and runtime metadata expose the borrow/copy policy.

### Changed

- Scalar `Vec[T]` outputs reuse the fresh, typed Python list produced by PyO3
  instead of rebuilding the boundary codec and allocating another list once per
  element. This removes the prior Python-side output-normalization bottleneck
  from bulk numeric kernels.
### Fixed

- Verified cache entries remain authoritative when Cargo reports its target
  artifact as fresh, avoiding false `CRAB306` failures from byte-different shared
  Windows target copies while retaining the invariant for actual rebuilds.

## [1.0.4] - 2026-08-24

### Changed

- Prebuilt-wheel manifest schema 4 records effective Cargo policy and the complete
  dependency-lock identity for installed-runtime provenance.

### Fixed

- Python-visible structs now construct Python tuples dynamically, removing PyO3's
  nominal Rust tuple-arity limit and retaining struct/field source mappings.
- Installed prebuilt functions preserve locked/offline Cargo policy with
  `origin: "prebuilt"` and expose the dependency-lock hash instead of reporting
  incomplete provenance.

## [1.0.3] - 2026-08-24

### Added

- Projects can set `source-locked = true` for decorator-driven source imports;
  inspection and function metadata expose the effective Cargo policy.

### Changed

- The GitHub release attachment job supplies explicit repository context to `gh`,
  allowing it to create or update a release without a source checkout.

### Fixed

- Unsupported floor division now reports the source expression rather than the
  module origin and explains the supported Rust typed `/` division semantics.

## [1.0.2] - 2026-08-24

### Added

- Sequential and Rayon iterators now share a semantic execution/item-mode model
  with `map`, `filter`, `filter_map`, `copied`, `cloned`, `collect_vec`,
  `collect_map`, `sum`, `count`, `any`, `all`, `find`, `fold`, `reduce`,
  `enumerate`, and `zip`. Borrowed `String` and domain items auto-dereference for
  their supported method and field surface.
- Explicit `rust.extern_type` and `@rust.extern` adapters describe external crate
  values, functions, borrow signatures, closure callbacks, and reviewed effects.
  Untyped crate values may no longer escape an expected terminal expression.
- Explicit ownership boundaries accept recursively structured vectors, including
  tuples, options, nested vectors, and generated domain rows. Native functions can
  return owned domain values, and direct nested struct/enum values have
  fingerprint-bound constructors, getters, setters, and deep conversion.
- The typed standard-library subset now includes iterable `HashMap`, common
  `Option`/`Result` patterns and combinators, and the string trim/split/parse/join
  operations needed by a complete delimited transformation.
- A generated capability-maturity registry distinguishes proof, bounded,
  compositional, and production contracts. A cross-product iterator matrix,
  structured filter-group-emit workload, and runnable Rayon String ETL showcase
  provide application-level evidence.
- Compiler responsibilities now have independently typed source, declaration,
  signature, expression/statement/pattern lowering, ABI, ownership, effect,
  semantic type, binding, Rust-emission, capability, and Cargo-emission modules,
  with pass-boundary tests and documented extension invariants.
- Capability maturity now references executable contract IDs attached to native
  and diagnostic tests. Compositional claims require a larger evidence set than
  bounded or proof-level demonstrations.

### Changed

- Development builds identified themselves as `1.0.2.dev0`, keeping the release
  candidate distinct from the immutable 1.0.1 artifacts.
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
- Native package compilation now hashes only declaration roots, requested entry
  modules, required initializers, and reachable internal imports. A separate
  wheel-source integrity hash still covers every shipped `.py` and `.pyi` file.
- Rayon `Vec.par_iter()` now carries a typed borrowed-item state. `Vec<String>`
  pipelines can filter borrowed rows, map them into owned strings, and collect a
  native `Vec<String>` without consuming the input handle.
- Source and emitted identities are separated through `SymbolId`, `BindingId`, and
  per-scope gensym allocation. Semantic types are tagged variants for primitives,
  domains, external crate values, generics, lifetimes, ownership, containers, and
  iterator execution/item modes rather than one overloaded string record.
- Domain fields, enum payload fields/variants, and trait members now carry their
  own Rust member identities. Python-visible names remain stable through explicit
  PyO3 names, including Rust 2024-reserved source spellings such as `gen`.
- IR schema 22 and codegen schema 36 invalidate older development artifacts for
  structured patterns, inferred anonymous locals, Rayon indexing, and the updated
  generated-Rust contract.

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
- Semantically typed iterator stacks and native futures assigned to unannotated
  locals now rely on Rust inference instead of emitting invalid nominal
  `Iterator<Item = T>` or `Future<T>` annotations.
- Sequential `for` targets retain shared/mutable iterator item modes, including
  tuple projection, so borrowed collection values cannot be mistaken for owned
  values by the frontend.
- Rayon iterator types now track indexed versus unindexed capability. Parallel
  `enumerate`/`zip` validate that capability, and search uses explicit
  `find_any`/`find_first`/`find_last` semantics.
- Match patterns are structured semantic IR. Capture hygiene no longer performs
  regex substitution over Rust source, eliminating field and literal corruption.
- Exported `HashMap` signatures now reject key types whose documented Python
  representation is unhashable while accepting recursively hashable tuple,
  option, scalar, string, and byte-vector keys.
- Generated move, panic, and Rust-result failures now use private native exception
  identities with structured payloads. Public translation no longer trusts error
  message prefixes, and borrow conflicts retain structured parameter/source data.
- Numeric `HashMap.add` now emits the additive identity with its concrete value
  type; floating-point maps no longer receive an invalid integer `or_insert(0)`.
- Python ABI validation now composes a boundary-shape descriptor rather than
  independent child booleans. Nested `Result`, nested `Option`, `Option[Unit]`,
  and non-injective `HashMap` keys fail before Rust emission instead of compiling
  badly or collapsing distinct Rust values in Python.
- Anonymous iterator, future, and closure locals carry an explicit opaque-storage
  identity. Ordinary reassignment fails as `CRAB226`; unannotated
  `rust.shadow(...)` creates a fresh inferred binding.
- Native local consumption is tracked across iterator loops, owned calls,
  consuming methods, futures, and control-flow joins. Use after move now reports
  source-spanned `CRAB227` while recursively `Copy` values remain reusable.
- `rust.Range` accepts only matching integer or char literal endpoints and rejects
  wildcard, bool, enum, and compound endpoints as `CRAB192` before code generation.
- Capability maturity is enforced from actual pytest collection and outcomes.
  Native CI publishes per-platform JSON evidence, and skipped/xfail-only tests no
  longer satisfy a public contract.

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
