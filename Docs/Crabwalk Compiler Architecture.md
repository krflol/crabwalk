# Crabwalk compiler architecture

Crabwalk compiles a deliberately bounded Python syntax into semantic IR and then
into deterministic Rust/PyO3. The Python AST is never treated as a Rust template,
and generated Rust is never used as Crabwalk's semantic type database.

## Pass pipeline

```text
UTF-8 source
  -> source.py             parsing, source spans, syntax diagnostics
  -> package_graph.py      reachable native modules and initialization edges
  -> declarations.py       structs, enums, traits, crates, functions, adapters
  -> signatures.py         resolved callable and dispatch signatures
  -> frontend.py           pass orchestration and typed scope construction
  -> lowering/             statement, expression, and pattern AST lowering
  -> bindings.py           BindingId/SymbolId assignment and hygienic Rust names
  -> ownership.py          places, receiver access, moves, and reborrows
  -> effects.py            exhaustive direct effects and call-graph propagation
  -> validation.py         cross-pass ownership/effect/name/ABI invariants
  -> rust_emission.py      deterministic typed function/body Rust emission
  -> emission.py           source-mapped writer and backend gensym state
  -> codegen.py            domain, runtime-support, and PyO3 ABI orchestration
  -> cargo_emission.py     Cargo manifest, build script, dependency identity
  -> rustc/Cargo           authoritative Rust checking and native artifact
```

`abi.py` owns the semantic question of which types may cross each supported
boundary. `boundary.py` owns the matching Python input and output codec contract.
The build service fingerprints the IR schema, codegen schema, compiler input,
dependency specification, lock, toolchain, environment, and declared extra inputs.

## Semantic identities

Source spelling and emitted Rust spelling are separate identities:

```text
SymbolId   package-level functions, domains, traits, and adapters
BindingId  parameters, locals, patterns, closures, fields, variants, methods,
           generics, and lifetimes
```

Each binding retains its Python name and source span for diagnostics. A per-scope
gensym allocator produces an injective Rust identifier, so Python names cannot
shadow prelude constructors, runtime support items, or compiler temporaries.
Value, type, macro, lifetime, and member namespaces are tracked independently.
Parameters, locals, destructuring and loop targets, closures, patterns, generic
parameters, lifetimes, struct fields, enum fields/variants, and trait methods all
carry source and emitted identities. Python-visible domain members retain their
source spelling through explicit PyO3 names while Rust uses the emitted identity.

Every compiler-injected binding that shares a user-emitted scope is allocated by
the same backend gensym. Fixed names inside isolated runtime-support functions are
implementation items rather than user-scope temporaries and are validated in the
separate generated support namespace.

Types use a tagged algebra rather than optional string fields. Concrete variants
include primitives, domains, external crate types, generic parameters, lifetimes,
ownership wrappers, tuples, arrays, containers, sequential/parallel iterators,
dynamic traits, runtime support types, unit, and the narrowly bounded inferred
terminal type. Rust spelling belongs to the backend; semantic passes match type
variants and stable IDs.

## Iterator contract

An iterator type records three independent facts:

```text
execution  Sequential | Parallel
item type  T
item mode  Owned | SharedRef | MutableRef
```

Sequential and Rayon adapters share typed lowering for `map`, `filter`,
`filter_map`, `copied`, `cloned`, `collect_vec`, `collect_map`, `sum`, `count`,
`any`, `all`, `find`, `fold`, `reduce`, `enumerate`, and `zip`, subject to their
documented execution/item constraints. Borrowed built-in and domain values use
semantic auto-dereference. An unsupported combination receives a targeted
diagnostic rather than falling through to an inferred Rust chain.

## Invariants for new compiler features

Every new expression or value family must include all of the following in one
change:

1. A semantic type and source-spanned IR node or an explicit reuse of an existing
   node.
2. Binding, ownership, effect, and traversal rules. Effect coverage is exhaustive:
   importing the compiler fails if an expression node has no declared rule.
3. Pre-codegen validation for combinations the backend cannot correctly lower.
4. Deterministic code generation and a schema-version bump when output or IR
   identity changes.
5. A negative diagnostic test, a generated-Rust assertion, and native interaction
   evidence for an advertised family.
6. A capability-registry update when the supported contract or maturity changes.

The public capability table in the language reference is generated from
`compiler/capabilities.py`. Rust Book chapter coverage is pedagogical coverage,
not a claim that a language family is complete.

## Pass ownership

The extraction is incremental rather than a rewrite, but the pass boundaries are
now executable modules rather than roadmap labels. Source/graph discovery,
declarations, signatures, expression/statement/pattern policies, binding identity,
ownership, effects, validation, Rust body emission, ABI policy, and Cargo emission
are independently imported, typed, and tested. `frontend.py` retains stateful scope
orchestration; `codegen.py` retains final backend composition. Neither owns the
semantic policies extracted into those passes.
