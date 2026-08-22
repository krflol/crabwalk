# Crabwalk

Crabwalk is an experimental compiler/runtime for opting valid Python functions
into real Rust semantics and native execution. There is no interpreted fallback:
accepted `@rust.fn` bodies become Rust, and unsupported source fails with a
source-oriented `CRAB` diagnostic.

```python
from crabwalk import rust

@rust.fn
def fibonacci(n: rust.u64) -> rust.u64:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

print(fibonacci(40))
```

The current alpha includes:

- checked Rust primitives, `String`, borrowed `Str`, `Vec`, `Option`, and `Result`;
- locals, arithmetic, conditionals, loops, native calls, recursion, and semantic
  receiver/place capability checking;
- one native extension per regular Python package, including imports/re-exports;
- crates.io, path, and Git Cargo dependencies with persisted lock state;
- `Owned`, `Ref`, and `Mut` handles with move/use-after-move and call-scoped
  borrow enforcement;
- Rust structs, unit/tuple/record enums, exhaustive `match`, and narrow derives;
- general patterns and guards, inherent methods, trait objects, selected
  advanced/unsafe Rust, native async, and a finite native thread pool;
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
Cargo. Run the readiness probe before developing from source:

```text
python -m pip install -e .
crabwalk doctor
```

## Commands

```text
crabwalk expand PATH
crabwalk check PATH [--locked] [--offline]
crabwalk build PATH [--locked] [--offline]
crabwalk inspect PATH [--json]
crabwalk show PATH SYMBOL
crabwalk wheel PACKAGE --name DIST --version VERSION
crabwalk cache status PATH [--json]
crabwalk cache prune [PROJECT] [--dry-run]
```

Generated Rust and disposable build/cache state live under `.crabwalk/`.
Resolved generated Cargo dependency locks live under `crabwalk-locks/` and should
be committed. Every compilation unit has one because its graph includes mandatory
PyO3 even when source declares no additional crate.

Normal builds may maintain a copied dependency lock and persist an intentional
Cargo update. Pass `--locked` when the lock must remain byte-for-byte unchanged.

When a `.py` file triggers an implicit first build, Crabwalk reports analysis,
dependency, cache, Cargo, and extension-loading phases on stderr. Interactive
terminals get an animated elapsed-time meter; redirected output gets plain log
lines. Set `CRABWALK_PROGRESS=never` to silence it (for example in CI), or
`CRABWALK_PROGRESS=always` to force progress output.

For bounded project discovery, a project may declare one or more regular packages:

```toml
[tool.crabwalk]
packages = ["src/my_package"]
python-boundaries = "allow" # allow, warn, or deny
extra-files = ["native/schema.proto"]
extra-env = ["MY_NATIVE_MODE"]
wheel-include = ["templates/**/*.html"]
```

When exactly one package is configured, the project directory itself can be passed
to build/inspection commands. `--project PYPROJECT_OR_DIRECTORY` selects an
explicit configuration for a source path.

## Examples

```text
python examples/fibonacci/app.py
python examples/core/app.py
python examples/ownership/app.py
python examples/crates_regex/app.py
python examples/parallel/app.py
# From the examples directory:
python -m the_rust_book.run_all
```

The [Rust Book adaptation](examples/the_rust_book/README.md) covers Chapters 1–21 and doubles as an end-to-end compiler evolution suite.

## Documentation

- [Project hub](Crabwalk%20Project%20Hub.md)
- [Getting started](Docs/Crabwalk%20Getting%20Started.md)
- [Language reference](Docs/Crabwalk%20Language%20Reference.md)
- [Ownership and domain types](Docs/Crabwalk%20Ownership%20and%20Domain%20Types.md)
- [Tooling, packaging, and cache](Docs/Crabwalk%20Tooling%20Packaging%20and%20Cache.md)
- [Security and limitations](Docs/Crabwalk%20Security%20and%20Limitations.md)
- [Compatibility and verification](Docs/Crabwalk%20Compatibility%20and%20Verification.md)
- [Invariant-hardening plan](Planning/Crabwalk%20Invariant%20Hardening.md)
- [Changelog and migration notes](CHANGELOG.md)

The original long-form vision remains in [crabwalk.md](crabwalk.md). The
implemented contract is intentionally narrower; the reference documents state
what is accepted today.
