---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-23
tags:
  - project/crabwalk
  - docs/language
---

# Crabwalk Language Reference

## Capability maturity

“Supported” is not a single breadth claim. Proof means one audited teaching shape;
Bounded means several documented forms under explicit constraints; Compositional
means values survive ordinary combinations across types, adapters, ownership, and
boundaries; Production additionally requires validated lifecycle, performance, and
platform evidence. Rust Book chapter coverage is tracked separately and never
promotes a language family by itself.

Each listed contract is attached to real pytest items. Release CI records whether
those items were collected, passed, failed, skipped, or xfailed and publishes a
machine-readable evidence manifest for every native OS/Python lane. A skipped or
xfail-only contract does not satisfy a maturity claim.

<!-- crabwalk-capabilities:start -->
| Capability | Maturity | Supported contract | Evidence | Important limit |
|---|---|---|---|---|
| Static compiler pipeline | Compositional | Source-spanned typed IR, validation, deterministic Rust/PyO3 emission | unit, native, package, diagnostic, and generated-Rust tests<br>Contracts: `compiler.package-native`, `compiler.generated-identities`, `compiler.pattern-identity` | an explicit Python subset; rustc remains authoritative |
| Ownership boundary | Compositional | Owned/Ref/Mut, move state, borrows, reload and fingerprint identity | multi-argument, alias, reload, thread, domain, and vector tests<br>Contracts: `ownership.failure-atomic`, `ownership.reload-fingerprint`, `ownership.domain-schema` | handles are thread-affine; no retained cross-call borrows |
| Cargo build and cache | Compositional | locks, complete modeled fingerprints, hashing, leases, atomic publish | dependency, corruption, replan, prune, race, and wheel tests<br>Contracts: `cache.corruption-repair`, `cache.concurrent-publication`, `cache.prune-load-lease` | trusted build scripts may require declared extra inputs |
| Sequential iterators | Compositional | owned/shared items; map/filter/filter_map/fold/reduce/collect and queries | Copy, String, &str, tuple, domain, one- and three-stage native pipelines<br>Contracts: `iterator.copy-inline`, `iterator.string-inline`, `iterator.string-split-local`, `iterator.opaque-shadow`, `iterator.borrowed-for-loop`, `iterator.borrowed-for-loop-native` | expression lambdas only; no retained iterator boundary |
| Rayon iterators | Compositional | typed par_iter with borrowed items, adapters, collect, sum and reduce | u64, Vec<String>, and Vec<domain> multi-adapter native tests<br>Contracts: `rayon.string-split-local`, `rayon.domain-filter-map-collect`, `rayon.indexed-enumerate`, `rayon.indexed-zip`, `rayon.unindexed-order-rejected`, `rayon.explicit-find-semantics` | requires an explicit Rayon dependency; no arbitrary Rayon API reflection |
| Structured native data | Compositional | recursive vectors, domain rows, nested domains, owned domain returns | Python mappings/handles through Vec<Row>, nested struct/enum round trips<br>Contracts: `structured.vector-domain-input`, `structured.nested-domain-roundtrip`, `structured.owned-domain-return` | allocating explicit input; direct recursive domain cycles are invalid Rust |
| Read-only numeric buffer boundary | Bounded | call-scoped zero-copy input from one-dimensional, C-contiguous, native-endian Python buffers | native array/memoryview track-plan test, zero-length exporters, and negative shape/format/alignment tests<br>Contracts: `buffer.readonly-numeric-native`, `buffer.invalid-input-rejected` | primitive numeric inputs only; GIL held; no writable, strided, retained, parallel, or output buffers |
| String, HashMap, Option/Result | Compositional | parse-transform-group-iterate-return algebra with typed errors | native delimited parsing and structured filter-group-emit acceptance<br>Contracts: `collections.result-pattern-algebra`, `collections.hashmap-iteration`, `collections.hashmap-split-local`, `collections.hashable-map-return` | documented method table is finite, not the complete Rust standard library |
| Typed crate adapters | Bounded | external types/functions, borrow signatures, closures, declared effects | real path-crate value and generic callback native test<br>Contracts: `crate.typed-value`, `crate.typed-callback` | no trait/builder manifest generation or automatic crate API discovery |
| Traits, generics, operators | Bounded | generic helpers, shared no-argument traits, Add implementations | Rust Book and focused native conformance tests<br>Contracts: `traits.dynamic-dispatch`, `generics.concrete-export` | not a general Rust trait or operator declaration language |
| std-only native futures | Proof | Future/await/join/select lowering through a teaching executor | focused Rust Book subprocess tests<br>Contracts: `futures.split-local-block-on` | busy-polling; no reactor, cancellation, Tokio, or Python future ABI |
| Thread pool and TCP | Proof | finite unit-job pool and loopback HTTP teaching operations | panic-containment and Rust Book web-server subprocess tests<br>Contracts: `threadpool.loopback-http` | no general server, task handles, backpressure, TLS, or cancellation |
| Advanced and unsafe intrinsics | Proof | audited operations for individual Rust Book concepts | subprocess panic/unsafe and exact code-generation tests<br>Contracts: `advanced.audited-intrinsics` | not general inline Rust, FFI, unsafe, macro, or pointer support |
<!-- crabwalk-capabilities:end -->

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
| `rust.Buffer[T]` | call-scoped alias-aware numeric view | top-level input only; borrows a read-only, one-dimensional, C-contiguous, native-endian Python buffer without copying elements |
| `rust.Option[T]` | `Option<T>` | `None` or the supported conversion for `T`; `T` must not itself normalize to `None` |
| `rust.Result[T, E]` | `Result<T, E>` | top-level exported return control type only; `Ok` converts `T`; `Err` raises `CrabwalkRustError` |
| `rust.Tuple[T, ...]` | fixed Rust tuple | recursively checked Python tuple when every element is boundary-safe |
| `None` return | `()` | Python `None` |

