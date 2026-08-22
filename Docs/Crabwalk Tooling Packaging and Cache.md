---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-22
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

`--locked` requires persisted dependency lock state and rejects any Cargo lock
change. `--offline` passes Cargo's offline policy and is fingerprinted. Every
compilation unit has a persisted generated dependency lock, even when mandatory
PyO3 is its only dependency. A normal build copies that lock into the generated
crate, runs without `--locked`, and atomically persists intentional Cargo updates
beneath `crabwalk-locks/`. A changed lock abandons the old-key staging result and
restarts under a fresh fingerprint before publication or loading.

## Fingerprints

The cache key includes:

- package source hash and module identity;
- Crabwalk implementation, IR, codegen, and fingerprint schema versions;
- CPython implementation/version/extension ABI;
- project-resolved rustc/Cargo executable and toolchain-selector state;
- the complete generated dependency specification, including the mandatory pinned
  PyO3 package and internal alias;
- Cargo lock content and complete regular-file path-dependency trees;
- release profile, overflow policy, and forced unwind panic strategy;
- Cargo configuration content;
- hashed build-affecting environment variables, including target, flags, wrappers,
  linker/compiler choices, SDK deployment settings, and `PATH`;
- declared `[tool.crabwalk].extra-files` trees and `extra-env` values.

Raw environment values are not written to inspect metadata. Cache manifests bind
the fingerprint, extension initialization name, exact filename, and SHA-256 of the
artifact. A malformed, mismatched, missing, or corrupt entry is rebuilt under an
interprocess lock. Artifact publication and metadata writes are atomic.
Generated inputs are not rewritten when their bytes are unchanged, preserving
mtimes so Cargo validation does not trigger a needless relink or mapped-DLL
replacement.

Every external artifact hit still invokes Cargo, allowing its dependency,
build-script, and incremental rules to validate inputs. Crabwalk's
cache identity remains content-addressed over the documented/default inputs plus
explicit `extra-files` and `extra-env`; arbitrary undeclared build-script inputs are
outside that contract. If Cargo produces different native bytes under an unchanged
fingerprint, Crabwalk raises `CRAB306` instead of silently changing a
content-addressed entry. If a corrupt entry needs replacement while another process
has it mapped, `CRAB307` defers recovery until that process exits.

## Cache cleanup

```powershell
crabwalk cache prune . --dry-run
crabwalk cache prune . --max-bytes 1073741824 --max-age-days 14
```

Cleanup only considers direct child directories whose names are 64 lowercase hex
characters beneath `.crabwalk/cache/artifacts`. Unknown entries and paths that
resolve outside that directory are untouched. Defaults retain at most 2 GiB and
30 days. Successful publication, validation, and native loading atomically update
a `.last-access` marker. Entry age is the newer of content modification and the
nanosecond value recorded in that marker, so repairing an old corrupt entry makes
it fresh. Pruning is
serialized globally, tries each fingerprint lock without blocking, checks
process-lifetime native load leases, and revalidates the selected size/access
snapshot after acquiring it. Busy, mapped, or changed entries are left for a later
pass. A dry run lists the exact candidates and reclaimed byte count without
acquiring deletion leases.

## Declaring nonstandard build inputs

```toml
[tool.crabwalk]
packages = ["src/my_package"]
extra-files = ["native/schema.proto", "native/templates"]
extra-env = ["OPENSSL_DIR", "MY_NATIVE_MODE"]
wheel-include = ["templates/**/*.html", "py.typed"]
```

Paths are project-relative, must remain inside the configured project, and must
exist. Environment values participate by SHA-256 only; raw values are not persisted
to build-input inspection metadata.

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
2. copies `.py`, `.pyi`, and `py.typed` plus explicitly configured `wheel-include`
   package data, while rejecting symlinks and common secret/private-key names;
3. embeds the extension beneath `_crabwalk_native/`;
4. embeds `_crabwalk_prebuilt.json` with source/artifact hashes, exact alpha
   Crabwalk version, and runtime ABI version;
5. writes deterministic wheel metadata and a hashed `RECORD`;
6. declares the matching Crabwalk runtime version as a dependency.

On import, the installed runtime re-analyzes source without executing it, verifies
the manifest schema/runtime ABI/exact alpha version/source hash, contains the
artifact path within the package, verifies the binary hash, and loads the matching
extension name. Any mismatch raises `CRAB405`; it never silently invokes Cargo
from an installed wheel.

Wheels are interpreter-specific (`cpXY-cpXY-platform`), not `abi3`. Build one per
supported CPython/platform combination. This is an alpha wheel command rather than
a general PEP 517 backend: distribution metadata/dependency merging beyond the
required Crabwalk runtime is still the packager's responsibility.
