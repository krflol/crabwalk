---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-30
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
| `check PATH --watch` | polling incremental check loop with the same locks/diagnostics |
| `build PATH` | verified content-addressed native artifact |
| `inspect PATH [--json]` | IR effects, conversions, calls, GIL, cache, dependencies, fingerprint inputs |
| `show PATH SYMBOL` | annotated native function and Python ABI wrapper |
| `wheel PACKAGE` | interpreter/platform wheel containing sources and native artifact |
| `explain CRAB_CODE [--json]` | stable diagnostic explanation and suggested next action |
| `export-rust PATH DESTINATION` | deterministic standalone copy of the generated Cargo project |
| `lsp` | bounded stdio LSP server for source diagnostics |
| `cache status PATH` | hit/miss/corruption status and expected artifact |
| `cache prune` | scoped age/size cleanup with dry-run support |

Inspection schema 3 describes return conversion recursively. Fixed-width scalars
remain constant-cost, while `String`, `Vec`, `Array`, `HashMap`, tuples, options,
and results expose a machine-readable `complexity` plus child conversion records.
Container costs are cardinality-dependent where Python must materialize elements;
a composite return is never described as a scalar merely because PyO3 performs the
conversion in one wrapper call.

The first runtime decorator reached during a package import performs the complete
analysis, fingerprint, Cargo validation, and extension load. Remaining exported
function, struct, and enum decorators in that same initialization bind symbols
from the validated result and share one progress lifecycle. A repeated binding,
such as `importlib.reload`, ends that binding session and re-enters the full service
so non-source build inputs are not hidden by a weaker memo.

`--locked` requires persisted dependency lock state and rejects any Cargo lock
change. `--offline` passes Cargo's offline policy and is fingerprinted. Every
compilation unit has a persisted generated dependency lock, even when mandatory
PyO3 is its only dependency. A normal build copies that lock into the generated
crate, runs without `--locked`, and atomically persists intentional Cargo updates
beneath `crabwalk-locks/`. A changed lock abandons the old-key staging result and
restarts under a fresh fingerprint before publication or loading. Replanning is
iterative and bounded: a dependency graph that changes during three consecutive
plans fails as `CRAB308` instead of recursing indefinitely.

## Fingerprints

The cache key includes:

- reachable native compiler-input hash and module identity;
- a canonical hash of native-relevant `[tool.crabwalk]` settings (packages,
  boundary policy, source lock policy, extra files, and extra environment);
- Crabwalk implementation, IR, codegen, and fingerprint schema versions;
- CPython implementation/version/extension ABI plus resolved executable, prefix,
  and base-prefix identity;
- project-resolved rustc/Cargo executable and toolchain-selector state;
- the complete generated dependency specification, including the mandatory pinned
  PyO3 package, `extension-module` feature, macOS link-config build dependency,
  and internal alias;
- Cargo lock content and complete regular-file path-dependency trees; `.git`,
  `.crabwalk`, and Cargo `target` directories are pruned before traversal;
- release profile, overflow policy, and forced unwind panic strategy;
- Cargo configuration content;
- hashed build-affecting environment variables, including target, flags, wrappers,
  linker/compiler choices, SDK deployment settings, and `PATH`;
- declared `[tool.crabwalk].extra-files` trees and `extra-env` values.

Python-only dependencies, PEP 621 metadata, wheel data patterns, and comments do
not change the native fingerprint. Changing a native-relevant setting does. Wheel
source-integrity hashing remains separate and still covers every shipped Python
source, so avoiding an unnecessary native rebuild does not weaken installed-wheel
tamper detection.

Raw environment values are not written to inspect metadata. Cache manifests bind
the fingerprint, extension initialization name, exact filename, and SHA-256 of the
artifact. A malformed, mismatched, missing, or corrupt entry is rebuilt under an
interprocess lock. Artifact publication and metadata writes are atomic.
Generated inputs are not rewritten when their bytes are unchanged, preserving
mtimes so Cargo validation does not trigger a needless relink or mapped-DLL
replacement.

Cargo incremental state is separated from artifact identity. Crabwalk derives a
target identity from the effective Python installation, Rust/Cargo toolchain,
dependency specification, build environment, Cargo configuration, and release
policy. On POSIX it lives beneath `.crabwalk/target/<identity>` and generated Cargo
projects remain beneath `.crabwalk/generated`. On Windows, both linker-facing path
dimensions use deterministic short roots:
`%TEMP%/cw-targets/<project>-<identity>` and
`%TEMP%/cw-projects/<project>-<kind>-<identity>` for generated builds and dependency
lock bootstraps. This avoids MSVC failures caused by either a deep target or a deep
embedding snapshot/generated-project root. Set
`CRABWALK_CARGO_TARGET_ROOT` and `CRABWALK_CARGO_PROJECT_ROOT` to short writable
roots when host policy requires specific locations; both settings participate in
build identity. Every created target root receives Cargo's standard `CACHEDIR.TAG`
signature and explanatory marker.