Bare `Vec` parameters are rejected because they would hide an allocating input
conversion. Use an ownership annotation and `rust.from_python`; see
[[Crabwalk Ownership and Domain Types]]. A supported `Vec[T]` return converts to a
new Python list at the explicit output boundary, except `Vec[u8]`, which is the
deliberate byte-oriented boundary and converts to Python `bytes`. The same rule
applies to `rust.to_python()` and Python-visible domain fields or enum payloads.
Generated domain parameters likewise require `Owned`, `Ref`, or `Mut`.

`Buffer[T]` is the bounded alternative when compatible numeric storage already
exists in Python and the function only needs to read it:

```python
from array import array
from crabwalk import rust

@rust.fn
def total(values: rust.Buffer[rust.f64]) -> rust.f64:
    result: rust.f64 = 0.0
    for value in values.iter():
        result += value
    return result

storage = array("d", [1.5, 2.0, 3.25])
print(total(memoryview(storage).toreadonly()))
```

Supported elements are `i8/i16/i32/i64`, `u8/u16/u32/u64/usize`, and
`f32/f64`. The exported value must implement Python's buffer protocol and expose
the exact native format. Valid zero-length buffers are accepted even when their
exporter has no aligned data pointer; Crabwalk substitutes Rust's canonical empty
slice without exposing or dereferencing exporter storage. Non-empty storage still
must be correctly aligned. Crabwalk holds the owner and the GIL for the complete
call, exposes only copied element reads to generated Rust, and reports the boundary
as `BorrowedBuffer` with `copies_elements=false`. Writable, strided,
multidimensional, retained, nested, parallel, and output buffers are deliberately
outside this milestone. A read-only view is constant-time; producing the backing
array in the first place may still allocate and copy, so measure that application
lifecycle separately.

