# Crabwalk

> [!info] Implementation planning
> Start at [[Crabwalk Project Hub]] for the scoped product contract, architecture plan, dependency-aware roadmap, verification gates, risks, and decision queue.

## Rust as a Python Semantic Layer

**Status:** Guiding architecture / pre-design  
**Project name:** Crabwalk  
**Primary package:** `crabwalk`  
**Primary user-facing capability:** `rust`  
**Canonical import:**

```python
from crabwalk import rust
```

**Primary objective:** Bring Rust's compiler, type system, ownership model, ecosystem, and native execution into ordinary Python without creating a new programming language.

---

## 1. Vision

Crabwalk treats **Python as the host language and module system** while allowing developers to opt selected portions of a program into **real Rust semantics and real Rust compilation**.

The mental model is closer to React's relationship with JavaScript than to a Python-to-Rust rewrite tool:

> Python remains Python. Crabwalk makes Rust an opt-in semantic and execution layer inside it.

A user should be able to write:

```python
from crabwalk import rust


@rust.fn
def add(a: rust.i64, b: rust.i64) -> rust.i64:
    return a + b
```

and receive a normal Python-callable function whose implementation is compiled by `rustc` and executes as native Rust.

Crabwalk's purpose is **not merely acceleration**.

Its primary value is access to:

- Rust's compile-time type checking
    
- ownership and borrowing
    
- memory safety
    
- `Option`
    
- `Result`
    
- enums and exhaustive matching
    
- traits
    
- `Send` / `Sync`
    
- Rust standard-library types
    
- crates.io ecosystem
    
- native execution
    
- Rust tooling and optimizer
    
- explicit Python/Rust boundaries
    

Performance is an important consequence, but not the fundamental abstraction.

---

# 2. Core Design Principle

## Rust where possible. Python where necessary.

Within Crabwalk Rust-enabled code, execution should remain in Rust **to the maximum practical extent**.

```python
from crabwalk import rust


@rust.fn
def hello():
    print("hello from Python")
    rust.println("hello from Rust")
```

The function remains compiled Rust.

Calling:

```python
print(...)
```

creates an explicit Python runtime boundary.

Calling:

```python
rust.println(...)
```

lowers directly to native Rust.

Conceptually:

```rust
fn hello(py: Python<'_>) {
    // Python boundary.
    py.import("builtins")?
        .getattr("print")?
        .call1(("hello from Python",))?;

    // Native Rust.
    println!("hello from Rust");
}
```

Crabwalk should expose these boundaries clearly through diagnostics, IDE tooling, generated-source inspection, and performance analysis.

---

# 3. What Crabwalk Is Not

Crabwalk is **not a new programming language**.

Source remains ordinary:

```text
.py
```

and must remain valid Python syntax.

Crabwalk should not require constructs such as:

```text
pub fn
let
foo!
```

unless represented through valid Python grammar.

Crabwalk is also **not a universal Python-to-Rust transpiler**.

The developer explicitly opts into Rust semantics:

```python
@rust.fn
def calculate(...):
    ...
```

That gives Crabwalk permission to reject constructs which cannot sensibly be lowered into Rust.

Nor should Crabwalk behave as a hidden accelerator.

Rust participation should be intentional and visible.

---

# 4. Fundamental Execution Model

```text
Python application
       │
       │
       ▼
┌──────────────────────────┐
│        Crabwalk          │
│                          │
│ Python AST analysis      │
│ Rust symbol resolution   │
│ semantic lowering        │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│       Rust Island        │
│                          │
│ types                    │
│ ownership                │
│ borrowing                │
│ traits                   │
│ Result / Option          │
│ native execution         │
│                          │
│ compiled by rustc        │
└────────────┬─────────────┘
             │
             │ PyO3 boundary
             ▼
          Python
```

A Rust island may call Python, but doing so is an explicit interoperability boundary.

---

# 5. Canonical Import Model

Crabwalk itself is the Python package:

```python
import crabwalk
```

but ordinary application code should normally use:

```python
from crabwalk import rust
```

This establishes a useful distinction:

