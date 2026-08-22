---
type: quality-plan
project: Crabwalk
status: proposed
created: 2026-08-21
updated: 2026-08-21
tags:
  - project/crabwalk
  - area/testing
  - area/release
  - area/security
---

# Crabwalk Verification and Release

This plan defines the evidence required by [[Crabwalk Roadmap]]. Crabwalk sits across a source language, compiler, build system, native ABI, cache, package loader, and distribution system; a passing unit suite in only one layer is not meaningful release evidence.

## Verification principles

1. Test the language contract, not just implementation functions.
2. Every supported source form has a positive case, a misuse case, and an unsupported-neighbor case.
3. Every failure is tested for source location and diagnostic identity as well as failure/no-failure.
4. Generated Rust is compiled; snapshots alone are insufficient.
5. Runtime tests prove native execution and boundary behavior.
6. Cache tests observe process execution and artifact identity, not just a reported “hit.”
7. Cross-platform extension builds and clean installs are release gates.
8. Golden files are deterministic review artifacts, not a substitute for semantic assertions.
9. No test may rely on silently executing the original Python body.
10. Build trust and path handling receive adversarial tests before compiling untrusted projects is encouraged.

## Test layers

| Layer | What it proves | Typical oracle | Runs |
|---|---|---|---|
| Source/AST | Python parsing, positions, declaration recognition | Structured snapshot plus direct assertions | Every PR |
| Symbols/types | Static name/path/type resolution | Resolved-symbol and error assertions | Every PR |
| IR | Semantic lowering, types, effects, spans, calls | Schema-versioned readable golden | Every PR |
| Validation | Strict supported subset and actionable rejection | CRAB code, primary span, suggestion | Every PR |
| Code generation | Deterministic, inspectable Rust/Cargo/source map | Byte golden plus range invariants | Every PR |
| Rust compile-pass | Generated Rust is valid | cargo check/build success | Every PR for focused matrix |
| Rust compile-fail | rustc failures remap correctly | Rust code plus Python span assertions | Every PR |
| ABI/runtime | Native call, conversions, errors, GIL/panic behavior | Python assertions and tracing | Every PR for primary platform; matrix in CI |
| Cache/concurrency | Correct reuse/invalidation/locking/recovery | Process-runner log, hashes, multi-process assertions | Every PR core; stress scheduled |
| Package graph | Python modules/re-exports map to one crate | Multi-file fixtures and import behavior | M2 onward |
| Dependency | Cargo declarations/lock/offline behavior | Cargo metadata and clean-cache scenarios | M4 onward |
| Packaging | Wheel contents and clean consumer behavior | Isolated build/install/run | Release CI |
| Security | No path/command/cache/diagnostic trust regression | Adversarial fixtures and threat-model checks | Every PR relevant; scheduled |
| Performance | Cold/warm build and call/boundary regressions | Recorded benchmarks with environment | Scheduled and release |

## Proposed fixture layout

    tests/
      fixtures/
        m1/
          fibonacci/
            source/
              app.py
            expected/
              ir.yaml
              generated.rs
              source-map.json
              inspect.txt
        core/
          arithmetic/
          control_flow/
          strings/
          vec/
          option/
          result/
        packages/
          cross_module/
          reexports/
          import_cycle/
        boundaries/
          conversions/
          python_print/
          failures/
        crates/
          regex/
          resolution_failures/
        ownership/
          move/
          borrow/
          reentrancy/
        diagnostics/
          crab/
          rustc/
        cache/
          invalidation/
          concurrent/
          corruption/
        packaging/
          minimal/
      unit/
      golden/
      compile/
      runtime/
      integration/
      packaging/

Each fixture declares:

- contract feature(s) and milestone;
- expected status: pass, reject-before-codegen, rustc-fail, runtime-fail;
- expected CRAB and rustc codes;
- primary/related source spans using stable source markers;
- boundary effects;
- expected generated/IR golden files when useful;
- platform restrictions, if any, with justification; and
- cache inputs expected to invalidate.

## Stable source markers