Boundary composition must be lossless. `Option[Option[T]]` and `Option[Unit]` are
rejected because both `None` and `Some(None)`/`Some(())` would become Python
`None`. `Result` is rejected inside `Option`, `Vec`, tuples, maps, or another
`Result`; generated wrappers translate it only in the outer return position.
`HashMap` return keys must have a Python representation that is both hashable and
injective, preventing distinct Rust keys from collapsing into one Python key.

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
Iterator, future, and closure adapter stacks have anonymous concrete Rust types.
They may be stored in inferred locals, but ordinary assignment to the same slot is
rejected as `CRAB226`. Use unannotated `name = rust.shadow(expression)` to emit a
fresh inferred Rust binding. Consuming a tracked native local and using it again is
rejected as `CRAB227`; `Copy` values remain reusable.

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
| `Buffer[numeric T]` | read-only `len`, `is_empty`, indexing, and copied `iter`; top-level exported input only |
| `Vec[T]` | `push`, `pop`, `len`, `is_empty`, `iter`, `iter_ref`; typed `par_iter` with declared Rayon; numeric teaching intrinsic `split_at_mut_sum` |
| typed iterator | `map`, `filter`, `filter_map`, `copied`, `cloned`, `collect_vec`, `collect_map`, `sum`, `count`, `any`, `all`, sequential `find`, parallel `find_any`/`find_first`/`find_last`, `fold`, `reduce`, `enumerate`, `zip`; item ownership, execution, and Rayon indexed capability remain explicit |
| `String`, `Str` | `len`, `is_empty`, `lines`, `as_str`, `to_lowercase`, `contains`, `starts_with`, `ends_with`, `push_str`, `replace`, `find`, `trim`, `trim_start`, `trim_end`, `split`, `split_once`, `split_whitespace`, `strip_prefix`, `strip_suffix`, `chars`, `bytes`, typed numeric `parse`, and `join` |
| `Option[T]` | `is_some`, `is_none`, `unwrap`, `expect`, `unwrap_or`, `map`, `and_then`, `or_else`, `as_ref`, `copied`, `cloned` |
| `Result[T, E]` | `is_ok`, `is_err`, `unwrap`, `expect`, `unwrap_or`, `map`, `map_err`, `and_then`, `or_else`, `as_ref`, `ok`, `err`; `rust.Ok`/`rust.Err` patterns |
| `HashMap[K, V]` | `insert`, `contains_key`, `remove`, `get`, `get_mut`, `get_or`, `entry_or_insert`, numeric `add`, `len`, `is_empty`, `iter`, `iter_ref`, `keys`, `values`, `into_iter` |
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

An untyped declared-crate call may continue only as a terminal expression with a
concrete expected result. An inferred crate value cannot be stored: `CRAB222`
directs multi-expression APIs to `rust.extern_type` and `@rust.extern`. Typed
adapters declare the Rust path, full Crabwalk-visible signature, closure inputs and
outputs, and reviewed effects. Rustc remains authoritative for the actual crate API.

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

Trait conformance is also checked before emission: every declared method must be
implemented exactly once, names and return types must match, and the implementation
must contain only the shared receiver. An additional implementation parameter is a
source-spanned `CRAB211`; trait method arguments are not part of the current trait
declaration shape.

Direct nested struct fields and enum payloads can be constructed from a matching
compiled handle or mapping, read as fingerprint-bound handles, and deep-copied with
`to_python()`. Owned domain and `Vec[Domain]` returns preserve the same native
identity. Container-wrapped nested domain fields remain outside the current codec;
use a direct nested domain or a top-level structured vector.

## Pattern matching

Python `match` is checked against the Rust subject type and emitted as an
exhaustive Rust match. Supported pattern families include:

- wildcard and name bindings;
- integer, bool, char, and Option `None` literals;
- `case left | right` or-patterns with identical binding sets;
- `rust.Range(low, high)` for inclusive Rust `low..=high` patterns, with matching
  integer or char literal endpoints only;
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

For a crate API whose values outlive one terminal expression, declare types and
functions explicitly:

```python
native = rust.crate("native-core", path="./native")
Counter = rust.extern_type(native, path="model::Counter")

@rust.extern(native, path="model::read", effects=[rust.Pure])
def read(counter: rust.Ref[Counter]) -> rust.u64:
    ...
```

Omitting `effects` deliberately records `OpaqueCrateCall` and `MayPanic`. A
non-empty explicit list can use `Pure`, `PythonRuntime`, `Blocking`, `ThreadSpawn`,
`GlobalMutation`, `UnsafeMemory`, `UnsafeFfi`, or `MayPanic`; `Pure` must stand
alone. These declarations are trusted adapter contracts, not inferred audits of a
third-party crate implementation.

## Python and native effects

Every `FunctionIR` stores one or more typed effects:

- `NativeRust` — the generated body executes as Rust;
- `ConversionBoundary` — the exported call converts a parameter or return value;
- `OpaqueCrateCall` — a declared external crate call whose implementation effects
  Crabwalk cannot infer;
- `PythonRuntime` — the call graph reaches an allowlisted Python operation;
- `Blocking` and `ThreadSpawn` — native scheduling/lifecycle behavior;
- `GlobalMutation`, `UnsafeMemory`, and `UnsafeFfi` — reviewed safety-relevant work;
- `MayPanic` — a reachable Rust panic path that relies on ABI containment.

The initial Python operation is `print(value)` for ABI-convertible scalar/string
values. `rust.println(value)` remains native. The Python effect propagates through
ordinary calls, inherent methods, concrete and dynamic trait dispatch, custom
operators, and function-pointer targets. Wrapper policy consumes the typed effects:
Python runtime, opaque crate calls, global mutation, unsafe memory, and unsafe FFI
prevent GIL detachment even when the signature itself contains only primitives.

