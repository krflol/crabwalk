# Rust Book coverage

Baseline: [rust-lang/book](https://github.com/rust-lang/book) commit `917544888a55e4da7109bdba8c88c893c0da70f4`.
Compositional example refresh: 2026-08-30.

“Complete” means the chapter's principal runnable concepts have native Crabwalk examples and package assertions. It does not mean every intentionally non-compiling listing is copied into executable source; those are represented by focused diagnostics or explanatory comments where useful. Chapter completeness is pedagogical coverage only. It does not assert that the corresponding iterator, collection, trait, async, networking, or unsafe family is a complete language subsystem; the generated maturity table in the Language Reference is authoritative for those claims.

| Chapter | Module | Native coverage | Evolution delivered | Status |
|---:|---|---|---|---|
| 1 | `ch01_getting_started.py` | Hello world | native println and first package build | Complete |
| 2 | `ch02_guessing_game.py` | comparison and bounded secret derivation | typed branches and integer boundaries | Complete, I/O/randomness adapted deterministically |
| 3 | `ch03_common_concepts.py` | bindings, shadowing, const, tuples, arrays, chars, loops | compound types, destructuring, repeat arrays | Complete |
| 4 | `ch04_ownership.py` | borrow, mutable borrow, move, string slice | Owned/Ref/Mut wrappers and move checks | Complete |
| 5 | `ch05_structs.py` | Rectangle construction, methods, factory return | inherent methods and `Owned[Rectangle]` boundary | Complete |
| 6 | `ch06_enums.py` | Message variants, exhaustive match, Option `plus_one` | unit/tuple/record enums and typed Option patterns | Complete |
| 7 | `ch07_modules.py` | cross-module domain import/call | package graph and re-export resolution | Complete |
| 8 | `ch08_collections.py` | Vec, String pipelines, returned/iterated HashMap | split-transform-collect, grouping algebra, and checked Python mapping input | Complete |
| 9 | `ch09_error_handling.py` | Result, native file I/O, parse, combinators, patterns, propagation, panic | real `io::Error` propagation with `?`, declared `From` conversion into a structured application error, typed error algebra, panic containment | Complete |
| 10 | `ch10_generics_traits_lifetimes.py` | generic largest, richer trait method, bounds, named lifetime | monomorphization, mutable trait receiver with typed argument, and LifetimeRef | Complete |
| 11 | `ch11_automated_tests.py` | assertions, panic expectations | runnable pytest teaching suite | Complete |
| 12 | `ch12_minigrep.py` | search, owned SearchConfig, config-driven dispatch | domain return/borrow plus lines iteration and Vec returns | Complete, filesystem CLI adapted to pure inputs |
| 13 | `ch13_closures_iterators.py` | Copy/non-Copy/domain iterators, explicit closure contracts, and typed Rayon pipelines | split anonymous locals, owned Vec<Shoe>, move capture, parallel index capability | Complete |
| 14 | `ch14_cargo.py` | package layout, regex and Rayon dependencies, lock | Cargo dependencies and package lock | Complete, publishing intentionally non-mutating |
| 15 | `ch15_smart_pointers.py` | Box, Rc counts, RefCell mutation | smart-pointer constructors/methods | Complete |
| 16 | `ch16_concurrency.py` | move thread, mpsc, Arc/Mutex, Python-visible Shared handle | Send/Sync checked by rustc and concurrent immutable calls from Python workers | Complete |
| 17 | `ch17_async_await.py` | async fn, await, join, select, async channel, stream-like loop | native futures and std-only executor | Complete teaching subset; not Tokio |
| 18 | `ch18_object_oriented.py` | encapsulated methods, trait objects, type-state | inherent methods, trait impls, Dyn boxes | Complete |
| 19 | `ch19_patterns.py` | all major pattern locations/syntax families | general patterns, guards, ranges, nested payloads, tuple ABI | Complete with Python syntax adaptations |
| 20 | `ch20_advanced_features.py` | unsafe operations, advanced traits/types/functions/macros | unsafe intrinsics, Add, UFCS, fn pointers, Box<dyn Fn>, aliases | Complete teaching slice with explicit constraints |
| 21 | `ch21_web_server.py` | HTTP 200/404/sleep, finite pool, validation, graceful Drop | TcpListener/TcpStream and ThreadPool | Complete bounded loopback project |

## Chapter 19 pattern map

| Book family | Crabwalk spelling | Generated Rust |
|---|---|---|
| let destructuring | tuple assignment | `let (x, y, z) = ...` |
| if/while let and let-else | exhaustive match, or loop plus match | ordinary exhaustive `match` |
| for pattern | `for index, value in iterator` | `for (index, value) in ...` |
| literals/or | `case 1 \| 2` | `1 \| 2` |
| inclusive range | `case rust.Range(3, 7)` | `3..=7` |
| at binding | `case pattern as found` | `found @ pattern` |
| tuple rest | `case (head, *_, tail)` | `(head, .., tail)` |
| struct/enum/nested | Python class patterns | typed Rust record/tuple patterns |
| guard | `case pattern if condition` | `pattern if condition` |

## Chapter 20 constraint map

- Raw reads/writes accept named Copy locals only and emit `&raw` plus a narrow unsafe block.
- The split abstraction bounds-checks before constructing two nonoverlapping mutable slices.
- Arbitrary pointer dereference, unions, user-authored unsafe traits, and general inline Rust remain unsupported.
- Trait declarations remain a focused object-safe surface; std Iterator associated items, generic bounds, Add<Rhs>, and UFCS have dedicated typed paths.
- Function pointers and closure trait objects remain inside native Rust and are not exported as Python callable objects.
- Declarative `vec!` and PyO3 procedural attributes are generated; authoring a new proc-macro crate remains a separate Cargo project concern.

## Evidence

Focused tests added by the later chapters:

- `tests/unit/test_collection_algebra.py`, `tests/unit/test_iterators.py`, and
  `tests/unit/test_iterator_capability_matrix.py` for the expanded Chapters 8, 9,
  and 13 compositions
- `tests/integration/test_native_etl_acceptance.py`,
  `tests/integration/test_native_etl_pipeline.py`, and
  `tests/integration/test_native_parallel.py` for structured and Rayon workloads
- `tests/unit/test_patterns.py` and `tests/integration/test_native_patterns.py`
- `tests/unit/test_advanced_features.py` and `tests/integration/test_native_advanced_features.py`
- `tests/unit/test_web_server.py` and `tests/integration/test_native_web_server.py`
- `tests/integration/test_native_showcase_examples.py` for the documented
  structured ETL boundary
- `tests/integration/test_native_rust_book.py` for one-crate Chapters 1–21 execution

The package runner's terminal line is:

```text
Rust Book chapters 1-21: all native assertions passed
```

The package runner is part of the supported native integration suite, not a
copy-pasted transcript. Release-matrix evidence and the generated capability
evidence manifest remain the authoritative platform and subsystem gates.
