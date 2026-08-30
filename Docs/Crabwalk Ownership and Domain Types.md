---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-30
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
types/ranges before native construction. `Vec[u8]` is byte-oriented: construction
accepts a checked byte sequence and `to_python()` returns Python `bytes`. Other
supported vectors return a newly allocated Python list.

The 1.1 bulk extractor accepts recursive shapes such as `Vec[Row]`,
`Vec[Tuple[...]]`, `Vec[Option[T]]`, `Vec[Vec[T]]`, and nested domains from either
compiled handles or checked Python mappings/sequences. It validates the complete
shape in Python, then performs one native construction call rather than one PyO3
call per row. `value.boundary_telemetry` reports validation/native time, modeled
container/domain allocations, values, bytes copied, clones, and crossings;
`function.call_with_telemetry(...)` returns the function result and the same
phase-separated call record. These are explicit modeled boundary operations, not
samples from the allocator.

Construction is an explicit, allocating boundary proportional to the complete
input shape; a native function's warm execution timing does not include that cost
unless the application measures construction and the call together. For repeated
read-only work, construct one `Ref`-compatible handle on its owner thread and reuse
it when the application can define safe invalidation. Small or one-shot inputs may
remain faster in ordinary Python even when the native kernel itself is faster.

## Borrowing existing numeric buffers

When the application already owns compatible numeric buffer storage, a bounded
`rust.Buffer[T]` parameter avoids the allocating `rust.from_python(..., Vec[T])`
step:

```python
from array import array
from crabwalk import rust

@rust.fn
def total(values: rust.Buffer[rust.f64]) -> rust.f64:
    result: rust.f64 = 0.0
    for value in values.iter():
        result += value
    return result

durations = array("d", [1.25, 2.5, 3.75])
view = memoryview(durations).toreadonly()
print(total(view))
```

This is a read-only, one-dimensional, C-contiguous, native-endian, primitive
numeric input boundary. The generated wrapper keeps PyO3's buffer lease alive for
the complete native call and reads through alias-aware cells; it does not cast the
exporter to an immutable Rust slice and does not copy its elements. The GIL remains
held, the view cannot escape the call, and `par_iter` is unavailable. Use
`function.__crabwalk__["parameter_boundaries"]` or `crabwalk inspect` to verify
the `BorrowedBuffer`/no-element-copy policy. Empty compatible exporters are valid:
the wrapper represents them with Rust's canonical empty slice and never
dereferences their data pointer.

Creating an `array`, NumPy array, or other backing store may itself allocate. This
boundary removes only the redundant Python-buffer-to-Rust-`Vec` construction. A
small kernel that returns a large Python container can still be dominated by call
and output conversion costs; benchmark the full production path.

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

All ownership arguments are validated before any `Owned` slot is taken. If a later
`Owned`, `Ref`, or `Mut` argument has already moved, the call is rejected and every
earlier valid handle remains live. Generated Rust repeats this preflight even though
the Python wrapper normally provides the richer source-linked diagnostic first.

Borrowed returns and retained Python-crossing lifetimes are rejected. Ordinary
`Owned`/`Ref`/`Mut` handles are thread-affine: access from another Python thread
raises `CrabwalkThreadError`. They are also excluded from `rust.async_call`.

## Immutable shared handles

`rust.Shared[T]` is the explicit exception to thread affinity. Calling `freeze()`
on an eligible owned handle consumes it and returns a frozen Python handle backed
by Rust `Arc<T>`; calling `freeze()` on that shared handle cheaply clones the Arc.
Only compiler-proven immutable `Send + Sync` payloads are accepted. Mutation,
`Rc`, `RefCell`, `Mut`, retained borrows, and other non-shareable shapes are
rejected before rustc.

```python
@rust.fn
def total(rows: rust.Shared[rust.Vec[Row]]) -> rust.u64:
    return rows.par_iter().map(lambda row: row.value).sum()

owned = rust.Vec[Row]([{"value": 1}, {"value": 2}])
shared = owned.freeze()
alias = shared.freeze()
```

The wrapper clones the Arc before an eligible GIL-detached call, so many Python
threads and Rayon workers can read the same immutable allocation. The compilation
fingerprint remains part of the handle identity; old handles survive reload/GC for
old compiled functions and are rejected by a different compilation.

## Owned UTF-8 text columns

`rust.TextColumn(data, offsets)` packs many immutable strings into one owned
`Vec[u8]` plus an offset table. Construction validates a zero start, monotonic
in-range offsets, final byte length, and UTF-8 for every segment before crossing
once into native storage. Native functions accept `Ref[TextColumn]`,
`Owned[TextColumn]`, or `Shared[TextColumn]` and can use `len`, `get`,
`contains_at`, and `total_bytes` without creating one Python string wrapper per
row. `to_python()` deliberately returns `{"data": bytes, "offsets": list[int]}`
so the packed representation remains observable.

## Structs

```python
serde = rust.crate("serde", version="1", features=["derive"])

@rust.struct(derive=[serde.Serialize, serde.Deserialize])
class User:
    id: rust.u64
    name: rust.String
```

Supported fields are primitives, `String`, recursively supported `Vec`, `Option`,
and tuple values, and nested generated structs/enums at any supported child
position. For example, `Vec[Term]`, `Option[Metadata]`, and
`Tuple[Term, Metadata]` may all be fields of one generated record. Direct recursive
type cycles remain invalid Rust, and `Str` fields/ownership annotations are
rejected because the required retained lifetime cannot be expressed. A generated
struct marker creates a Rust-backed object:

```python
user = User(id=42, name="Alice")
print(user.id)
user.name = "Bob"
print(user.to_python())  # {'id': 42, 'name': 'Bob'}
```

Constructors and field setters use the same exact boundary codec as exported
functions. For example, `User(id=True, name="Alice")` is rejected because a Python
`bool` is not an exact integer boundary value. Field getters and `to_python()` use
the matching output policy, including the `Vec[u8]` to `bytes` rule.

Passing the object to a native function requires `rust.Ref[User]`,
`rust.Mut[User]`, `rust.Owned[User]`, or eligible immutable `rust.Shared[User]`.
An exported factory can return `rust.Owned[User]`; the result is the same
move-aware native handle, not an implicit dictionary copy.

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

Struct and enum markers are tied to the compilation fingerprint that created them.
After a source reload changes a domain schema, a retained old marker continues to
construct the old native class with the old schema; new markers use the new class.
Passing either value across compilation identities remains an explicit error.

Payload patterns accept captures, `_`, nested domain patterns, tuple/rest forms,
or-patterns, ranges, at-bindings, and typed guards. rustc remains the exhaustiveness
authority; a missing variant is a `CRAB301` error mapped to the original Python
`match` span.

## Derives

`derive=[crate.Path, ...]` is a narrow, static derive surface. Each path must come
from a declared crate. The Serde example in `tests/integration/test_native_structs.py`
proves Serialize/Deserialize-backed JSON through `serde_json`; arbitrary macros,
traits, impl blocks, and raw Rust injection are not enabled by this feature.