`OpaqueCrateCall` is visibility, not a claim that the external implementation is
pure, nonblocking, or Python-free. Crabwalk conservatively also records `MayPanic`
and keeps the GIL attached for an opaque call. Effect policy is complete for
Crabwalk-visible operations. Typed adapters can replace opacity with a reviewed
effect promise and recover detachment, but Crabwalk cannot prove that a third-party
implementation honors its declaration.

Every concrete `ExpressionIR` variant has one mandatory direct-effect rule; adding
a new expression without updating that table fails the compiler invariant suite.
Ordinary panic-capable forms include integer arithmetic, signed minimum-value
negation, indexing, integer `HashMap.add`, fallible synchronization/channel paths,
and explicit unwrap/expect operations. Child-call effects are then propagated over
the complete Crabwalk-visible dispatch graph.

Before code generation, an IR validation pass checks effect consistency and rejects
a Rust worker closure that directly or transitively reaches Python runtime state
(`CRAB206`). It also rejects a Python-runtime effect in methods/trait or operator
implementations, native async helpers, iterator closures, and function-pointer
targets (`CRAB207`) until those generated contexts have a result-aware boundary
lowering.

## Package import policy

Regular packages compile their reachable native modules as one crate with
explicit supported imports and re-exports. The roots are modules containing
Crabwalk declarations, the requested entry module, and required package
initializers. The compiler rejects cycles (`CRAB204`) and `import *` (`CRAB205`)
inside that graph rather than copying partially initialized bindings or
approximating Python's `__all__` and private-name rules. Cycle analysis includes
the referenced module, selected child module, and every parent-package initializer
that Python must execute. Unreachable Python-only modules remain ordinary package
content and are excluded from the native compiler identity.

## Generated identifier contract

Python-visible declaration names remain unchanged, but Rust internals use an
injective encoding of module-path components and declaration names. Domain types,
native helpers, ABI exports, ownership pyclasses, crate bindings, mandatory runtime
items, method glue, and the C FFI helper are kept collision-free. A pre-codegen
table rejects any duplicate emitted value, type, method, dependency, or crate
binding as `CRAB209` with the relevant source declaration.
Function/type-local source bindings must also be valid Rust identifiers. Rust
2024 strict and reserved keywords (including `_` and `gen`), compiler-reserved
`__cw_*` names, and generated pyclass member collisions are rejected as `CRAB210`;
wrapper-owned temporaries use the reserved prefix. Crabwalk retains a portable
ASCII identifier subset and does not lower raw identifiers such as `r#gen`.
Contextual weak keywords (`macro_rules`, `raw`, `safe`, and `union`) remain valid in
the binding positions Crabwalk emits; weak-keyword treatment is context-specific,
not a global ban.

The same validation protects Python lookup after a native value returns. Struct
and enum payload fields may not shadow the owned-value handle API (`moved`,
`rust_type`, `to_python`, or its internal slots), and enum variants may not shadow
the `RustType` marker API (`name`, `arguments`, `variants`, `rust_key`, and related
members). These collisions also fail as `CRAB210` rather than making reads and
writes resolve to different Python objects.

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

Borrowed Rayon string items can be filtered, mapped into owned strings, and
collected without consuming the input handle:

```python
@rust.fn
def active_lowercase(
    rows: rust.Ref[rust.Vec[rust.String]],
) -> rust.Vec[rust.String]:
    return rows.par_iter().filter(
        lambda row: row.contains("|active|")
    ).map(
        lambda row: row.to_lowercase()
    ).collect_vec()
```

Collecting a borrowed parallel iterator directly is rejected: use `copied()` for
Copy items or `map` into an owned value first.

Rayon vector sources begin as indexed iterators. `map`, `copied`, and `cloned`
preserve indexing; `filter` and `filter_map` remove it. Parallel `enumerate` and
`zip` therefore fail as `CRAB225` when a preceding adapter made either input
unindexed. Search semantics are explicit: use `find_any`, `find_first`, or
`find_last` instead of sequential `find`.

Iterator and future pipelines may be factored across unannotated locals. Crabwalk
retains their semantic type for later method and `await` checking while allowing
rustc to infer the anonymous concrete adapter/future type. Because different
adapter stacks can share a semantic capability type while having distinct concrete
Rust types, transformation rebindings use `rust.shadow(...)` rather than ordinary
assignment.

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
