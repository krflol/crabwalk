"""Chapter 13: typed Rust closures, captures, and iterator adapters."""

from crabwalk import rust


# Rust Book sources:
# https://doc.rust-lang.org/book/ch13-01-closures.html#capturing-the-environment-with-closures
# https://doc.rust-lang.org/book/ch13-02-iterators.html#methods-that-produce-other-iterators
#
# Each Python lambda is statically typed from its iterator item. It becomes a Rust
# closure and can capture `offset` by immutable borrow. `Vec.iter()` is emitted as
# `iter().copied()` for Copy elements, making the lambda's `value` a `u64` rather
# than a Python object or an implicit reference wrapper.
@rust.fn
def transformed(
    minimum: rust.u64,
    offset: rust.u64,
) -> rust.Vec[rust.u64]:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3, 4])
    return (
        values.iter()
        .map(lambda value: value + offset)
        .filter(lambda value: value >= minimum)
        .collect_vec()
    )


# Rust Book sources (`sum` as a consuming adapter and lazy iterator execution):
# https://doc.rust-lang.org/book/ch13-02-iterators.html#methods-that-consume-the-iterator
# https://doc.rust-lang.org/book/ch13-02-iterators.html#methods-that-produce-other-iterators
#
# `map` is lazy. Nothing executes until `sum` consumes the adapter chain, exactly
# as in Rust; Crabwalk does not materialize a Python list between the operations.
@rust.fn
def shifted_sum(offset: rust.u64) -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3])
    return values.iter().map(lambda value: value + offset).sum()


# Rust Book source (rewriting minigrep with iterator adapters):
# https://doc.rust-lang.org/book/ch13-03-improving-our-io-project.html#clarifying-code-with-iterator-adapters
#
# Chapter 12 keeps its loop version so both styles remain inspectable. This compact
# example counts matching lines without allocating the returned strings.
@rust.fn
def matching_line_count(query: rust.Str, contents: rust.Str) -> rust.usize:
    return contents.lines().filter(lambda line: line.contains(query)).count()
