---
type: reference
project: Crabwalk
status: implemented
updated: 2026-08-30
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
| Non-executing source embedding | Bounded | content-addressed single-source/virtual-package compilation and direct native callable binding | native cross-module non-execution, callable binding, and process cancellation tests<br>Contracts: `embedding.nonexecuting-source-callable`, `embedding.phase-cancellation`, `embedding.virtual-package`, `embedding.generated-artifacts` | Cargo dependencies remain a trusted build boundary; virtual mappings are regularized into immutable package snapshots |
| Ownership boundary | Compositional | Owned/Ref/Mut plus immutable Shared, move state, borrows, reload and fingerprint identity | multi-argument, alias, reload, thread, domain, and vector tests<br>Contracts: `ownership.failure-atomic`, `ownership.reload-fingerprint`, `ownership.domain-schema`, `ownership.shared-send-sync`, `ownership.audited-gil-release` | ordinary handles are thread-affine; Shared is immutable Send + Sync only; no retained cross-call borrows |
| Cargo build and cache | Production | locks, complete modeled fingerprints, hashing, leases, atomic publish, cancellation, and release budgets | dependency, corruption, replan, prune, race, cancellation, wheel, and versioned performance gates<br>Contracts: `cache.corruption-repair`, `cache.concurrent-publication`, `cache.prune-load-lease`, `build.hard-cancellation`, `build.performance-budgets` | trusted build scripts may require declared extra inputs |
| Application packaging | Bounded | PEP 517 wheel/sdist metadata merging with regular, namespace, and multiple top-level packages | clean dependency-resolving install of a native multi-package wheel without a Rust toolchain<br>Contracts: `packaging.metadata-sdist`, `packaging.pep517-multi-package` | platform wheels remain CPython-specific and must be built per supported target |
| Sequential iterators | Compositional | owned/shared items; map/filter/filter_map/fold/reduce/collect and queries | Copy, String, &str, tuple, domain, one- and three-stage native pipelines<br>Contracts: `iterator.copy-inline`, `iterator.string-inline`, `iterator.string-split-local`, `iterator.opaque-shadow`, `iterator.borrowed-for-loop`, `iterator.borrowed-for-loop-native`, `iterator.vec-consuming` | expression lambdas only; no retained iterator boundary |
| Rayon iterators | Compositional | typed par_iter with borrowed items, adapters, collect, sum and reduce | u64, Vec<String>, and Vec<domain> multi-adapter native tests<br>Contracts: `rayon.string-split-local`, `rayon.domain-filter-map-collect`, `rayon.indexed-enumerate`, `rayon.indexed-zip`, `rayon.unindexed-order-rejected`, `rayon.explicit-find-semantics` | requires an explicit Rayon dependency; no arbitrary Rayon API reflection |
| Structured native data | Compositional | recursive vectors, domain rows, nested domains, owned domain returns | Python mappings/handles through Vec<Row>, nested struct/enum round trips<br>Contracts: `structured.vector-domain-input`, `structured.hashmap-input`, `structured.nested-domain-roundtrip`, `structured.owned-domain-return` | allocating explicit input; direct recursive domain cycles are invalid Rust |
| Read-only numeric buffer boundary | Bounded | call-scoped zero-copy input from one-dimensional, C-contiguous, native-endian Python buffers | native array/memoryview track-plan test, zero-length exporters, and negative shape/format/alignment tests<br>Contracts: `buffer.readonly-numeric-native`, `buffer.invalid-input-rejected` | primitive numeric inputs only; GIL held; no writable, strided, retained, parallel, or output buffers |
| Owned UTF-8 text column boundary | Bounded | one-crossing bytes+offset construction with immutable native row access | native UTF-8 lifecycle, malformed-layout rejection, and telemetry tests<br>Contracts: `text-column.owned-native`, `text-column.invalid-layout` | owned contiguous UTF-8 only; no writable or retained Python borrow |
| String, HashMap, Option/Result | Compositional | parse-transform-group-iterate-return algebra with typed errors | native delimited parsing and structured filter-group-emit acceptance<br>Contracts: `collections.result-pattern-algebra`, `collections.hashmap-iteration`, `collections.hashmap-split-local`, `collections.hashable-map-return`, `collections.hashmap-borrowed-string-key` | documented method table is finite, not the complete Rust standard library |
| Native standard-library ETL | Bounded | checked casts, isize, slices/chunks/windows, ordered/hash collections, sorting, numeric formatting, UTF-8 bytes, PathBuf, and buffered I/O | native parse-validate-group-sort-format-emit application acceptance<br>Contracts: `etl.native-standard-library`, `etl.ordered-grouping` | finite UTF-8/path surface; no arbitrary filesystem traversal policy |
| Native filesystem results | Proof | typed File::open and whole-file String reads with io::Error propagation | native success, open-error, and read-error Result propagation test<br>Contracts: `filesystem.result-propagation` | read-only whole-file teaching surface; no general path or filesystem API |
| Structured native errors | Bounded | declared From conversions, custom error enums, fields, and cause chains | native file, parse, and validation errors through one application error<br>Contracts: `errors.from-structured`, `errors.undeclared-from-rejected` | error payloads are displayable scalar/string/io/error values; no arbitrary Error trait discovery |
| Typed crate adapters | Bounded | external types/functions/traits, borrow signatures, closures, declared effects | real path-crate value, generic callback, buffer, and trait native tests<br>Contracts: `crate.typed-value`, `crate.typed-callback`, `crate.builder-method-error`, `crate.buffer-adapter`, `crate.external-owned-handle` | no automatic crate API discovery or manifest generation |
| Typed Python-call adapters | Bounded | static Python signatures, explicit effects, PyErr propagation, and checked return extraction | native success/exception/invalid-return plus closure-placement diagnostics<br>Contracts: `python-adapter.success-errors`, `python-adapter.explicit-target`, `python-adapter.method-placement`, `python-adapter.invalid-placement` | synchronous calls only; rejected in closures, trait/operator methods, workers, and async helpers |
| Traits, generics, operators | Bounded | per-parameter generic bounds; typed trait arguments; ref/mut/owned receivers; generic and associated outputs; arithmetic operators | focused lowering and native compositional conformance tests<br>Contracts: `traits.dynamic-dispatch`, `generics.concrete-export`, `traits.arguments-receivers-associated`, `traits.external-implementation`, `closures.capture-contracts` | finite safe trait/operator surface; no unsafe traits or specialization |
| std-only native futures | Proof | Future/await/join/select lowering through a teaching executor | focused Rust Book subprocess tests<br>Contracts: `futures.split-local-block-on` | busy-polling; no reactor, cancellation, Tokio, or Python future ABI |
| Typed native channels | Bounded | unbounded Sender/Receiver and capacity-bearing SyncSender channels | native send/receive coverage for both std mpsc channel families<br>Contracts: `channels.unbounded`, `channels.bounded` | blocking std channels only; no async wake integration, fairness, or cancellation |
| Thread pool and TCP | Proof | finite unit-job pool and loopback HTTP teaching operations | panic-containment and Rust Book web-server subprocess tests<br>Contracts: `threadpool.loopback-http` | no general server, task handles, backpressure, TLS, or cancellation |
| Advanced and unsafe intrinsics | Proof | audited operations for individual Rust Book concepts | subprocess panic/unsafe and exact code-generation tests<br>Contracts: `advanced.audited-intrinsics` | not general inline Rust, FFI, unsafe, macro, or pointer support |
| Exported Python call ergonomics | Bounded | positional-or-keyword calls and lossless literal defaults | native external and compiled-internal keyword/default contract<br>Contracts: `calls.keywords-defaults`, `calls.invalid-default` | no positional-only, keyword-only, or variadic signatures |
| Watch, diagnostics, LSP, and Rust export | Bounded | versioned JSON diagnostics, stdio LSP, explain, watch, and deterministic crate export | framing/schema/export/watch CLI contract tests<br>Contracts: `tooling.diagnostics-explain-lsp`, `tooling.export-rust`, `tooling.watch` | LSP performs static Crabwalk analysis; watch uses polling; no completion/refactoring server |
<!-- crabwalk-capabilities:end -->

