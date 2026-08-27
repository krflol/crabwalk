# Crabwalk

[![CI](https://github.com/krflol/crabwalk/actions/workflows/ci.yml/badge.svg)](https://github.com/krflol/crabwalk/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/crabwalk-lang.svg)](https://pypi.org/project/crabwalk-lang/)
[![Python](https://img.shields.io/pypi/pyversions/crabwalk-lang.svg)](https://pypi.org/project/crabwalk-lang/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/krflol/crabwalk/blob/main/LICENSE)

**Python outside. Rust inside.**

Crabwalk is a compiler/runtime for opting an explicit subset of Python functions
into real Rust semantics and native execution. There is no interpreted fallback:
accepted `@rust.fn` bodies become inspectable Rust, rustc checks the generated
program, and unsupported source fails with a source-oriented `CRAB` diagnostic.

```python
from crabwalk import rust

rayon = rust.crate("rayon", version="1.12.0")

@rust.fn
def parallel_sum(n: rust.u64) -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([])
    for value in range(n):
        values.push(value)
    return values.par_iter().copied().sum()

print(parallel_sum(5_000_000))
```

Those annotations are concrete Rust types, `Vec[rust.u64]` becomes `Vec<u64>`,
and `par_iter()` is real Rayon parallelism resolved through Cargo.

## Why Crabwalk

Python keeps ownership of the application, libraries, orchestration, and
presentation. Selected typed regions gain native execution, Cargo crates, rustc
checking, explicit ownership, GIL-aware concurrency, and source-mapped compiler
diagnostics without requiring a handwritten PyO3 project for every kernel.

- **Gradual native adoption:** move one hot path at a time instead of starting a
  ground-up rewrite.
- **Two ecosystems in one program:** compose FastAPI, NumPy, and Matplotlib with
  Rayon, `libm`, and other expressible Cargo APIs.
- **Visible boundaries:** conversions, moves, shared borrows, mutable borrows,
  panic translation, and GIL behavior are explicit.
- **Low-overhead numeric input:** `rust.Buffer[T]` can lease existing read-only,
  contiguous `memoryview`, `array`, and compatible NumPy storage for one native
  call without constructing a Rust-owned `Vec` or copying its elements.
- **Less integration machinery:** Crabwalk generates Cargo and PyO3 projects,
  builds and caches extensions, and maps native errors back to Python source.
- **An extraction path:** inspect generated Rust today and promote a mature kernel
  into a purpose-built Rust crate when it outgrows the application boundary.

Crabwalk does not claim that arbitrary Python is Rust. It statically checks its
supported compiled subset, asks rustc to check the generated Rust, and validates
exported values at runtime boundaries.

## Showcase

The reproducible showcase combines FastAPI, NumPy, Matplotlib, Rayon, `libm`,
owned Rust vectors, async scheduling, and GIL-detached native work:

```text
python -m pip install fastapi uvicorn numpy matplotlib
python examples/showcase/showcase_api.py
```

Open `http://127.0.0.1:8001/docs`, or run the focused examples:

```text
python examples/showcase/true_par.py
python examples/showcase/etl_rayon.py
python examples/showcase/fastapi_mre.py
python examples/showcase/ml_mre.py
```

Verified warm runs on the development machine showed a Rayon sum around **7.8x**
faster than an explicit Python loop, and the educational logistic-regression
trainer around **3.4x–5.5x** faster than its vectorized NumPy implementation and
**8.7x–17.6x** faster than equivalent scalar Python loops. These are local kernel
measurements—not universal speed claims—and exclude compilation, HTTP transport,
serialization, evaluation, and plotting.

![Logistic regression trained in Rust and plotted in Python](https://raw.githubusercontent.com/krflol/crabwalk/main/examples/showcase/ml_decision_curve.png)

See the [full showcase guide](https://github.com/krflol/crabwalk/tree/main/examples/showcase)
for routes, expected outputs, ownership observations, measurement boundaries, and
precise wording for public claims.

## What works today

The current compiler surface includes:

- checked Rust primitives, `String`, borrowed `Str`, read-only numeric `Buffer`,
  `Vec`, `Option`, and `Result`;
- locals, arithmetic, conditionals, loops, native calls, recursion, and semantic
  receiver/place capability checking;
- one native extension per regular Python package, including imports/re-exports;
- crates.io, path, and Git Cargo dependencies with persisted lock state;
- `Owned`, `Ref`, and `Mut` handles with move/use-after-move and call-scoped
  borrow enforcement;
- Rust structs, unit/tuple/record enums, exhaustive `match`, and narrow derives;
- general patterns and guards, inherent methods, trait objects, audited
  advanced/unsafe teaching intrinsics, a std-only future teaching executor, and a
  finite unit-job native thread pool;
- Python `print` versus native `rust.println`, panic containment, typed `Result`
  errors, dispatch-aware typed effects, boundary-placement validation, and
  non-panicking worker teardown;
- native Rayon iterators and an explicit `rust.async_call` Python async boundary;
- verified artifact caching, inspection commands, and wheels with embedded native
  extensions that need no Rust toolchain on the consumer machine.

## Requirements

- CPython 3.11–3.14
- stable Rust with Cargo for source development/builds
- a native linker suitable for CPython extensions

Consumers installing a Crabwalk-built application wheel do not need Rust or
Cargo. Install Crabwalk and run the readiness probe before developing from source:

```text
python -m pip install crabwalk-lang
crabwalk doctor
```

The distribution is named `crabwalk-lang`; the import package and command remain
`crabwalk`.

For an editable checkout, replace the install command with
`python -m pip install -e .`.

## Commands

```text
crabwalk expand PATH
crabwalk check PATH [--locked] [--offline]
crabwalk build PATH [--locked] [--offline]
crabwalk inspect PATH [--json]
crabwalk show PATH SYMBOL
crabwalk wheel PACKAGE [--project PROJECT] --name DIST --version VERSION
crabwalk cache status PATH [--json]
crabwalk cache prune [PROJECT] [--dry-run]
```

Generated Rust and disposable build/cache state live under `.crabwalk/`.
Resolved generated Cargo dependency locks live under `crabwalk-locks/` and should
be committed. Every compilation unit has one because its graph includes mandatory
PyO3 even when source declares no additional crate.

See the [compiler architecture](Docs/Crabwalk%20Compiler%20Architecture.md) for
the pass pipeline, hygienic identity model, tagged type algebra, iterator contract,
and the invariants required when extending the compiled language.

Normal builds may maintain a copied dependency lock and persist an intentional
Cargo update. Pass `--locked` when the lock must remain byte-for-byte unchanged.

Applications that accept editable source can compile and bind exported functions
without importing or executing that Python module:

```python
from crabwalk import compile_source

compiled = compile_source(
    editor_text,
    filename="recipe.py",
    progress=show_compile_phase,
)
transform = compiled.function("transform")
```

`compile_source` stores a content-addressed UTF-8 snapshot for diagnostics and
Cargo source maps, then binds `RustFunction` objects directly from the static IR
and loaded extension. Top-level Python statements in the authored source are not
executed. This is not a sandbox for Cargo dependencies, build scripts, proc macros,
or linkers; apply an application-specific source/effect/crate policy before building
untrusted input. Cancellation is cooperative between phases and cannot preempt an
already-running Cargo process.

When a `.py` file triggers an implicit first build, Crabwalk reports analysis,
dependency, cache, Cargo, and extension-loading phases on stderr. Interactive
terminals get an animated elapsed-time meter; redirected output gets plain log
lines. A package import reports one lifecycle for its compilation unit; later
decorators bind symbols from that already-loaded result without replaying the
meter. Set `CRABWALK_PROGRESS=never` to silence it (for example in CI), or
`CRABWALK_PROGRESS=always` to force progress output.

For bounded project discovery, a project may declare one or more regular packages:

```toml
[tool.crabwalk]
packages = ["src/my_package"]
python-boundaries = "allow" # allow, warn, or deny
source-locked = true # require Cargo --locked for decorator-driven source imports
extra-files = ["native/schema.proto"]
extra-env = ["MY_NATIVE_MODE"]
wheel-include = ["templates/**/*.html"]
```

When exactly one package is configured, the project directory itself can be passed
to build, inspection, and wheel commands. `--project PYPROJECT_OR_DIRECTORY`
selects an explicit configuration for a source path. It does not rebase that
positional source: relative source paths resolve from the current working directory.
For an out-of-tree project copy, change into its root or pass an absolute source
path beneath it.

## Examples

```text
python examples/fibonacci/app.py
python examples/core/app.py
python examples/ownership/app.py
python examples/buffer/app.py
python examples/crates_regex/app.py
python examples/parallel/app.py
# From the examples directory:
python -m the_rust_book.run_all
```

The [Rust Book adaptation](https://github.com/krflol/crabwalk/tree/main/examples/the_rust_book)
covers Chapters 1–21 and doubles as an end-to-end compiler evolution suite.
That is chapter coverage, not a claim that every represented Rust subsystem is
feature-complete. The [generated capability maturity table](https://github.com/krflol/crabwalk/blob/main/Docs/Crabwalk%20Language%20Reference.md#capability-maturity)
separates proofs, bounded surfaces, and compositional support.

## Documentation

- [Project hub](https://github.com/krflol/crabwalk/blob/main/Crabwalk%20Project%20Hub.md)
- [Getting started](https://github.com/krflol/crabwalk/blob/main/Docs/Crabwalk%20Getting%20Started.md)
- [Language reference](https://github.com/krflol/crabwalk/blob/main/Docs/Crabwalk%20Language%20Reference.md)
- [Ownership and domain types](https://github.com/krflol/crabwalk/blob/main/Docs/Crabwalk%20Ownership%20and%20Domain%20Types.md)
- [Tooling, packaging, and cache](https://github.com/krflol/crabwalk/blob/main/Docs/Crabwalk%20Tooling%20Packaging%20and%20Cache.md)
- [Security and limitations](https://github.com/krflol/crabwalk/blob/main/Docs/Crabwalk%20Security%20and%20Limitations.md)
- [Compatibility and verification](https://github.com/krflol/crabwalk/blob/main/Docs/Crabwalk%20Compatibility%20and%20Verification.md)
- [Release process](https://github.com/krflol/crabwalk/blob/main/Docs/Release%20Process.md)
- [Governance](https://github.com/krflol/crabwalk/blob/main/GOVERNANCE.md)
- [Security policy](https://github.com/krflol/crabwalk/blob/main/SECURITY.md)
- [Changelog and migration notes](https://github.com/krflol/crabwalk/blob/main/CHANGELOG.md)

The original long-form vision remains in
[crabwalk.md](https://github.com/krflol/crabwalk/blob/main/crabwalk.md). The
implemented contract is intentionally narrower; the reference documents state what
is accepted today.

## License

Crabwalk is licensed under the
[Apache License 2.0](https://github.com/krflol/crabwalk/blob/main/LICENSE).
