---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-22
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

## Install for development

```powershell
python -m pip install -e .
crabwalk doctor
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

## Packages

A regular package (`__init__.py` present) is one compilation unit. Crabwalk
statically analyzes every ordinary `.py` file beneath that package without
importing it, resolves supported relative imports and re-exports, then emits one
extension. Runtime decorators in all package modules bind to that same artifact.

```text
my_package/
  __init__.py
  math.py
  model.py
```

Namespace packages are not currently compilation units. Pass a file or regular
package directory to the CLI. Internal import cycles and `import *` are rejected
in the alpha compiler; use an acyclic graph and explicit imported names.

For explicit, bounded project discovery:

```toml
[tool.crabwalk]
packages = ["src/my_package"]
python-boundaries = "warn"
extra-files = ["native/schema.proto"]
extra-env = ["MY_NATIVE_MODE"]
wheel-include = ["templates/**/*.html"]
```

Valid boundary policies are `allow`, `warn`, and `deny`. Unknown configuration
keys are errors rather than silently ignored. Configured paths must remain inside
the project and contain `__init__.py`. A project-directory command resolves the
package only when exactly one entry is configured; otherwise select a package or
source file explicitly, optionally with `--project`.

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