```text
crabwalk
    project/compiler/runtime infrastructure

rust
    user-facing Rust semantic namespace
```

Therefore:

```python
from crabwalk import rust
```

should be the canonical form used throughout documentation.

This also leaves room for future Crabwalk capabilities:

```python
from crabwalk import rust
from crabwalk import diagnostics
from crabwalk import build
```

without crowding the `rust` semantic namespace.

---

# 6. Strictness Principle

`@rust.fn` must mean something.

```python
from crabwalk import rust


@rust.fn
def calculate(...):
    ...
```

means:

> Compile this function as Rust.

If Crabwalk cannot lower the function, compilation fails.

There should be **no silent fallback to interpreted Python**.

Example:

```text
CRAB102 Unsupported construct in @rust.fn

    app.py:18

    value = some_dynamic_python_magic()
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^

This expression cannot be lowered to Rust.

Possible solutions:
  • call it explicitly through the Python boundary
  • move this operation outside @rust.fn
  • use a supported Rust equivalent
```

Crabwalk-specific diagnostics should use a project namespace such as:

```text
CRAB###
```

while preserving underlying Rust error codes where relevant.

---

# 7. Python Calls Inside Rust Functions

Python remains callable:

```python
import requests

from crabwalk import rust


@rust.fn
def fetch():
    response = requests.get("https://example.com")
```

Crabwalk recognizes `requests` as a Python module.

Therefore:

```python
requests.get(...)
```

becomes a PyO3 boundary crossing.

The surrounding function remains native Rust.

Tooling should surface this:

```text
CRAB201 Python boundary crossing

    response = requests.get(url)
               ^^^^^^^^^^^^

This operation enters the Python runtime.
```

By contrast, a declared Rust crate such as `reqwest` should remain native.

---

# 8. Python Owns the Module System

A central Crabwalk rule is:

> **Crabwalk does not recreate Rust's module system. Rust participates in Python's module system.**

Python already provides:

- packages
    
- modules
    
- relative imports
    
- nested namespaces
    
- initialization
    
- re-exports
    
- public façades
    

Crabwalk should build upon those mechanisms rather than replacing them.

Example:

```text
myapp/
├── __init__.py
├── app.py
├── models.py
├── data/
│   ├── __init__.py
│   └── codec.py
└── network/
    ├── __init__.py
    └── client.py
```

This structure remains authoritative.

---

# 9. `__init__.py` as Rust Manifest and Module Façade

A package's `__init__.py` can serve approximately the combined role of:

```text
Cargo dependency declarations
        +
module façade
        +
pub-use style re-exports
```

Example:

```python
# myapp/__init__.py

from crabwalk import rust


serde = rust.crate(
    "serde",
    version="1",
    features=["derive"],
)

serde_json = rust.crate(
    "serde_json",
    version="1",
)

rayon = rust.crate(
    "rayon",
    version="1",
)
```

Application code then uses normal Python imports:

```python
from . import serde, serde_json
```

Crates belong to the application's package namespace.

They do **not** become global properties such as:

```python
rust.serde = ...
```

---

# 10. Crate Declaration

The explicit initial API should be:

```python
from crabwalk import rust


serde = rust.crate(
    "serde",
    version="1",
    features=["derive"],
)
```

Crabwalk lowers dependency declarations into generated Cargo configuration.

Equivalent:

```toml
serde = {
    version = "1",
    features = ["derive"]
}
```

Other forms:

```python
regex = rust.crate(
    "regex",
    version="1",
)
```

```python
tokio = rust.crate(
    "tokio",
    version="1",
    features=[
        "rt-multi-thread",
        "macros",
        "net",
    ],
)
```

```python
json = rust.crate(
    "serde_json",
    version="1",
)
```

```python
engine = rust.crate(
    "engine",
    path="../engine",
)
```

```python
foo = rust.crate(
    "foo",
    git="https://github.com/example/foo",
    rev="...",
)
```

Cargo remains the actual dependency resolver.

Crabwalk should expose it rather than recreate it.

---

# 11. Optional Crate Shorthand

A later ergonomic form may allow:

```python
serde = rust.crate(
    "1",
    features=["derive"],
)
```

with Crabwalk inferring the crate name from:

```python
serde =
```

However, explicit crate naming should come first.

Compiler magic should only be added where it clearly improves the development experience.

---

# 12. Rust Standard Library

Rust's standard library should appear under the semantic namespace exported by Crabwalk:

```python
from crabwalk import rust

from crabwalk.rust.std.collections import HashMap
from crabwalk.rust.std.sync import Arc
from crabwalk.rust.std.time import Duration
```

However, the preferred ergonomic model may also support attributes directly from the imported `rust` namespace:

```python
from crabwalk import rust


HashMap = rust.std.collections.HashMap
```

The exact import-hook mechanics remain implementation detail.

What matters semantically is that these symbols resolve to actual Rust paths:

```text
std::collections::HashMap
std::sync::Arc
std::time::Duration
```

rather than Python reimplementations.

---

# 13. Package-Local Rust Crates

After:

```python
# __init__.py

from crabwalk import rust


serde_json = rust.crate(
    "serde_json",
    version="1",
)
```

another package module uses:

```python
from . import serde_json
```

Crabwalk's semantic analysis determines that this symbol represents a Rust crate.

Therefore:

```python
serde_json.to_string(value)
```

can lower directly into Rust.

---

# 14. Re-Exports

Ordinary Python re-exports remain authoritative.

```python
# models.py

from crabwalk import rust


@rust.struct
class User:
    id: rust.u64
    name: rust.String
```

Then:

```python
# __init__.py

from .models import User
```

allows:

```python
from myapp import User
```

This naturally serves the same architectural purpose as a Rust façade such as:

```rust
mod models;

pub use models::User;
```

without introducing a second module system.

---

# 15. Cargo Architecture

Initially:

> **One generated Cargo crate per Crabwalk-enabled Python package/distribution.**

Do not make every Python subpackage into a Cargo crate.

For:

```text
myapp/
    __init__.py
    data/
        __init__.py
    network/
        __init__.py
```

Crabwalk might generate:

```text
.crabwalk/
└── generated/
    └── myapp/
        ├── Cargo.toml
        └── src/
            ├── lib.rs
            ├── data.rs
            └── network.rs
```

This keeps Python's package hierarchy while avoiding premature Cargo workspace complexity.

---

# 16. Primitive Rust Types

The `rust` namespace exported from Crabwalk should expose:

```python
rust.i8
rust.i16
rust.i32
rust.i64
rust.i128

rust.u8
rust.u16
rust.u32
rust.u64
rust.u128

rust.f32
rust.f64

rust.bool
rust.char
```

Example:

```python
from crabwalk import rust


@rust.fn
def multiply(
    x: rust.i64,
    y: rust.i64,
) -> rust.i64:
    return x * y
```

These lower directly to corresponding Rust primitive types.

---

# 17. Core Semantic Types

Early support should include:

```python
rust.String
rust.Str

rust.Vec[T]

rust.Option[T]
rust.Result[T, E]

rust.Box[T]
rust.Rc[T]
rust.Arc[T]
```

Later:

```python
rust.HashMap[K, V]
rust.HashSet[T]
```

although standard-library imports may remain preferable for less fundamental types.

---

# 18. Ownership and Borrowing

Crabwalk's real differentiation begins with explicit Rust ownership semantics.

Proposed annotations:

```python
rust.Owned[T]
rust.Ref[T]
rust.Mut[T]
```

Shared borrow:

```python
@rust.fn
def total(
    values: rust.Ref[rust.Vec[rust.i64]],
) -> rust.i64:
    ...
```

approximately:

```rust
fn total(values: &Vec<i64>) -> i64
```

Mutable borrow:

```python
@rust.fn
def append(
    values: rust.Mut[rust.Vec[rust.i64]],
    value: rust.i64,
):
    values.push(value)
```

approximately:

```rust
fn append(values: &mut Vec<i64>, value: i64)
```

Owned value:

```python
@rust.fn
def consume(
    values: rust.Owned[rust.Vec[rust.i64]],
):
    ...
```