Avoid brittle hard-coded line numbers in test code. Fixture comments can name spans:

    # error: unsupported-start
    values = [x for x in items]
    # error: unsupported-end

The harness resolves markers to byte/line coordinates, then asserts that the diagnostic selects the intended token range. Keep separate Unicode/CRLF tests to validate the coordinate implementation itself.

## Golden-file discipline

- Golden updates require an explicit command/flag and appear as ordinary review diffs.
- Each golden begins with its schema version and relevant fixture identity.
- Normalize generated newlines, stable ordering, workspace-relative paths, and nondeterministic hashes only where the hash is separately asserted.
- Never normalize away semantic differences, source-map ranges, compiler codes, or boundary effects.
- Rust compiler prose can change between toolchains. Assert stable rustc code, severity, mapped Python span, and key labels; keep full rendered goldens only on pinned CI toolchains.
- Generated Rust goldens must also compile or intentionally compile-fail.
- A byte-identical expand test runs twice in separate temporary roots to catch absolute-path and ordering leaks.

## Contract coverage matrix

Maintain a generated table that maps each row in [[Crabwalk Product Contract#v0.1 source surface]] to:

- positive fixture;
- negative/misuse fixture;
- Unsupported-neighbor fixture;
- diagnostic code;
- codegen path;
- boundary classification;
- platform runtime evidence; and
- documentation example.

The v0.1 gate fails if a Supported row lacks any required evidence or if a Deferred row is accepted without a decision record.

## Native-execution evidence

Use multiple independent signals:

1. The decorated object is a Crabwalk RustFunction bound to an extension symbol.
2. Generated inspection shows an internal native function and direct Rust call edges.
3. Python tracing/profiling emits no Python line events for a Rust function body or its recursive calls.
4. A native-only call graph contains no `PythonRuntime` effect.
5. A test-only build manifest lists the exported native symbol and artifact fingerprint.
6. Boundary instrumentation counts zero Python-runtime entries for a native-only fixture.

Timing alone is not proof of native execution.

## Semantic test matrix

### Types and conversions

For every integer type:

- exact minimum and maximum;
- minimum minus one and maximum plus one;
- zero, one, negative input to unsigned;
- Python bool input;
- non-int input;
- output round trip;
- arithmetic overflow behavior in every build profile.

For floats:

- int and float input policy;
- finite values;
- positive/negative zero;
- infinities and NaN policy;
- f32 narrowing;
- wrong type;
- round trip and comparison edge cases.

For strings:

- empty and ASCII;
- multi-byte Unicode;
- combining characters;
- embedded NUL;
- large input;
- borrowed call-duration Str;
- attempted borrow escape;
- allocation effect in inspect output.

For Vec/Option/Result:

- empty/non-empty/nested supported concrete types;
- element conversion error with index path;
- None/Some behavior;
- Ok/Err behavior inside Rust and at export;
- moves versus copies;
- exception during conversion and cleanup.

### Operators and control flow

- Every allowed operator for every compatible type pair.
- Every incompatible pair produces a localized error.
- Division/overflow/truthiness differences are explicit.
- Single-evaluation behavior when calls appear in operands.
- Branch joins, early returns, nested loops, break/continue.
- Definite assignment on all paths and rejected maybe-uninitialized reads.
- Rebinding that does and does not require mut.
- Native recursion, mutual recursion, and deep-call failure behavior.

### Module/package behavior

- Flat and src layouts.
- Relative and absolute imports.
- __init__.py façade re-exports.
- Same short symbol name in different modules.
- Package names requiring Rust identifier sanitization.
- Import cycles.
- Namespace-package policy once decided.
- Symlinks/case differences according to platform policy.
- Project relocation produces the same semantic fingerprint unless a path dependency makes location meaningful.

## Diagnostic verification

Every diagnostic test asserts:

- stable CRAB code;
- severity/title;
- exact primary Python source marker;
- related marker(s) where applicable;
- suggested alternative or explanation;
- underlying rustc code when present;
- no generated file as the primary display;
- generated detail remains accessible;
- Unicode and terminal-control content is escaped safely; and
- text and machine-readable renderers represent the same event.

Required diagnostic scenarios include:

- missing rustc/Cargo/linker;
- project root ambiguity;
- malformed configuration;
- unsupported AST node;
- unresolved Rust/Python symbol;
- invalid/missing annotation;
- bad call arity;
- missing return;
- truthiness/semantic mismatch;
- Cargo dependency and offline failures;
- rustc type and borrow errors;
- Python conversion failure;
- panic and Result::Err;
- cache corruption;
- artifact module-name/ABI mismatch; and
- moved/borrow-conflict errors in M5.

## Source-map verification

Test:

- LF and CRLF;
- ASCII and multi-byte UTF-8 before/inside the selected span;
- multi-line expressions;
- generated temporaries that map back to one expression;
- one Python expression producing several Rust ranges;
- one Rust diagnostic with primary and secondary spans;
- wrapper/helper error mapped to function/decorator fallback span;
- cross-module related spans;
- rustc suggestions;
- source edited after build but before diagnostic display;
- mapping schema mismatch; and
- missing/corrupt map fallback.

The map must use source content hashes so a diagnostic cannot confidently point into a different version of the file.

## Cache and reproducibility verification

### Required invalidation tests

Each of these must cause a miss when relevant:

- Rust-enabled source bytes;
- import/re-export graph;
- Crabwalk configuration;
- IR/codegen/source-map schema;
- compiler/runtime protocol version;
- Python implementation/ABI;
- PyO3 version/features;
- rustc/Cargo/toolchain;
- host/target/profile/controlled flags;
- crate declaration/features/source;
- dependency lock;
- generated runtime template.

Each of these should not cause a miss unless documented:

- file modification time alone;
- unrelated non-Rust source outside the conservative package dependency set once refinement exists;
- absolute project relocation without location-sensitive path dependencies;
- CLI output verbosity/color choice.

### Concurrency and failure tests

- Two, ten, and many processes request the same missing key.
- Different keys build concurrently.
- Builder is killed before/after artifact creation and before atomic publish.
- Waiting process is cancelled.
- Lock holder crashes.
- Manifest exists but artifact is absent.
- Artifact hash is wrong.
- Map/metadata schema is unsupported.
- Target disk becomes full.
- Cache entry is read-only.
- Cleanup runs while another process loads an entry.

A valid-hit test injects/logs the process runner and asserts zero Cargo/rustc processes, not just cache_status == hit.

## ABI and runtime verification

- Native wrapper rejects invalid inputs before calling internal Rust.
- Conversion cleanup is safe when the nth argument/element fails.
- Internal native error becomes the documented Python exception.
- Panic cannot unwind across the ABI.
- Python exception from a boundary preserves useful traceback/context.
- GIL is released for a long native-only function when contracted.
- GIL/runtime access is reacquired only for classified boundaries.
- Nested and reentrant Python boundary calls cannot violate borrow state.
- Extension module filename and initialization symbol match.
- Two content-addressed versions coexist and remain callable.
- Reload and garbage-collection behavior are documented and tested.
- Free-threaded CPython is unsupported or separately tested; it is never assumed equivalent to a GIL-enabled build.

Use Python debug builds, native sanitizers, Miri, or equivalent tools where they can exercise handwritten runtime glue. Generated safe Rust still needs ABI and state-machine testing.

## Dependency and supply-chain verification

M4 adds tests for:

- registry dependency with a lock;
- features and aliases;
- local path dependency;
- path outside the project policy;
- Git dependency policy if enabled;
- offline/locked success and failure;
- registry/network failure;
- yanked/incompatible resolution error;
- dependency with a build script;
- build-script output in Cargo JSON stream;
- Cargo configuration and credentials not leaked in diagnostics;
- exact dependency graph shown by inspect; and
- cache invalidation when lock/features/source change.

Crabwalk does not claim to sandbox Cargo, rustc, procedural macros, or build scripts. Documentation and CLI warnings must say that compiling an untrusted Crabwalk project has the same class of code-execution risk as building an untrusted Rust project.

## Security test themes

- Pass subprocess arguments as arrays; no source-derived shell command construction.
- Reject/sanitize generated Rust identifiers, paths, module names, Cargo names, and native filenames.
- Ensure resolved generated/cache/staging paths stay under their intended roots.
- Treat symlinks, junctions, case folding, reserved Windows names, and path traversal explicitly.
- Use per-entry atomic publish; never load an artifact before hash/manifest verification.
- Avoid broad recursive deletion; cleanup operates only on verified entry directories.
- Escape untrusted source/compiler text for terminal and machine-readable output.
- Do not expose environment secrets, Cargo credentials, URLs with tokens, or full sensitive paths by default.
- Bound compiler output, source snippets, cache size, and wait behavior against denial-of-service.
- Record exact tool/dependency inputs for incident reproduction.

## Proposed compatibility matrix

The owner ratifies exact versions in M0. Until then:

| Dimension | M1 evidence | v0.1 alpha gate |
|---|---|---|
| Python | Latest stable CPython on Windows and Linux | Lowest supported + latest stable + one intermediate CPython |
| Rust | Current stable | Declared MSRV + current stable |
| OS | Windows x86-64 and Linux x86-64 required; macOS advisory if unavailable | Windows, Linux, and macOS required |
| Architecture | x86-64 | x86-64 required; macOS arm64 required if distributed |
| Build profile | Development | Development and release |
| Install mode | Editable/source | Clean source build and wheel install |
| Python runtime model | GIL-enabled CPython | Same; free-threaded explicitly unsupported or separately gated |

Do not advertise an OS, architecture, Python implementation, stable ABI, or free-threaded mode that is not in required CI.

## CI lanes

### PR fast lane

- Python formatting/lint/type checks
- Unit/source/symbol/IR/validation tests
- Deterministic codegen goldens
- Focused Cargo check and primary-platform runtime tests
- Diagnostic and basic cache tests

Target: fast enough to run on every change.

### PR native matrix

- Required OSes for the current milestone
- Primary Python and Rust toolchain
- Compile-pass/fail, load, ABI, native execution
- Cross-platform path/module-name/source-map tests

### Merge/nightly stress lane

- Lowest/latest Python and MSRV/stable Rust combinations
- Multi-process cache races and interruption
- Large fixture/package graph
- Property/fuzz tests
- Sanitizer/Miri-compatible runtime glue tests
- Performance trend recording

### Packaging lane

- Isolated sdist/wheel build
- Inspect wheel contents
- Install into a toolchain-free consumer image/VM
- Run examples and metadata/import tests
- Verify no generated cache/build workspace leaks into the wheel

### Release lane

- Full required matrix without relying on project artifact cache
- Reproducibility comparison where feasible
- Artifact hashes/inventory
- Documentation link and example checks
- License/dependency notices
- Signed/tagged release process once governance selects it

## Performance baselines

Measure before assigning thresholds:

| Metric | Required invariant |
|---|---|
| Cold compile | Report frontend, codegen, dependency build, crate build, and load separately. |
| Warm Cargo build | Distinguish Cargo dependency reuse from Crabwalk artifact hit. |
| Crabwalk cache hit | Zero Cargo/rustc for dependency-free projects; user crates may run Cargo validation without a relink. |
| Cached import | Content-keyed static analysis/fingerprinting and verified load only; report each phase. |
| Primitive Python→Rust call | Compare wrapper overhead across supported Python versions. |
| Native loop/recursion | Confirm work stays in Rust and scales independently of Python tracing. |
| Python boundary call | Measure each crossing separately. |
| String/container conversion | Report bytes/elements and allocations where practical. |

Release gates should initially prevent severe regressions relative to a checked-in baseline, not promise arbitrary absolute millisecond targets across machines.

## Milestone release gates

### M1 technical proof

- [x] Fibonacci expands, compiles, loads, and returns the correct result.
- [x] Python tracing sees no lines/recursive Python frames for the native body.
- [x] Invalid u64 inputs fail correctly.
- [x] Unsupported syntax fails before codegen.
- [x] One rustc error maps to the intended Python tokens.
- [x] Second-process unchanged run starts no Cargo process.
- [x] Two fingerprints coexist in one process.
- [ ] Windows and Linux required jobs pass.
- [x] Generated Rust/IR/map/build inputs are inspectable.

### M2 core compiler

- [x] Contract coverage matrix is complete for the M2 subset.
- [x] Multi-module/re-export example compiles as one crate.
- [x] Primitive/operator/control-flow edge matrices pass.
- [x] String/Str lifetime tests pass.
- [x] Vec is real Rust and never an implicit Python list.
- [x] Option/Result behavior is stable inside and across the ABI.
- [x] Every misuse has a source-located diagnostic.
- [x] Determinism and cache invalidation still pass.

### v0.1 alpha release gate

- [ ] M1 and M2 gates pass.
- [x] Typed native/conversion/Python/blocking/threading/unsafe/mutation/panic effects are complete and inspectable.
- [x] Python print boundary and rust.println native path are distinguished.
- [x] Panic, GIL, conversion, and Result error contracts pass.
- [x] Source maps pass Unicode/CRLF/multi-file/helper cases.
- [x] Cache concurrency, interruption, corruption, environment invalidation, load leases, and local prune/build/load stress pass.
- [x] doctor/check/build/expand/show/inspect behavior is documented and tested.
- [x] Clean wheel builds and runs without Rust on the consumer.
- [ ] Lowest/latest supported Python, MSRV/stable Rust, and Windows/Linux/macOS pass.
- [x] Security/trust model and known limitations are published.
- [ ] Changelog, migration notes, artifact inventory, licenses, and hashes are present.
- [x] No Deferred feature is accidentally accepted or advertised.

### M4 ecosystem alpha

- [x] Regex crate demonstration passes source, cached, locked, offline-prepared, and wheel scenarios.
- [x] Cargo manifest and lock are deterministic and inspectable.
- [x] Crate API and resolution errors map to Python.
- [x] Dependency build-script trust is disclosed.
- [x] Path/Git/feature policies have positive and adversarial tests.

### M5 ownership preview

- [x] Owned/Ref/Mut lower to real Rust signature semantics.
- [x] Wrapper aliasing observes one shared move state.
- [x] Double move and use-after-move fail safely.
- [x] Shared/mutable borrow conflicts fail safely.
- [x] Exceptions, reentrancy, GC, threads, and reload cannot violate the state machine.
- [x] Unsupported escaping borrows are rejected.
- [x] Ownership diagnostics include definition and move/borrow sites.

## Release artifact checklist

- Python sdist and wheels for every advertised platform
- Package metadata, license, README, and type information policy
- Compiler/runtime protocol version
- Generated-schema and source-map-schema versions
- CLI help and shell-exit behavior
- Compatibility matrix and toolchain requirements
- Language contract and unsupported list
- Security/trust and dependency-build disclosure
- Changelog and migration notes
- Dependency/license inventory
- Artifact hashes and provenance/signature policy
- Clean-install smoke results
- Example outputs and generated Rust for the release’s primary demonstrations

## Compatibility and rollback policy

- Cache entries are namespaced by compiler/runtime/schema versions; incompatible releases never reuse them.
- Generated artifacts are not a stable public ABI until declared. A clear error should request rebuild when protocols differ.
- Diagnostic codes are stable once published; message prose may improve.
- Syntax/semantic breaking changes require a versioned contract update and migration note.
- A release with an ABI, cache-integrity, or soundness defect is yanked/recalled according to governance and followed by a patched release; documentation must identify affected fingerprints/versions.
- Users can remove one verified cache entry or rebuild all artifacts through a scoped Crabwalk command; no recovery instruction uses broad destructive filesystem operations.

## Release evidence record

For each release, create a dated note or machine-generated report containing:

- source commit/tag;
- supported matrix;
- tool/dependency versions;
- CI run links;
- test counts by layer;
- known skips and waivers;
- benchmark environment/results;
- artifact hashes;
- security review changes;
- open high risks; and
- owner sign-off.

No milestone waiver is implicit. A waived gate records owner, rationale, user impact, mitigation, and expiry/revisit date in [[Crabwalk Risks and Decisions]].