## Declaration contract

- Use exactly `from crabwalk import rust`; namespace aliases are rejected.
- `@rust.fn` exports a module-level synchronous function through Python's ABI.
  `@rust.fn(release_gil=True)` is an explicit audited release policy for eligible
  owned/shared native calls; it is not inferred purity for an external crate.
- `@rust.async_fn` marks a native-only `async def`; an exported function enters it
  explicitly with `rust.block_on(...)`.
- `@rust.generic(...)`, `@rust.method(...)`, `@rust.impl(...)`, and
  `@rust.operator(...)` declare native-only helpers that are called by
  exported functions. At ordinary Python runtime these names are metadata-bearing
  sentinels and raise instead of interpreting their original Python bodies.
- Every parameter has a supported Rust annotation. Value-returning functions
  have an explicit return annotation; a unit function may use `-> None` or omit it.
- Parameters may have lossless compile-time literal defaults. Variadics,
  positional-only markers, keyword-only parameters, and mutable/dynamic defaults
  are rejected.
- Exported Python calls and compiled internal calls accept positional or keyword
  arguments with normal duplicate/missing/unknown-argument diagnostics.

## Boundary types

| Source type | Rust type | Exported Python behavior |
|---|---|---|
| `rust.i8` … `rust.i128` | matching signed integer | exact `int`, checked range; `bool` rejected |
| `rust.u8` … `rust.u128`, `rust.usize` | matching unsigned integer | exact nonnegative `int`, checked range |
| `rust.f32`, `rust.f64` | matching float | `int`/`float`, `bool` rejected; finite f32 range checked |
| `rust.bool` | `bool` | exact Python `bool` only |
| `rust.String` | `String` | allocating UTF-8 copy |
| `rust.Str` | `&str` | call-scoped Python string borrow; cannot be returned |
| `rust.File` | `std::fs::File` | native-only local returned by `rust.File.open(path)` |
| `rust.IoError` | `std::io::Error` | error type for a top-level exported `Result`; becomes `CrabwalkRustError` |
| `@rust.error` enum | generated enum implementing `Debug`, `Display`, and `Error` | top-level `Result` error; becomes a structured `CrabwalkRustError` with `variant`, `fields`, and `source_chain` |
| `rust.Buffer[T]` | call-scoped alias-aware numeric view | top-level input only; borrows a read-only, one-dimensional, C-contiguous, native-endian Python buffer without copying elements |
| `rust.TextColumn` | owned UTF-8 bytes plus offsets | explicit one-crossing construction; move-aware handle; `to_python()` returns packed bytes and offsets |
| `rust.HashMap[K, V]` | `HashMap<K, V>` | checked Python mapping input and recursively normalized dict output when keys are injective/hashable |
| generated domain | generated Rust struct/enum | explicit handle/mapping input in recursive codecs; `Owned[Domain]` return preserves native identity |
| declared `rust.extern_type` | crate-owned Rust type | opaque `Owned` return plus later `Owned`/`Ref`/`Mut` handle input; no implicit Python value conversion |
| `rust.Shared[T]` | `Arc<T>` | immutable cross-thread handle for compiler-approved `Send + Sync` payloads |
| `rust.Option[T]` | `Option<T>` | `None` or the supported conversion for `T`; `T` must not itself normalize to `None` |
| `rust.Result[T, E]` | `Result<T, E>` | top-level exported return control type only; `Ok` converts `T`; `Err` raises `CrabwalkRustError` |
| `rust.Tuple[T, ...]` | fixed Rust tuple | recursively checked Python tuple when every element is boundary-safe; direct Python ABI conversion is limited to 12 items by PyO3 0.29 |
| `None` return | `()` | Python `None` |