should result in a real Rust move.

Crabwalk should express these constraints as valid Rust and allow `rustc` to validate them.

---

# 19. Rust-Owned Python Objects

```python
from crabwalk import rust


values = rust.Vec([1, 2, 3])
```

should ultimately represent an actual Rust-owned vector surfaced through a controlled Python wrapper.

If:

```python
consume(values)
```

moves the underlying value, later use may produce:

```text
CrabwalkMoveError

`values` was moved into consume()

    consume(values)
            ^^^^^^
```

Static enforcement ends at the Python boundary, so some ownership enforcement necessarily becomes runtime behavior there.

That does not diminish the value of maintaining ownership semantics wherever possible.

---

# 20. Rust Structs

```python
from crabwalk import rust


@rust.struct
class User:
    id: rust.u64
    name: rust.String
```

lowers to actual Rust:

```rust
pub struct User {
    pub id: u64,
    pub name: String,
}
```

Derives may eventually look like:

```python
@rust.struct(
    derive=[
        serde.Serialize,
        serde.Deserialize,
    ]
)
class User:
    id: rust.u64
    name: rust.String
```

---

# 21. Rust Enums

Provisional syntax:

```python
@rust.enum
class Status:
    Pending = rust.variant()
    Running = rust.variant(progress=rust.u8)
    Failed = rust.variant(message=rust.String)
```

Conceptually:

```rust
enum Status {
    Pending,
    Running { progress: u8 },
    Failed { message: String },
}
```

Python pattern matching may provide a natural authoring surface for Rust `match`.

---

# 22. `Option` and `Result`

Rust's explicit absence/error models should survive inside Rust islands.

```python
@rust.fn
def divide(
    x: rust.f64,
    y: rust.f64,
) -> rust.Option[rust.f64]:
    if y == 0:
        return rust.None

    return rust.Some(x / y)
```

Likewise:

```python
@rust.fn
def load(...) -> rust.Result[Config, LoadError]:
    ...
```

Conversion to Python exceptions should occur only at deliberate Python API boundaries.

---

# 23. Traits

Later:

```python
@rust.trait
class Printable:
    def render(self) -> rust.String:
        ...
```

and:

```python
@rust.impl(Printable, for_=User)
class UserPrintable:
    ...
```

should lower to actual Rust trait and impl declarations.

Traits should not block the initial compiler.

---

# 24. Macros

Rust macro syntax is not legal Python syntax.

Crabwalk should therefore allow imported Rust symbols to carry metadata identifying them as macros.

For example:

```python
value = json({
    "name": "Alice",
})
```

where `json` resolves to a Rust macro can lower to:

```rust
let value = json!({
    "name": "Alice",
});
```

The symbol resolver, rather than special Python syntax, determines whether the call represents:

- function
    
- macro
    
- struct
    
- enum
    
- trait
    
- module
    
- constant
    
- type
    

---

# 25. Compiler Architecture

```text
Python source
      │
      ▼
CPython parser / AST
      │
      ▼
Crabwalk semantic analysis
      │
      ├── Python symbols
      ├── Rust symbols
      ├── crate declarations
      ├── Rust types
      └── @rust constructs
      │
      ▼
Rust-oriented IR
      │
      ▼
Rust source generation
      │
      ▼
Generated Cargo project
      │
      ▼
cargo / rustc
      │
      ▼
PyO3 extension
      │
      ▼
Normal Python objects
```

---

# 26. Use Python's Parser

Crabwalk should not implement a custom parser.

Because Crabwalk source remains valid Python:

```python
ast.parse(source)
```

already provides:

- functions
    
- classes
    
- imports
    
- annotations
    
- source locations
    
- expressions
    
- loops
    
- conditionals
    
- pattern matching
    

Crabwalk begins with this AST and adds Rust-aware semantic analysis.

---

# 27. Intermediate Representation

Do not directly stringify Python AST into Rust.

Introduce a semantic IR:

```text
Function
  name
  arguments
  return type
  body

Expression
  Integer
  Float
  BinaryOp
  Call
  Borrow
  Move
  RustSymbol
  PythonBoundaryCall

Statement
  Let
  Assign
  If
  Loop
  Return
```

