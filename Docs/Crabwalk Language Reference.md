---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-22
tags:
  - project/crabwalk
  - docs/language
---

# Crabwalk Language Reference

## Declaration contract

- Use exactly `from crabwalk import rust`; namespace aliases are rejected.
- `@rust.fn` exports a module-level synchronous function through Python's ABI.
- `@rust.async_fn` marks a native-only `async def`; an exported function enters it
  explicitly with `rust.block_on(...)`.
- `@rust.generic(...)`, `@rust.method(...)`, `@rust.impl(...)`, and
  `@rust.operator(..., name="add")` declare native-only helpers that are called by
  exported functions. At ordinary Python runtime these names are metadata-bearing
  sentinels and raise instead of interpreting their original Python bodies.
- Every parameter has a supported Rust annotation. Value-returning functions
  have an explicit return annotation; a unit function may use `-> None` or omit it.
- Parameters are required positional parameters. Defaults, variadics,
  positional-only markers, and keyword-only parameters are rejected.
- Calls from Python are positional-only and arity checked.

## Boundary types

| Source type | Rust type | Exported Python behavior |
|---|---|---|
| `rust.i8` … `rust.i128` | matching signed integer | exact `int`, checked range; `bool` rejected |
| `rust.u8` … `rust.u128`, `rust.usize` | matching unsigned integer | exact nonnegative `int`, checked range |
| `rust.f32`, `rust.f64` | matching float | `int`/`float`, `bool` rejected; finite f32 range checked |
| `rust.bool` | `bool` | exact Python `bool` only |
| `rust.String` | `String` | allocating UTF-8 copy |
| `rust.Str` | `&str` | call-scoped Python string borrow; cannot be returned |
| `rust.Option[T]` | `Option<T>` | `None` or the supported conversion for `T` |
| `rust.Result[T, E]` | `Result<T, E>` | exported `Ok` converts `T`; `Err` raises `CrabwalkRustError` |
| `rust.Tuple[T, ...]` | fixed Rust tuple | recursively checked Python tuple when every element is boundary-safe |
| `None` return | `()` | Python `None` |

Bare `Vec` parameters are rejected because they would hide an allocating input
conversion. Use an ownership annotation and `rust.from_python`; see
[[Crabwalk Ownership and Domain Types]]. A supported `Vec[T]` return converts to a
new Python list at the explicit output boundary. Generated domain parameters
likewise require `Owned`, `Ref`, or `Mut`.

## Statements

Supported:

- `return`, local assignment, annotated locals, rebinding, and numeric augmented
  assignment;
- `if`/`else` with `rust.bool` conditions;
- `while`, `break`, and `continue`;
- `for name in range(stop)` and `range(start, stop)` for typed integer ranges;
- `for name in iterator` and tuple targets such as `for index, value in iterator`;
- call expression statements, `pass`, and typed `match` over primitives, tuples,
  Option, structs, and enums.

Definite assignment and compatible rebinding are checked before code generation.
Names written repeatedly become `let mut`; one-write locals remain immutable.

Rejected include nested Python declarations, comprehensions, generators,
`try`/`raise`/`with`, dynamic imports, globals/nonlocals, and `yield`. Lambdas are
accepted only in typed iterator, thread, async, and thread-pool positions. `await`
is accepted only inside `@rust.async_fn`. Python container literals are limited to
typed tuples/arrays and the explicit `rust.Vec([...])` constructor.

## Expressions and semantics

- Integer, float, bool, string, and context-typed `None` literals.
- Numeric `+`, `-`, `*`, `/`, `%`; Rust typed division is intentional.
- Unary `+`, `-`, and bool `not`.
- `==`, `!=`, `<`, `<=`, `>`, `>=`; chained comparisons are rejected.
- Bool-only `and`/`or`; Python truthiness and operand-return semantics do not apply.
- Calls between generated functions remain direct Rust calls, including recursion.
- Supported crate paths and the versioned standard method subset.
- Tuple/array construction, destructuring, and indexing.
- Struct construction/field access/field assignment; enum construction and nested
  domain payloads.
- Inherent method calls, object-safe trait dispatch through `Box<dyn Trait>`, and
  fully qualified shared trait calls through `rust.trait_call`.
- Typed closures in accepted adapter positions and native futures inside
  `@rust.async_fn`.
- Domain `+` only when a visible `@rust.operator(Type, name="add")`
  implementation defines the Rust `Add<Rhs>` output.

Release builds retain overflow checks. A Rust panic is caught at the ABI and
raised as `CrabwalkPanicError`; it never unwinds into Python.

## Standard method subset

