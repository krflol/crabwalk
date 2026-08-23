---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-22
tags:
  - project/crabwalk
  - docs/ownership
---

# Crabwalk Ownership and Domain Types

## Explicit owned values

An allocating Python-to-`Vec` conversion is visible:

```python
from crabwalk import rust

@rust.fn
def total(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()

@rust.fn
def append(values: rust.Mut[rust.Vec[rust.u64]], value: rust.u64) -> None:
    values.push(value)

@rust.fn
def consume(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()

values = rust.from_python([1, 2, 3], rust.Vec[rust.u64])
print(total(values))
append(values, 4)
print(rust.to_python(values))
print(consume(values))
```

`rust.Vec[T](sequence)` is equivalent explicit construction when the generated
wrapper for that concrete `T` is loaded. `rust.Vec(sequence)` infers homogeneous
`bool`, `i64`, `f64`, or `String`; an empty vector requires an explicit type.
Conversion errors name the failing element index and enforce exact primitive
types/ranges before native construction.

Owned wrapper identity belongs to a compiled module/fingerprint, not merely a Rust
type spelling. When exactly one compatible wrapper is loaded, inferred construction
may use it. If multiple compilations expose the same type, construction raises a
clear ambiguity error instead of choosing the most recently imported module. Bind
the conversion explicitly to a compiled function from the consumer module:

```python
values = rust.from_python(
    [1, 2, 3],
    rust.Vec[rust.u64],
    for_=module_a.consume,
)
```

## Ownership state

- `Ref[T]` creates a shared borrow for one native call.
- `Mut[T]` creates an exclusive mutable borrow for one native call.
- `Owned[T]` takes the value from its Rust-backed Python handle.
- A consumed handle and all Python aliases report `moved == True`.
- Reading, converting, borrowing, or consuming it again raises
  `CrabwalkMoveError`, including the value-creation site, consuming parameter
  definition, Python move-call site, and a `Ref`/`Mut` alternative.
- Overlapping shared/mutable access or reentrant Python access during a mutable
  boundary raises `CrabwalkBorrowError`. Its message identifies the conflicting
  parameter definitions, call site, and safe signature alternatives.

Python `copy.copy` and `copy.deepcopy` intentionally alias the same ownership
state. There is no implicit deep clone. A value from a different compiled module
fingerprint must be reconstructed explicitly from `value.to_python()`.

Borrowed returns and retained Python-crossing lifetimes are rejected. Ownership
handles are thread-affine: access from another Python thread raises
`CrabwalkThreadError`, even when the underlying Rust type might implement `Send`.
They are also excluded from `rust.async_call`. A future explicit `Send`/`Sync`
surface may relax this only with matching lifecycle tests.

## Structs

```python
serde = rust.crate("serde", version="1", features=["derive"])

@rust.struct(derive=[serde.Serialize, serde.Deserialize])
class User:
    id: rust.u64
    name: rust.String
```

Supported fields are primitives, `String`, and recursively supported `Vec` or
`Option` values. `Str` fields and ownership annotations are rejected because the
required retained lifetime cannot be expressed. A generated struct marker creates
a Rust-backed object:

```python
user = User(id=42, name="Alice")
print(user.id)
user.name = "Bob"
print(user.to_python())  # {'id': 42, 'name': 'Bob'}
```

Passing the object to a native function requires `rust.Ref[User]`,
`rust.Mut[User]`, or `rust.Owned[User]`. Domain values are not implicitly copied
through exported parameters or returns.

Domain declarations have a checked Python namespace contract. Fields cannot reuse
owned-handle members such as `moved`, `rust_type`, `to_python`, or internal wrapper
slots because Python attribute lookup would otherwise bypass the native field.
Crabwalk reports these declarations as `CRAB210`; ordinary neighboring names such
as `name` remain available.

## Enums and match

```python
@rust.enum
class Status:
    Pending = rust.variant()
    Running = rust.variant(progress=rust.u8)
    Failed = rust.variant(rust.String)

@rust.fn
def score(status: rust.Ref[Status]) -> rust.u8:
    match status:
        case Status.Pending:
            return 0
        case Status.Running(progress=value):
            return value
        case Status.Failed(_):
            return 255
```

Enums support unit, record, and tuple payload variants. Python constructors are
`Status.Pending()`, `Status.Running(progress=7)`, and `Status.Failed("message")`.
`to_python()` produces a dictionary with `variant` and payload fields.

Variant names also cannot shadow the `RustType` marker API (for example `name`,
`variants`, or `rust_key`), and payload fields follow the same owned-handle rule as
struct fields. These restrictions keep constructor and field lookup unambiguous.

Payload patterns accept captures, `_`, nested domain patterns, tuple/rest forms,
or-patterns, ranges, at-bindings, and typed guards. rustc remains the exhaustiveness
authority; a missing variant is a `CRAB301` error mapped to the original Python
`match` span.

## Derives

`derive=[crate.Path, ...]` is a narrow, static derive surface. Each path must come
from a declared crate. The Serde example in `tests/integration/test_native_structs.py`
proves Serialize/Deserialize-backed JSON through `serde_json`; arbitrary macros,
traits, impl blocks, and raw Rust injection are not enabled by this feature.
