# The Rust Book as Crabwalk

This package is a runnable, explanatory adaptation of all 21 chapters of [*The Rust Programming Language*](https://doc.rust-lang.org/book/). Every `@rust.fn` body compiles into one native Rust extension; Python only orchestrates imports and checks values at explicit boundaries.

The source baseline is rust-lang/book commit `917544888a55e4da7109bdba8c88c893c0da70f4` (captured 2026-08-21). See [COVERAGE.md](COVERAGE.md) for the chapter matrix, source links, implemented compiler surface, and verification status.

## Run it

Run the package from the repository's `examples` directory so `the_rust_book` is
the package root and unrelated sibling examples are not folded into its crate:

```text
cd examples
python -m the_rust_book.run_all
cd ..
```

Run the test commands below from the repository root:

```text
python -m pytest examples/the_rust_book/test_ch11_automated_tests.py -q
python -m pytest tests/integration/test_native_rust_book.py -q
```

The first cold import can invoke Cargo. Crabwalk reports analysis, cache, build, and load phases on stderr; an interactive terminal gets the animated meter. Use `CRABWALK_PROGRESS=never` for quiet CI or `CRABWALK_PROGRESS=always` to force durable phase output.

To inspect rather than execute:

```text
crabwalk expand examples/the_rust_book/__init__.py
crabwalk check examples/the_rust_book/__init__.py --locked
```

The committed dependency resolution is [the package Cargo.lock](../../crabwalk-locks/examples/the_rust_book/__init__.Cargo.lock).

## Reading order

- `ch01_...py` through `ch21_...py` follow the Book's chapter order.
- Source links sit immediately above each adaptation family.
- Comments explain what valid Python spelling becomes in Rust and which safety/type rule remains authoritative.
- `run_all.py` is the boundary-visible contract for the whole package.
- `test_ch11_automated_tests.py` preserves the Book's testing chapter as actual pytest tests.
- `hello.html` and `404.html` reproduce the final project's page assets.

## Adaptation vocabulary

| Label | Meaning |
|---|---|
| Direct | Python syntax maps naturally to the same Rust construct |
| Syntax-adapted | Valid Python needs a compiler marker or a nearby equivalent spelling |
| Native concept proof | The generated crate contains the Book mechanism, although the Python API is narrower |
| Compile-fail/documented | The Book example is intentionally invalid or requires a safety contract Crabwalk does not expose |

No accepted `@rust.fn` body falls back to Python. “Adapted” describes source spelling, not execution.

## Resource behavior

Chapter 21 binds only `127.0.0.1` with port `0`, allowing the OS to choose an unused port. Each call serves one request, closes both streams, drops its job sender, and joins every worker. It does not leave a background server running.

Chapter 20's unsafe helpers are deliberately bounded. They emit real unsafe Rust but do not provide arbitrary pointer dereferencing or inline-Rust escape hatches.