| Receiver | Methods |
|---|---|
| `Vec[T]` | `push`, `pop`, `len`, `is_empty`, `iter`, `iter_ref`; `par_iter` with declared Rayon; numeric teaching intrinsic `split_at_mut_sum` |
| `Iterator[T]` | `map`, `filter`, `sum`, `count`, `collect_vec`, `copied` where the item contract permits |
| `String`, `Str` | `len`, `is_empty`, `lines`, `contains`, `starts_with`, `ends_with`, `replace`, `find`; owned String also `as_str`, `push_str`, `to_lowercase` |
| `Option[T]` | `is_some`, `is_none`, `unwrap`, `expect`, `unwrap_or` |
| `Result[T, E]` | `is_ok`, `is_err`, `unwrap`, `expect`, `unwrap_or` |
| `HashMap[K, V]` | `insert`, `contains_key`, `remove`, `get_or`, `entry_or_insert`, numeric `add`, `len`, `is_empty` |
| `Box`, `Rc`, `RefCell` | focused construction, copy dereference/count/interior-mutation operations used by the Book suite |
| `Arc<Mutex<T>>` | `clone`, `strong_count`, numeric `add_locked`, `get_locked` |
| `Sender`, `Receiver`, `ThreadHandle` | `send`, `recv`, `recv_async`, `join` |
| `TcpListener` | `local_port`, bounded `serve_http_once` |
| `TcpStream` | `write_get`, `shutdown_write`, `read_to_string` |
| `ThreadPool` | unit-returning `execute(lambda: expression)` jobs |

`ThreadPool.finish()` consumes the pool and returns `Result[Unit, String]` after
closing the channel and joining workers. Use `.expect(...)` or propagate the result
when worker failure matters; `Drop` still closes/joins but never propagates a worker
panic.

Calls on an inferred declared-crate value may continue a crate method chain and
are ultimately checked by rustc. This is not general crate reflection: source
must provide enough expected type context, and a bad API call becomes a mapped
Cargo diagnostic.

## Domain types, methods, and traits

- `@rust.struct` emits a Clone/Debug Rust struct plus its Python ownership wrapper.
- `@rust.enum` bodies contain `Name = rust.variant(...)` declarations. Variants may
  be unit, tuple, or record shaped and may contain visible native domain types.
- `@rust.method(Type, name="...")` emits an inherent method. Its first parameter
  uses `Owned`, `Ref`, or `Mut` to choose `self`, `&self`, or `&mut self`.
- `Trait = rust.trait("Trait", method=ReturnType)` declares the current object-safe
  trait shape: shared receiver, no arguments, concrete owned return.
- `@rust.impl(Trait, Type, name="method")` emits a concrete implementation.
- `rust.Dyn[Trait]` and `rust.dyn_box(Trait, value)` create `dyn Trait` boxes for
  heterogeneous vectors. `rust.trait_call` emits fully qualified syntax when an
  inherent and one or more trait methods share a name.
- `@rust.operator(Left, name="add")` emits `std::ops::Add<Rhs>` using the helper's
  second parameter as RHS and return annotation as associated Output.

Receiver capability is checked before Rust emission. `Ref[T]` can satisfy shared
and explicitly interior-mutable operations, `Mut[T]` can also satisfy `&mut self`,
and `Owned[T]` can satisfy consuming operations. A mutable binding to `Ref[T]`
never counts as a mutable reference. Places retain their root through field and
index projections, so `bucket.items.push(value)` and mutable field reborrows mark
the owned `bucket` root mutable while the same operation through a shared root is
rejected as `CRAB208`.

Nested domain enum payloads are currently native-only at Python construction and
getter boundaries. Construct and inspect them inside compiled functions; direct
Python constructors/getters are omitted until consuming conversion semantics are
specified.

## Pattern matching

Python `match` is checked against the Rust subject type and emitted as an
exhaustive Rust match. Supported pattern families include:

- wildcard and name bindings;
- integer, bool, char, and Option `None` literals;
- `case left | right` or-patterns with identical binding sets;
- `rust.Range(low, high)` for inclusive Rust `low..=high` patterns;
- Python `pattern as name`, emitted as Rust `name @ pattern`;
- fixed tuple patterns and one `*_` rest, emitted as `..`;
- Option `rust.Some(pattern)`;
- unit/tuple/record enum patterns, struct patterns, and nesting;
- `if` guards whose environment includes the pattern bindings.

Python has no `if let`, `while let`, or `let ... else` grammar. Use an exhaustive
match, or a loop containing a match, when adapting those Rust forms.

## Focused advanced and unsafe surface

The advanced teaching surface is explicit and narrow:

- `rust.unsafe_read(local)` and `rust.unsafe_write(local, replacement)` create raw
  pointers to named Copy locals and isolate dereferencing in generated unsafe blocks.
- numeric `Vec.split_at_mut_sum(mid)` bounds-checks then demonstrates a safe
  abstraction over `from_raw_parts_mut`.
- `rust.c_abs(i32)` calls C `abs` through an unsafe extern declaration after
  rejecting `i32::MIN`, whose magnitude is not representable by C `int`.
- `rust.unsafe_static_increment(u64)` demonstrates synchronized global state with
  a checked `AtomicU64` update. It no longer uses `static mut`.
- `rust.type_alias_identity(value)`, `rust.call_twice(function, value)`,
  `rust.boxed_closure_call`, and `rust.closure_vector_total` emit a real type alias,
  function pointer, returned `Box<dyn Fn>`, and heterogeneous closure vector.

