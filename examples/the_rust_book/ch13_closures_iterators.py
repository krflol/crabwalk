"""Chapter 13: typed Rust closures, captures, and iterator adapters."""

from crabwalk import rust


# Rayon is not part of the standard library chapter, but it deliberately extends
# the same iterator vocabulary later in this file. The declaration becomes a
# normal Cargo dependency in the generated package.
rayon = rust.crate("rayon", version="1.12.0")


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


# Rust Book source (`shoes_in_size`, Listing 13-4):
# https://doc.rust-lang.org/book/ch13-02-iterators.html#methods-that-produce-other-iterators
#
# This is the Book's non-Copy domain example rather than another integer-only
# chain. Python explicitly constructs a native Vec<Shoe>; `into_iter` owns each
# Shoe, `filter` borrows it for the predicate, and the collected Vec crosses back
# as one move-aware `Owned[Vec[Shoe]]` handle.
@rust.struct
class Shoe:
    size: rust.u32
    style: rust.String


@rust.fn
def shoes_in_size(
    shoes: rust.Owned[rust.Vec[Shoe]], shoe_size: rust.u32
) -> rust.Owned[rust.Vec[Shoe]]:
    return shoes.into_iter().filter(lambda shoe: shoe.size == shoe_size).collect_vec()


# Rust Book source (adapter chains are lazy until consumed):
# https://doc.rust-lang.org/book/ch13-02-iterators.html#methods-that-produce-other-iterators
#
# Splitting the chain across locals is intentional: Crabwalk retains the semantic
# item/reference type while Rust infers each closure-bearing adapter's anonymous
# concrete type. Borrowed String methods auto-dereference exactly as they do in
# Rust.
@rust.fn
def normalize_active_rows(
    rows: rust.Ref[rust.Vec[rust.String]],
) -> rust.Vec[rust.String]:
    active = rows.iter_ref().filter(lambda row: row.contains("|active|"))
    normalized = active.map(lambda row: row.to_lowercase())
    return normalized.collect_vec()


# Rayon sources (`ParallelIterator` and `collect`):
# https://docs.rs/rayon/latest/rayon/iter/trait.ParallelIterator.html
# https://docs.rs/rayon/latest/rayon/iter/trait.FromParallelIterator.html
#
# The same non-Copy workload now changes only the execution source. `par_iter`
# borrows String rows across Rayon workers; filter/map/collect remain fully typed.
# The Owned input makes transfer at the Python boundary explicit and observable.
@rust.fn
def parallel_normalize_active_rows(
    rows: rust.Owned[rust.Vec[rust.String]],
) -> rust.Vec[rust.String]:
    active = rows.par_iter().filter(lambda row: row.contains("|active|"))
    normalized = active.map(lambda row: row.to_lowercase())
    return normalized.collect_vec()


# Rayon source (`IndexedParallelIterator::enumerate`):
# https://docs.rs/rayon/latest/rayon/iter/trait.IndexedParallelIterator.html#method.enumerate
#
# Vec.par_iter starts indexed, and copied/map preserve that capability. Crabwalk
# tracks it so enumerate is accepted here but rejected after an unindexed filter.
@rust.fn
def indexed_parallel_values(
    values: rust.Ref[rust.Vec[rust.u64]],
) -> rust.Vec[rust.Tuple[rust.usize, rust.u64]]:
    indexed = values.par_iter().copied().enumerate()
    return indexed.collect_vec()
