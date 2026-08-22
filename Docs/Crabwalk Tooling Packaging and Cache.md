---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-21
tags:
  - project/crabwalk
  - docs/tooling
---

# Crabwalk Tooling, Packaging, and Cache

## One compilation service

Decorators and every CLI build/inspection command use `CompilationService`.
Static analysis never imports or executes the target package. It reads the AST,
resolves the supported package graph, emits immutable IR, generates deterministic
Rust/Cargo/source-map files, and optionally invokes Cargo.

| Command | Result |
|---|---|
| `doctor` | interpreter/ABI/header/rustc/Cargo/linker readiness probe |
| `expand PATH` | deterministic generated project, no Cargo compilation |
| `check PATH` | `cargo check --release` with mapped diagnostics |
| `build PATH` | verified content-addressed native artifact |
| `inspect PATH [--json]` | IR effects, conversions, calls, GIL, cache, dependencies, fingerprint inputs |
| `show PATH SYMBOL` | annotated native function and Python ABI wrapper |
| `wheel PACKAGE` | interpreter/platform wheel containing sources and native artifact |
| `cache status PATH` | hit/miss/corruption status and expected artifact |
| `cache prune` | scoped age/size cleanup with dry-run support |

`--locked` requires persisted dependency lock state. `--offline` passes Cargo's
offline policy and is fingerprinted. An initial unlocked dependency build writes a
lock beneath `crabwalk-locks/`; subsequent builds copy it into the generated crate.

## Fingerprints

The cache key includes:

- package source hash and module identity;
- Crabwalk implementation, IR, codegen, and fingerprint schema versions;
- CPython implementation/version/extension ABI;
- rustc, Cargo, and PyO3 versions;
- Cargo lock content, path-dependency content and resolved identity;
- release profile and overflow policy;
- Cargo configuration content;
- hashed build-affecting environment variables, including target, flags, wrappers,
  linker/compiler choices, SDK deployment settings, and `PATH`.

Raw environment values are not written to inspect metadata. Cache manifests bind
the fingerprint, extension initialization name, exact filename, and SHA-256 of the
artifact. A malformed, mismatched, missing, or corrupt entry is rebuilt under an
interprocess lock. Artifact publication and metadata writes are atomic.

## Cache cleanup

```powershell
crabwalk cache prune . --dry-run
crabwalk cache prune . --max-bytes 1073741824 --max-age-days 14
```

Cleanup only considers direct child directories whose names are 64 lowercase hex
characters beneath `.crabwalk/cache/artifacts`. Unknown entries and paths that
resolve outside that directory are untouched. Defaults retain at most 2 GiB and
30 days. A dry run lists the exact entries and reclaimed byte count.

## Building a user wheel

```powershell
crabwalk wheel src\my_package `
  --name my-distribution `
  --version 1.0.0 `
  --output-dir dist
```

The current command targets a regular top-level package and the running CPython
ABI/platform. It:

1. statically analyzes and compiles the complete package;
2. copies ordinary package files while excluding `.crabwalk`, bytecode, Git data,
   previous embedded artifacts, and symlinks;
3. embeds the extension beneath `_crabwalk_native/`;
4. embeds `_crabwalk_prebuilt.json` with source and artifact hashes;
5. writes deterministic wheel metadata and a hashed `RECORD`;
6. declares the matching Crabwalk runtime version as a dependency.

On import, the installed runtime re-analyzes source without executing it, verifies
the manifest/source hash, contains the artifact path within the package, verifies
the binary hash, and loads the matching extension name. Any mismatch raises
`CRAB405`; it never silently invokes Cargo from an installed wheel.

Wheels are interpreter-specific (`cpXY-cpXY-platform`), not `abi3`. Build one per
supported CPython/platform combination. This is an alpha wheel command rather than
a general PEP 517 backend: distribution metadata/dependency merging beyond the
required Crabwalk runtime is still the packager's responsibility.