Every external artifact hit still invokes Cargo, allowing its dependency,
build-script, and incremental rules to validate inputs. Crabwalk's
cache identity remains content-addressed over the documented/default inputs plus
explicit `extra-files` and `extra-env`; arbitrary undeclared build-script inputs are
outside that contract. On a verified cache hit, a Cargo artifact explicitly reported
as fresh does not replace the independently verified cache entry. If Cargo actually
rebuilds and produces different native bytes under an unchanged fingerprint,
Crabwalk raises `CRAB306` instead of silently changing a content-addressed entry. If
a corrupt entry needs replacement while another process has it mapped, `CRAB307`
defers recovery until that process exits.

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
acquiring deletion leases. If an entry lock is busy, Crabwalk does not inspect its
files. If an inventoried entry changes, becomes locked, disappears, or cannot be
deleted during the second phase, its earlier snapshot is also discarded. Prune
results therefore report known remaining bytes, `uncertain_entries`, and an unknown
byte-limit status instead of claiming a ceiling was met from incomplete or stale
information. `busy_entries` remains a compatibility alias for that broader count.
Lease-file locks—not reusable process IDs—are authoritative for mapped-artifact
lifetime.

## Declaring nonstandard build inputs

```toml
[tool.crabwalk]
packages = ["src/my_package"]
extra-files = ["native/schema.proto", "native/templates"]
extra-env = ["OPENSSL_DIR", "MY_NATIVE_MODE"]
wheel-include = ["templates/**/*.html", "py.typed"]
source-locked = true
```

Paths are project-relative, must remain inside the configured project, and must
exist. Environment values participate by SHA-256 only; raw values are not persisted
to build-input inspection metadata.

Decorator-driven source imports normally use the lock-maintaining Cargo policy,
so they intentionally have a different fingerprint from a CLI build requested
with `--locked`. Set `source-locked = true` to require locked source imports and
reuse the corresponding complete fingerprint. `crabwalk inspect` and each compiled
function's `__crabwalk__["cargo_policy"]` expose the effective locked/offline state.

## Building a user wheel directly

```powershell
crabwalk wheel src\my_package `
  --project . `
  --name my-distribution `
  --version 1.2.3 `
  --output-dir dist
```

The direct command targets one regular or configured namespace top-level package
and the running CPython ABI/platform. `--project` accepts either a project directory or its
`pyproject.toml`; when that configuration declares exactly one package, the project
path itself may be used as the positional input. As with neighboring commands,
`--project` selects configuration and containment policy without rebasing a relative
positional path. The command:

1. statically analyzes and compiles the complete package;
2. copies `.py`, `.pyi`, and `py.typed` plus explicitly configured `wheel-include`
   package data, while rejecting symlinks and common secret/private-key names;
3. embeds the extension beneath `_crabwalk_native/`;
4. embeds `_crabwalk_prebuilt.json` with source/artifact hashes, compiler
   provenance, runtime/generated-wrapper ABI versions, compatibility range,
   effective Cargo policy, and the dependency-lock SHA-256;
5. writes deterministic wheel metadata and a hashed `RECORD`;
6. declares the compatible Crabwalk runtime line as a dependency.

Normal pip installation resolves that dependency by distribution name. The import
package and CLI remain `crabwalk`; application wheels generated by Crabwalk 1.0.0
must be rebuilt because their metadata named the pre-rename `crabwalk` project.

On import, the installed runtime re-analyzes source without executing it. It
verifies both the reachable compiler-input hash and a separate integrity hash for
every shipped `.py`/`.pyi` file, then checks the manifest schema, runtime and
generated-wrapper ABIs, contained artifact path, binary hash, and extension name.
Generator version is retained as provenance; compatible patch runtimes may load the
artifact without forcing a rebuild.
Any mismatch raises `CRAB405`; it never silently invokes Cargo from an installed
wheel.

The installed function's `__crabwalk__["cargo_policy"]` retains those immutable
build facts with `origin: "prebuilt"`, and
`__crabwalk__["dependency_lock_hash"]` exposes the lock identity; locked wheels
therefore remain auditable without Cargo or the original build directory.

Wheels are interpreter-specific (`cpXY-cpXY-platform`), not `abi3`. Build one per
supported CPython/platform combination.

## PEP 517 application backend

For an ordinary Python distribution, configure:

```toml
[build-system]
requires = ["crabwalk-lang>=1.1,<1.2"]
build-backend = "crabwalk.build_backend"
```

The backend supports `python -m build`, `pip wheel .`, `pip install .`, metadata
preparation, and deterministic sdists. It merges static PEP 621 dependencies,
optional dependencies, scripts, arbitrary entry-point groups, classifiers,
authors/maintainers, URLs, readme, license expression/files, and allowed package
data with Crabwalk's runtime requirement and embedded artifacts. Every configured
top-level regular or namespace package gets its own extension/manifest inside one
wheel. A clean acceptance test installs that multi-package wheel through normal
dependency resolution and runs both native modules with Cargo/rustc absent.

Dynamic project name/version metadata is rejected because the native distribution
identity must be reproducible. Editable PEP 660 builds are not yet supplied by the
application backend; use an editable Crabwalk runtime checkout and source imports
during development.

## Diagnostics, watch, and editor integration

`expand`, `check`, and `build` accept `--diagnostic-format json`, whose envelope is
versioned independently from the human renderer. `crabwalk explain CRAB_CODE`
describes a diagnostic without running a build. `check --watch` polls the reachable
source/config inputs and reruns the same static/Cargo check path after changes.
`crabwalk lsp` implements initialize/shutdown plus open/change diagnostics over
stdio; it intentionally does not yet advertise completion or refactoring.

`export-rust` copies the exact deterministic generated crate plus an export
manifest into an empty destination. This is the supported extraction/debugging
path; it refuses to merge into a non-empty tree where stale handwritten files
could make the result ambiguous.