This gives Crabwalk:

- cleaner testing
    
- source mapping
    
- better diagnostics
    
- easier compiler evolution
    
- explicit language boundaries
    
- future optimization opportunities
    

---

# 28. Generated Rust Must Be Inspectable

Generated source is a feature, not an implementation embarrassment.

Potential CLI:

```bash
crabwalk expand myapp
```

Output:

```text
.crabwalk/
    generated/
        myapp/
            Cargo.toml
            src/
                lib.rs
                models.rs
                codec.rs
```

Potential focused inspection:

```bash
crabwalk show app.py:calculate
```

The user should always be able to inspect what Crabwalk generated.

---

# 29. Compilation and Caching

Crabwalk should fingerprint:

```text
Python source
crate declarations
crate features
Rust compiler version
target triple
Crabwalk version
compiler settings
```

and reuse native artifacts when nothing relevant changed.

Suggested working directory:

```text
.crabwalk/
├── cache/
├── generated/
├── target/
└── metadata/
```

---

# 30. Development and Distribution

Development should approach:

```text
edit
 ↓
import
 ↓
compile changed Rust islands
 ↓
cache
 ↓
execute
```

Distribution should approach:

```text
build wheel
 ↓
native extension included
 ↓
normal Python import
```

Crabwalk should eventually integrate naturally with Python packaging rather than forcing developers to operate Cargo manually.

---

# 31. PyO3

PyO3 should initially provide the interoperability layer for:

- exported functions
    
- Rust-backed classes
    
- Python object conversion
    
- interpreter access
    
- exceptions
    
- module initialization
    
- Rust → Python calls
    

Crabwalk should not recreate the CPython ABI without a compelling measured reason.

---

# 32. Native Means Native

If:

```python
HashMap = rust.std.collections.HashMap
```

and:

```python
@rust.fn
def frequencies(...):
    counts = HashMap()
```

then Crabwalk should generate an actual:

```rust
std::collections::HashMap
```

It should not substitute a Python dictionary.

General rule:

> If the programmer explicitly selects Rust semantics, Crabwalk should generate the corresponding real Rust type or operation whenever possible.

---

# 33. Python Types Are Not Rust Types

Crabwalk must not pretend:

```python
list[int]
```

and:

```python
rust.Vec[rust.i64]
```

mean the same thing.

Likewise:

```python
str
```

and:

```python
rust.String
```

are different semantic commitments.

Explicit Rust types are valuable because they tell Crabwalk that Rust behavior is desired.

---

# 34. Conversion Boundaries

Potential APIs:

```python
rust.from_python(value, rust.Vec[rust.i64])
```

```python
rust.to_python(value)
```

Automatic primitive conversion is reasonable where predictable:

```text
int ↔ compatible Rust integer
float ↔ Rust float
str ↔ String/&str where valid
bytes ↔ Vec<u8>/slice
```

Expensive allocations and conversions should be visible to diagnostics and tooling.

---

# 35. Boundary Classification

Crabwalk should eventually classify operations as:

```text
Native Rust
Conversion boundary
Python runtime boundary
Unsupported
```

Potential inspection:

```bash
crabwalk inspect app.py
```

This may eventually report where Python crossings and data conversions occur.

The exact profiling model can wait, but boundary metadata should exist from the beginning.

---

# 36. Diagnostics

Generated Rust locations should map back to original Python source.

Instead of:

```text
generated/src/app.rs:417
```

the developer should primarily see:

```text
CRAB-BORROW

Cannot mutably borrow `users` while it is already borrowed.

  app.py:24

  current = users[0]
            ----- first borrow

  users.push(new_user)
  ^^^^^^^^^^^^^^^^^^^^ mutable borrow occurs here

rustc: E0502
```

Rust's original error code should remain available.

Crabwalk adds context; it should not hide Rust.

---

# 37. Escape Hatches

Eventually:

```python
rust.use(...)
rust.raw(...)
rust.expr(...)
rust.type(...)
rust.cfg(...)
```