These are audited examples, not general inline Rust. Arbitrary raw addresses,
unions, user-authored unsafe traits, arbitrary FFI signatures, and escape-hatch
expressions remain rejected.

## Native networking and thread pool

`rust.TcpListener`, `rust.TcpStream`, and `rust.ThreadPool` are native-only local
types for the bounded Rust Book server proof. The listener binds an explicit
address; the supplied stream constructor connects only to a loopback port. The
generated fixed pool stores `Box<dyn FnOnce() + Send + 'static>` jobs in an mpsc
channel shared by workers through `Arc<Mutex<Receiver<_>>>`. Each job is contained
with `catch_unwind`; the first worker failure is retained for `finish()`. Dropping
the pool closes the sender and joins every worker without unwrapping join errors.

This is not a production HTTP framework: there is no TLS, persistent service
lifecycle, general request parser, arbitrary bind helper, or externally managed
background task.

## Cargo dependency declarations

Crate declarations are module-scope, static build inputs. Supply exactly one of
`version`, `path`, or `git`; a Git `rev` is optional but strongly recommended.
Feature names are literal strings:

```python
regex = rust.crate("regex", version="1")
local = rust.crate("native-core", path="./native", features=["fast"])
pinned = rust.crate("remote-core", git="https://example.test/repo.git", rev="abc123")
```

Relative paths resolve from the declaring source file. The Python binding is source
identity only: generated Rust gives it a component-injective internal alias, while
Cargo keeps the canonical package crate key when possible so procedural macros can
resolve their package correctly. Mandatory PyO3 uses a separate internal Cargo key
and cannot collide with a user binding named `pyo3`. Dynamic versions, paths,
revisions, and feature lists are rejected by the frontend. Cargo then validates
package resolution and the called API; a resolution failure is reported as
`CRAB302` at the declaration, while rustc API failures are mapped to the originating
call.

## Python and native effects

Every `FunctionIR` stores one or more typed effects:

- `NativeRust` — the generated body executes as Rust;
- `ConversionBoundary` — the exported call converts a parameter or return value;
- `PythonRuntime` — the call graph reaches an allowlisted Python operation;
- `Blocking` and `ThreadSpawn` — native scheduling/lifecycle behavior;
- `GlobalMutation`, `UnsafeMemory`, and `UnsafeFfi` — reviewed safety-relevant work;
- `MayPanic` — a reachable Rust panic path that relies on ABI containment.

The initial Python operation is `print(value)` for ABI-convertible scalar/string
values. `rust.println(value)` remains native. The Python effect propagates through
ordinary calls, inherent methods, concrete and dynamic trait dispatch, custom
operators, and function-pointer targets. Wrapper policy consumes the typed effects:
Python runtime, global mutation, unsafe memory, and unsafe FFI prevent GIL
detachment even when the signature itself contains only primitives.

Before code generation, an IR validation pass checks effect consistency and rejects
a Rust worker closure that directly or transitively reaches Python runtime state
(`CRAB206`). It also rejects a Python-runtime effect in methods/trait or operator
implementations, native async helpers, iterator closures, and function-pointer
targets (`CRAB207`) until those generated contexts have a result-aware boundary
lowering.

## Package import policy

Regular packages compile as one crate with explicit supported imports and
re-exports. The alpha compiler rejects internal import cycles (`CRAB204`) and
`import *` (`CRAB205`) rather than copying partially initialized bindings or
approximating Python's `__all__` and private-name rules. Cycle analysis includes
the referenced module, selected child module, and every parent-package initializer
that Python must execute.

## Generated identifier contract

Python-visible declaration names remain unchanged, but Rust internals use an
injective encoding of module-path components and declaration names. Domain types,
native helpers, ABI exports, ownership pyclasses, crate bindings, mandatory runtime
items, method glue, and the C FFI helper are kept collision-free. A pre-codegen
table rejects any duplicate emitted value, type, method, dependency, or crate
binding as `CRAB209` with the relevant source declaration.

## Async and parallel distinction

Rayon work is real Rust-native parallelism:

```python
rayon = rust.crate("rayon", version="1")

@rust.fn
def total(stop: rust.u64) -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([])
    for value in range(stop):
        values.push(value)
    return values.par_iter().copied().sum()
```

Crabwalk also has native Rust futures:

- `@rust.async_fn` on `async def` emits a native-only `async fn`;
- `await` composes those futures inside another native async helper;
- `rust.block_on`, `rust.join`, and `rust.select` enter/compose them;
- `rust.yield_now`, `rust.sleep_millis`, and `Receiver.recv_async` provide the
  bounded std-only teaching operations used by the Book suite.

The generated executor is intentionally small and educational; it is not Tokio and
does not promise scalable reactor I/O or cancellation.

Python's `await rust.async_call(function, *args)` is a separate boundary. It
schedules an eligible synchronous native `RustFunction` on Python's default thread
executor, rejects ownership/Python-runtime boundaries, and cannot preempt Rust work
after Python cancellation.
