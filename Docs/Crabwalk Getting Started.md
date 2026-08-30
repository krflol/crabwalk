---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-30
tags:
  - project/crabwalk
  - docs/getting-started
---

# Crabwalk Getting Started

Crabwalk compiles explicitly decorated, valid Python into a native PyO3
extension. Importing a source checkout eagerly compiles the package the first
time a Crabwalk decorator executes. Unchanged imports reuse a verified,
content-addressed artifact. Installed application wheels load their embedded
artifact and do not invoke Cargo.

## Install

```powershell
python -m pip install crabwalk-lang
crabwalk doctor
```

The PyPI distribution is named `crabwalk-lang`; Python imports and the CLI remain
`crabwalk`.

For an editable source checkout:

```powershell
python -m pip install -e .
python -m pytest tests/unit
```

`doctor` checks the interpreter, ABI suffix, Python headers, rustc, Cargo, the
native linker, and temporary-directory writability. Source builds currently
target CPython 3.11–3.14 and stable Rust.

## First native function

Create `app.py`:

```python
from crabwalk import rust

@rust.fn
def sum_to(stop: rust.u64) -> rust.u64:
    total: rust.u64 = 0
    for value in range(stop):
        total += value
    return total

print(sum_to(10))
print(sum_to.__crabwalk__)
```

Run it normally:

```powershell
python app.py
```

The decorator returns a `RustFunction`, not the original Python function. Its
metadata identifies the build fingerprint, extension, native symbol, artifact,
effects, GIL policy, and cache state. The Python body is never a fallback.

## Inspect before running

```powershell
crabwalk inspect app.py
crabwalk inspect app.py --json
crabwalk show app.py sum_to
crabwalk expand app.py
crabwalk check app.py
crabwalk build app.py
```

`inspect` is the best overview: it lists source files, Cargo inputs, exact
fingerprint inputs, cache status, effects, native/Python calls, conversions,
ownership, and whether the exported wrapper releases the GIL. `show` prints the
native implementation and Python ABI wrapper for one symbol.

## Embed editable source without importing it

Use the public source API when an editor, service, or plugin host needs native
callables but must not execute the authored module's top-level Python:

```python
from crabwalk import compile_source

phases: list[str] = []
compiled = compile_source(
    source_text,
    filename="recipe.py",
    cache_directory=".recipe-cache",
    progress=phases.append,
)
transform = compiled.function("transform")
```

The returned `CompiledSource` exposes `functions`, `function(name)`, `fingerprint`,
`source_hash`, `source_path`, and `inspect()`. Crabwalk normalizes the text to UTF-8,
stores an immutable content-addressed snapshot, performs static analysis, builds and
loads the extension, and binds exported `RustFunction` objects directly from IR.
It never imports the source module, so unrelated top-level Python statements do not
run and there is no second decorator-driven build lifecycle.

Pass a mapping such as `{"__init__.py": "...", "model.py": "..."}` plus
`entry="model.py"` for a virtual multi-module package. Crabwalk synthesizes missing
package initializers, materializes one immutable snapshot, resolves the internal
graph, and exposes qualified names such as `model.transform`.

This API is a non-executing Python-module boundary, not a capability sandbox for the
Rust toolchain. Declared Cargo dependencies, build scripts, procedural macros,
linkers, and configured tools retain developer permissions. Hosts accepting
untrusted edits must enforce their own allowed declaration, crate, and effect policy
before building. The optional `cancelled` callback is checked between phases and
also terminates an already-running Cargo process tree before raising `CRAB309`.

## Packages

A regular package (`__init__.py` present) or explicitly configured namespace
package is one compilation unit. Crabwalk finds modules containing native
declarations or crate declarations, adds the requested entry module and required
package initializers, and follows supported internal imports and re-exports without
importing Python code. It emits that reachable native graph as one extension.
Unrelated Python-only modules do not block or invalidate native compilation;
mixed-wheel integrity still covers every shipped `.py` and `.pyi` source file.

```text
my_package/
  __init__.py
  math.py
  model.py
```

Declaration cycles are resolved to a fixed point rather than by executing Python
initializers. `import *` follows a literal static `__all__`; without one it follows
Python's leading-underscore export rule over compiler-visible bindings. Dynamic or
malformed `__all__` remains a source-spanned error because executing it would break
the static-analysis contract.

For explicit, bounded project discovery:

```toml
[tool.crabwalk]
packages = ["src/my_package"]
python-boundaries = "warn"
source-locked = true
extra-files = ["native/schema.proto"]
extra-env = ["MY_NATIVE_MODE"]
wheel-include = ["templates/**/*.html"]
```

Valid boundary policies are `allow`, `warn`, and `deny`. Unknown configuration
keys are errors rather than silently ignored. Configured paths must remain inside
the project and contain Python sources. A project-directory source command resolves
the package only when exactly one entry is configured; otherwise select a package
or source file explicitly, optionally with `--project`. The PEP 517 backend compiles
every configured top-level package into the same distribution.

`--project` selects configuration and containment policy; it does not change the
base directory of the positional source argument. Relative source paths resolve
from the current working directory. When checking an out-of-tree project copy,
change into that project root or pass an absolute source path beneath it.

`source-locked = true` makes decorator-driven source imports compile with Cargo's
locked policy. Without it, source imports use the normal lock-maintaining policy
and intentionally do not reuse a CLI artifact built with `--locked`. Function
`__crabwalk__` metadata and `crabwalk inspect` report the effective Cargo policy.

## Build an application with ordinary Python tooling

Add static PEP 621 metadata and select Crabwalk's backend:

```toml
[build-system]
requires = ["crabwalk-lang>=1.1,<1.2"]
build-backend = "crabwalk.build_backend"

[project]
name = "native-application"
version = "1.0.0"
readme = "README.md"
license = "Apache-2.0"
dependencies = ["fastapi>=0.116"]

[project.scripts]
native-application = "my_package.cli:main"

[tool.crabwalk]
packages = ["src/my_package", "src/company_namespace"]
```

`python -m build`, `pip wheel .`, and `pip install .` preserve dependencies,
extras, scripts, arbitrary entry-point groups, package data allowlists, readme,
license files, and project URLs. The produced wheel embeds one verified extension
per configured package and installs/runs without a Rust toolchain. The sdist is
deterministic and contains every declared native/metadata input.

## Where state goes

```text
.crabwalk/
  generated/       deterministic Cargo/Rust/IR/source-map inputs
  target/          shared Cargo target output
  cache/artifacts/ hash-verified loadable extensions and access markers
  locks/           interprocess build, load, and prune locks

crabwalk-locks/
  ...Cargo.lock    stable application dependency resolution
```

`.crabwalk/` is disposable. `crabwalk-locks/` is not disposable when a project
depends on crates and expects locked/offline reproducibility.

Normal builds may update and atomically persist Cargo's lock resolution. Use
`--locked` when any lock modification must fail. Declare build-script inputs that
Crabwalk cannot infer with `extra-files` and `extra-env`; wheel package data beyond
Python/type files requires `wheel-include`.

Continue with [[Crabwalk Language Reference]], [[Crabwalk Ownership and Domain Types]],
and [[Crabwalk Tooling Packaging and Cache]].