may expose functionality that does not map cleanly onto the high-level Python surface.

These are deliberate escape hatches rather than the normal programming model.

---

# 38. Async

Async should be postponed until the basic semantic model is stable.

Questions include:

- Tokio vs Python event loops
    
- coroutine interoperability
    
- cancellation
    
- runtime ownership
    
- future lifetimes
    
- GIL interactions
    

Eventually Crabwalk should distinguish:

```text
native Rust async
Python async boundary
```

rather than pretending they are the same execution model.

---

# 39. Parallelism

Rust-native parallelism is a major future benefit.

For example, Rayon-backed work inside:

```python
@rust.fn
```

can execute without treating Python's execution model as the computational substrate.

At that point Rust's:

```text
Send
Sync
```

checks become a user-facing safety capability.

---

# 40. Safety Boundary

Crabwalk does not make arbitrary Python memory-safe.

Ordinary Python objects remain governed by Python's:

- aliasing
    
- reference counting
    
- mutability
    
- dynamic object model
    

The accurate guarantee is:

> Within generated safe Rust, Rust's normal safety guarantees apply.

And:

> Rust-owned values may preserve additional ownership constraints when surfaced through controlled Python wrappers.

Unsafe Rust remains unsafe Rust.

Python remains Python.

Crabwalk must keep that boundary explicit.

---

# 41. Unsafe Rust

Do not support authoring unsafe Rust through the Python DSL in the MVP.

Users requiring unsafe functionality can initially write an ordinary Rust crate:

```text
native/
├── Cargo.toml
└── src/
    └── lib.rs
```

and consume it:

```python
native = rust.crate(
    "my_native",
    path="./native",
)
```

Later we may consider:

```python
with rust.unsafe:
    ...
```

or:

```python
@rust.unsafe_fn
```

but unsafe deserves separate design work.

---

# 42. Example Crabwalk Package

```text
example/
├── __init__.py
├── app.py
├── model.py
└── codec.py
```

## `__init__.py`

```python
from crabwalk import rust


serde = rust.crate(
    "serde",
    version="1",
    features=["derive"],
)

serde_json = rust.crate(
    "serde_json",
    version="1",
)
```

## `model.py`

```python
from crabwalk import rust

from . import serde


@rust.struct(
    derive=[
        serde.Serialize,
        serde.Deserialize,
    ]
)
class User:
    id: rust.u64
    name: rust.String
```

## `codec.py`

```python
from crabwalk import rust

from . import serde_json
from .model import User


@rust.fn
def encode(
    user: rust.Ref[User],
) -> rust.String:
    return serde_json.to_string(user)
```

## `app.py`

```python
from .codec import encode
from .model import User


user = User(
    id=42,
    name="Alice",
)

print(encode(user))
```

From the application's perspective:

> This is Python.

From Crabwalk's perspective:

> `User` and `encode` are Rust.

Both should be true.

---

# 43. MVP

Initial support should focus on:

- `from crabwalk import rust`
    
- `@rust.fn`
    
- Rust integer types
    
- Rust floating-point types
    
- `bool`
    
- `String`
    
- `Vec[T]`
    
- `Option[T]`
    
- basic `Result[T, E]`
    
- arguments
    
- return values
    
- local variables
    
- arithmetic
    
- comparison
    
- `if`
    
- `else`
    
- `for`
    
- `while`
    
- function calls
    
- Rust standard-library symbols
    
- declared crate functions
    
- explicit Python runtime calls
    
- primitive Python/Rust conversion
    

Potentially:

- basic `@rust.struct`
    

if implementation cost does not distract from proving the compiler pipeline.

---

# 44. First Compiler Milestone

```python
from crabwalk import rust


@rust.fn
def fibonacci(n: rust.u64) -> rust.u64:
    if n <= 1:
        return n

    return fibonacci(n - 1) + fibonacci(n - 2)


print(fibonacci(40))
```

Pipeline:

```text
Python AST
   ↓
Crabwalk semantic analyzer
   ↓
Rust IR
   ↓
generated Rust
   ↓
cargo / rustc
   ↓
PyO3 extension
   ↓
native Python-callable fibonacci()
```