Bare `Vec` parameters are rejected because they would hide an allocating input
conversion. Use an ownership annotation and `rust.from_python`; see
[[Crabwalk Ownership and Domain Types]]. A supported `Vec[T]` return converts to a
new Python list at the explicit output boundary, except `Vec[u8]`, which is the
deliberate byte-oriented boundary and converts to Python `bytes`. The same rule
applies to `rust.to_python()` and Python-visible domain fields or enum payloads.
Generated domain parameters likewise require `Owned`, `Ref`, `Mut`, or eligible
immutable `Shared`. A top-level `HashMap[K, V]` parameter is the explicit exception:
it accepts a checked Python mapping because no persistent map handle is created.
Native-only tuples may be larger, but a tuple at any level of a direct exported or
Python-adapter parameter/return is limited to 12 elements. Larger products fail as
`CRAB237`; use a generated domain type or nested smaller tuples.

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
| `Vec[T]` | `push`, `pop`, `reserve`, `len`, `is_empty`, `iter`, `iter_ref`, `as_slice`, indexing, sorting/reverse/dedup/truncate, consuming `into_iter`; typed `par_iter` with declared Rayon; numeric teaching intrinsic `split_at_mut_sum` |
| typed iterator | `map`, `filter`, `filter_map`, `copied`, `cloned`, `collect_vec`, `collect_map`, `sum`, `count`, `any`, `all`, sequential `find`, parallel `find_any`/`find_first`/`find_last`, `fold`, `reduce`, `enumerate`, `zip`; item ownership, execution, and Rayon indexed capability remain explicit |
| `String`, `Str` | `len`, `is_empty`, `lines`, `as_str`, explicit owned `String.clone`, `to_lowercase`, `contains`, `starts_with`, `ends_with`, `push_str`, `replace`, `find`, `trim`, `trim_start`, `trim_end`, `split`, `split_once`, `split_whitespace`, `strip_prefix`, `strip_suffix`, `chars`, `bytes`, typed numeric `parse`, and `join` |
| `Option[T]` | `is_some`, `is_none`, `unwrap`, `expect`, `unwrap_or`, `map`, `and_then`, `or_else`, `as_ref`, `as_mut`, `copied`, `cloned` |
| `Result[T, E]` | `is_ok`, `is_err`, `unwrap`, `expect`, `unwrap_or`, `map`, `map_err`, `and_then`, `or_else`, `as_ref`, `ok`, `err`; `rust.Ok`/`rust.Err` patterns |
| `HashMap[K, V]` | `insert`, `contains_key`, `remove`, `get`, `get_mut`, `get_or`, `entry_or_insert`, numeric `add`, `len`, `is_empty`, `iter`, `iter_ref`, `keys`, `values`, `into_iter` |
| `BTreeMap[K, V]` | ordered `insert`, lookup/mutation, numeric `add`, length/query, iterator/key/value/consuming iteration |
| `HashSet[T]`, `BTreeSet[T]` | `insert`, `remove`, `contains`, `len`, `is_empty`, `iter`, `into_iter` with hash/ordered constraints |
| `TextColumn` | immutable `len`, `is_empty`, `get`, `contains_at`, `total_bytes` |
| `Box`, `Rc`, `RefCell` | focused construction, copy dereference/count/interior-mutation operations used by the Book suite |
| `Arc<Mutex<T>>` | `clone`, `strong_count`, numeric `add_locked`, `get_locked` |
| `Sender`, `SyncSender`, `Receiver`, `ThreadHandle` | `send`, `recv`, `recv_async`, `join`; `rust.channel(T, capacity)` returns a bounded `SyncSender[T]` pair |
| `TcpListener` | `local_port`, bounded `serve_http_once` |
| `TcpStream` | `write_get`, `shutdown_write`, `read_to_string` |
| `File` | `rust.File.open(path) -> Result[File, IoError]`; mutable `read_to_string() -> Result[String, IoError]` |
| `ThreadPool` | unit-returning `execute(lambda: expression)` jobs |

