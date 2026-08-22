# Changelog

All notable Crabwalk changes will be recorded here. The project has not published
a release yet; the entries below describe the current `0.0.1` alpha candidate.

## [Unreleased]

### Added

- Static package-wide analysis for explicitly decorated Rust functions.
- Source-spanned schema-v16 IR and deterministic Rust, PyO3, Cargo, and source-map
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
  `examples/th_rust_book` with focused unit/native evidence and a coverage plan.

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