If this works cleanly, Crabwalk's fundamental architecture is proven.

---

# 45. Second Milestone: crates.io

```python
# __init__.py

from crabwalk import rust


regex = rust.crate(
    "regex",
    version="1",
)
```

Then:

```python
from crabwalk import rust

from . import regex


@rust.fn
def contains_number(
    value: rust.Str,
) -> rust.bool:
    expression = regex.Regex.new(r"\d+")
    return expression.is_match(value)
```

The milestone is:

> An ordinary crates.io dependency can participate naturally in a Python-authored Rust island.

That validates the ecosystem model.

---

# 46. Third Milestone: Ownership

Implement:

```python
rust.Vec
rust.String
rust.Option
rust.Result

rust.Ref
rust.Mut
rust.Owned
```

At this stage Crabwalk begins delivering the semantic safety value that motivated the project rather than simply compiling Python-shaped code natively.

---

# 47. Fourth Milestone: Domain Types

Implement:

```python
@rust.struct
@rust.enum
```

This enables:

- Serde models
    
- state machines
    
- richer crate integration
    
- typed domain APIs
    
- meaningful Rust-owned objects
    

---

# 48. Fifth Milestone: Concurrency

After semantic stability:

- Rayon
    
- native threads
    
- `Send`
    
- `Sync`
    
- Tokio
    
- Python coroutine interoperability
    

Concurrency should build upon Crabwalk's semantic foundation rather than being bolted on as a performance feature.

---

# 49. Development Priorities

When tradeoffs arise:

1. Semantic correctness
    
2. Predictable behavior
    
3. Real Rust compilation
    
4. Clear Python/Rust boundaries
    
5. Useful diagnostics
    
6. Pythonic ergonomics
    
7. Performance
    
8. Syntax convenience
    

Clever syntax should never outrank understandable semantics.

---

# 50. Crabwalk Architectural Rules

### Rule 1

**Source remains valid Python.**

### Rule 2

**The canonical Rust namespace is:**

```python
from crabwalk import rust
```

### Rule 3

**Python owns package and module structure.**

### Rule 4

**Rust owns Rust semantics.**

Generate Rust and let `rustc` perform Rust's correctness analysis.

### Rule 5

**`@rust.fn` compiles to Rust or fails.**

No silent Python fallback.

### Rule 6

**Calling Python from Rust is legal but visible.**

### Rule 7

**Rust types represent real Rust semantic choices.**

### Rule 8

**Use ordinary Python imports whenever possible.**

### Rule 9

**Use Cargo as the Rust dependency engine.**

### Rule 10

**Generated Rust remains inspectable.**

### Rule 11

**Prefer safe generated Rust.**

### Rule 12

**Performance comes primarily from staying in Rust.**

### Rule 13

**Existing Rust crates are first-class citizens.**

### Rule 14

**Crabwalk should orchestrate Rust rather than reimplement Rust.**

---

# 51. Product Feeling

The intended authoring experience is:

```python
from crabwalk import rust

from . import serde_json


@rust.fn
def encode(value: rust.Ref[Model]) -> rust.String:
    return serde_json.to_string(value)
```

The developer should simultaneously feel:

> I'm writing a Python application.

and:

> This code is executing as Rust.

That duality is Crabwalk.

---

# 52. Guiding Summary

```text
Python syntax
+
Python package/module system
+
Crabwalk semantic analysis
+
explicit Rust types
+
Cargo crate declarations
+
generated real Rust
+
rustc
+
PyO3
=
Crabwalk
```

Crabwalk should not erase the Python/Rust boundary.

It should make that boundary:

- easy to cross
    
- cheap where possible
    
- visible when crossed
    
- explicit where safety depends on it
    

The central implementation philosophy is:

> **Do as little ourselves as possible. Express the programmer's intent as real Rust, then let Rust perform the checking, optimization, ownership analysis, ecosystem integration, and native execution it already does exceptionally well.**

And the shortest description of Crabwalk is:

> **Python outside. Rust inside wherever we can keep it there.**