`ThreadPool.finish()` consumes the pool and returns `Result[Unit, String]` after
closing the channel and joining workers. Use `.expect(...)` or propagate the result
when worker failure matters; `Drop` still closes/joins but never propagates a worker
panic.

`rust.try_(result)` is the Python-valid spelling of Rust's postfix `?` operator.
It unwraps `Ok` and returns `Err` from the enclosing native function immediately.
The enclosing function must return `rust.Result`. Its error type may match the
operand directly, or it may be an `@rust.error` enum with exactly one
`rust.from_error(source_type)` variant. Crabwalk emits the corresponding Rust
`From<source_type>` implementation, so the generated `?` performs the same
conversion described by the Rust Book. Undeclared or ambiguous conversions fail
before Rust emission with `CRAB177` or `CRAB230`.

For `HashMap[String, V]`, lookup operations (`contains_key`, `remove`, `get`,
`get_mut`, and `get_or`) accept either an owned `String` key or a borrowed `Str`.
The borrowed form emits Rust's `String: Borrow<str>` lookup without allocating or
cloning the key. Inserting and entry mutation still require an owned `String`.

An untyped declared-crate call may continue only as a terminal expression with a
concrete expected result. An inferred crate value cannot be stored: `CRAB222`
directs multi-expression APIs to `rust.extern_type` and `@rust.extern`. Typed
adapters declare the Rust path, full Crabwalk-visible signature, closure inputs and
outputs, and reviewed effects. Rustc remains authoritative for the actual crate API.
`@rust.extern_method` additionally attaches a declared free Rust function to an
external receiver type with explicit shared/mutable/owned receiver semantics. This
supports typed builder values, consuming `Result` transitions, and closure-taking
methods without falling back to inferred intermediate chains.

Adapter positions such as `Result.map_err` accept either an expression lambda or a
compatible synchronous unary native function item. The complete parameter and
return types are checked before emission; use a lambda when borrowing, conversion,
capture, or arity adaptation is required.

`rust.Owned[ExternalType]` may cross an exported return boundary as an opaque,
fingerprint-bound handle and later enter `Owned`, `Ref`, or `Mut` parameters without
copying. The external type need not implement `Clone`, `Debug`, or `Send`. Because
no Python codec was declared for it, `to_python()` is intentionally rejected.

A `Buffer[T]` passed to an external adapter declared as `rust.Buffer[T]` is copied
into temporary owned Rust storage before the adapter receives `&[T]`.
That explicit adapter-boundary copy avoids inventing an immutable slice over
aliasable Python memory. Direct generated `Buffer` iteration remains zero-copy and
keeps the exporter lease and GIL for the call.

## Domain types, methods, and traits

- `@rust.struct` emits a Clone/Debug Rust struct plus its Python ownership wrapper.
- `@rust.enum` bodies contain `Name = rust.variant(...)` declarations. Variants may
  be unit, tuple, or record shaped and may contain visible native domain types.
- `@rust.error` declares a native-only error enum. `Name =
  rust.from_error(SourceType)` creates a one-field variant plus an explicit Rust
  `From<SourceType>` implementation; ordinary `rust.variant(...)` values model
  application validation failures. Exported failures retain their variant,
  displayable fields, and declared conversion/source chain in Python.
- `@rust.method(Type, name="...")` emits an inherent method. Its first parameter
  uses `Owned`, `Ref`, or `Mut` to choose `self`, `&self`, or `&mut self`.
- `rust.trait_method(...)` declares argument types, receiver mode
  (`shared`/`mut`/`owned`), method type parameters/bounds, and concrete or associated
  output. `rust.trait(...)` groups those method declarations; the old return-type
  shorthand remains the shared/no-argument form.
- `@rust.impl(Trait, Type, name="method")` emits a concrete implementation.
- `rust.extern_trait(crate, path="module::Trait", ...)` declares a typed
  dependency-owned trait. It may be implemented for a local Crabwalk domain type;
  an external-trait/external-type pair is rejected by Rust's orphan rule.
- `rust.Dyn[Trait]` and `rust.dyn_box(Trait, value)` create `dyn Trait` boxes for
  heterogeneous vectors. `rust.trait_call` emits fully qualified syntax when an
  inherent and one or more trait methods share a name.
- `@rust.operator(Left, name=...)` supports the finite arithmetic operator set
  (`add`, `subtract`, `multiply`, `divide`, `remainder`) using the helper's second
  parameter as RHS and return annotation as associated `Output`.
- `rust.closure(lambda ..., kind="fn", capture="move")` makes closure call-trait
  and capture mode explicit. Accepted expression lambdas may also use a tuple-like
  `(side_effect, result)` body, which lowers to a Rust block whose final expression
  is the closure result. Parallel adapters require `Fn` rather than `FnMut`.

Receiver capability is checked before Rust emission. `Ref[T]` can satisfy shared
and explicitly interior-mutable operations, `Mut[T]` can also satisfy `&mut self`,
and `Owned[T]` can satisfy consuming operations. A mutable binding to `Ref[T]`
never counts as a mutable reference. Places retain their root through field and
index projections, so `bucket.items.push(value)` and mutable field reborrows mark
the owned `bucket` root mutable while the same operation through a shared root is
rejected as `CRAB208`.

Trait conformance is also checked before emission: every declared method must be
implemented exactly once; receiver ownership, argument arity/types, generic
parameters/bounds, and concrete/associated outputs must match. Implementations may
therefore use shared, mutable, or consuming receivers and typed method arguments.

For example, a local application type can implement a framework trait without a
handwritten semantic shim:

```python
framework = rust.crate("framework", path="./framework")
App = rust.extern_trait(
    framework,
    path="App",
    update=rust.trait_method(None, rust.u64),
)

@rust.struct
class Editor:
    frames: rust.u64

@rust.impl(App, Editor, name="update")
def update(editor: rust.Mut[Editor], frame: rust.u64) -> None:
    editor.frames = frame
```

Nested struct fields and enum payloads can be constructed from a matching compiled
handle or mapping, read as fingerprint-bound handles, and deep-copied with
`to_python()`. The recursive codec supports domain leaves inside `Vec`, `Option`,
and tuples. Owned domain and `Vec[Domain]` returns preserve native identity; direct
recursive type cycles remain invalid Rust.

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

## Native filesystem/ETL, networking, and thread pool

`rust.File` and `rust.IoError` provide the bounded Chapter 9 lifecycle:
`rust.File.open(path)` returns the real `std::io::Result<File>`, and mutable
`File.read_to_string()` allocates a destination `String`, invokes
`std::io::Read::read_to_string`, and returns `Result[String, IoError]`. This is a
whole-file teaching adapter.

The chapter example wraps `IoError` in `UsernameError.Io` through
`rust.from_error(rust.IoError)`. Both native I/O operations use `rust.try_`, and
the Python failure exposes `error.variant == "Io"`, a `source` field, and a typed
`rust.IoError` entry in `error.source_chain`.

The larger native ETL surface adds `PathBuf` construction, buffered whole-file
read/write, metadata length, directory listing, checked numeric casts, slices with
`chunks`/`windows`, ordered/hash maps and sets, sorting/deduplication, UTF-8
bytes/string conversion, integer `to_string`, and bounded fixed-decimal formatting.
These operations are sufficient for the native parse → validate → group → sort →
format → emit acceptance workload. They are not a filesystem traversal/security
policy or arbitrary streaming framework; applications still own path authorization,
resource limits, atomic replacement, and untrusted-input policy.

`rust.channel(T)` emits an unbounded `std::sync::mpsc::Sender[T]`/`Receiver[T]`
pair. `rust.channel(T, capacity)` emits a bounded synchronous channel whose sender
is `rust.SyncSender[T]`; a full channel applies Rust's blocking backpressure. Both
forms are process-local blocking std channels, not an async reactor or cancellation
protocol.

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

Integers expose ordinary `to_string()` and `f64` exposes bounded
`format_fixed(digits)` for the native ETL surface. Use a typed adapter when a more
specific rendering algorithm is part of the data contract:

```python
formatting = rust.crate("formatting-adapter", path="./formatting-adapter")

@rust.extern(formatting, path="format_u64", effects=[rust.Pure])
def format_u64(value: rust.u64) -> rust.String:
    ...

@rust.extern(formatting, path="format_js_f64", effects=[rust.Pure])
def format_js_f64(value: rust.f64) -> rust.String:
    ...
```

The local Rust adapter should pin and test the intended formatter. In particular,
Rust `Display`/`to_string()` is not a promise of JavaScript-compatible floating-
point rendering; use a crate with that explicit contract when byte-for-byte JSON or
JavaScript output matters. Keeping the adapter typed gives Crabwalk the signature
and effects without claiming automatic reflection over arbitrary crate APIs.

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

Python work enters through `print(value)` or a statically declared synchronous
`@rust.python_adapter`. An adapter gives the Python callable a Crabwalk-visible
signature and explicit extra effects; generated code attaches to Python, imports
the named module/callable, propagates `PyErr`, and checks its return conversion.
By default it targets the declaration module and function name; use
`@rust.python_adapter(module="operator", name="neg")` to route explicitly.
`rust.println(value)` remains native. The Python effect propagates through ordinary
calls, inherent methods, concrete and dynamic trait dispatch, custom operators,
and function-pointer targets. Result-aware inherent methods may call Python;
trait/operator methods, closures, workers, and native async helpers still reject
that placement. Wrapper policy consumes the typed effects: Python runtime, opaque
crate calls, global mutation, unsafe memory, and unsafe FFI prevent *automatic* GIL
detachment even when the signature itself contains only primitives.

`OpaqueCrateCall` is visibility, not a claim that the external implementation is
pure, nonblocking, or Python-free. Crabwalk conservatively also records `MayPanic`
and keeps the GIL attached for an opaque call. Effect policy is complete for
Crabwalk-visible operations. Typed adapters can replace opacity with a reviewed
effect promise and recover detachment, but Crabwalk cannot prove that a third-party
implementation honors its declaration.

`@rust.fn(release_gil=True)` is the deliberate override for an audited call whose
visible effects are conservative (for example `OpaqueCrateCall` plus `Blocking`).
Validation rejects any reachable `PythonRuntime` operation and any call-scoped
borrow (`Buffer`, `Str`, `Ref`, or `Mut`). `Owned` and immutable `Shared` handles are
preflighted/extracted and their Python guards are dropped before `py.detach(...)`.
The author remains responsible for the external implementation's thread safety and
for the truth of the no-Python audit. Inspection reports `gil_policy` separately
from the effect list.

Every concrete `ExpressionIR` variant has one mandatory direct-effect rule; adding
a new expression without updating that table fails the compiler invariant suite.
Ordinary panic-capable forms include integer arithmetic, signed minimum-value
negation, indexing, integer `HashMap.add`, fallible synchronization/channel paths,
and explicit unwrap/expect operations. Child-call effects are then propagated over
the complete Crabwalk-visible dispatch graph.

Before code generation, an IR validation pass checks effect consistency and rejects
a Rust worker closure that directly or transitively reaches Python runtime state
(`CRAB206`). It also rejects a Python-runtime effect in trait/operator methods,
native async helpers, iterator closures, and function-pointer targets (`CRAB207`)
until those generated contexts have a result-aware boundary lowering. Inherent
method glue is result-aware and is therefore supported.

## Package import policy

Regular and configured namespace packages compile their reachable native modules
as one crate with explicit supported imports and re-exports. The roots are modules
containing Crabwalk declarations, the requested entry module, and required package
initializers. Domain, crate, and function/module bindings are resolved to a fixed
point, so compiler-visible declaration cycles do not depend on partially executed
Python initializers. `import *` honors a literal static `__all__`; otherwise it
copies compiler-visible names that do not begin with `_`. Dynamic or malformed
`__all__` is rejected as `CRAB205`. Unreachable Python-only modules remain ordinary
package content and are excluded from the native compiler identity while remaining
covered by installed-wheel source integrity.

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
