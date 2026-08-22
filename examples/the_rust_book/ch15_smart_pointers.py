"""Chapter 15: Box, dereferencing, drop, Rc counts, and interior mutation."""

from crabwalk import rust


# Rust Book sources:
# https://doc.rust-lang.org/book/ch15-01-box.html
# https://doc.rust-lang.org/book/ch15-02-deref.html
#
# The local is an actual `Box<u64>` allocated on Rust's heap. `deref_copy` is an
# explicit Crabwalk spelling for copying a `Copy` value through `Deref`; generated
# Rust uses `*boxed` and does not call into Python.
@rust.fn
def boxed_value(value: rust.u64) -> rust.u64:
    boxed: rust.Box[rust.u64] = rust.Box(value)
    return boxed.deref_copy()


# Rust Book sources:
# https://doc.rust-lang.org/book/ch15-03-drop.html#dropping-a-value-early-with-stdmemdrop
# https://doc.rust-lang.org/book/ch15-04-rc.html
#
# `Rc.clone` increments the same Rust allocation's strong count. `rust.drop` emits
# `std::mem::drop`, so the second count proves the clone was destroyed early. The
# packed result 21 means "two owners before drop, one owner afterward."
@rust.fn
def rc_counts() -> rust.usize:
    original: rust.Rc[rust.u64] = rust.Rc(5)
    shared_copy: rust.Rc[rust.u64] = original.clone()
    before: rust.usize = original.strong_count()
    rust.drop(shared_copy)
    after: rust.usize = original.strong_count()
    return before * 10 + after


# Rust Book source (`RefCell<T>` and the interior-mutability pattern):
# https://doc.rust-lang.org/book/ch15-05-interior-mutability.html
#
# `cell` itself is immutable, yet `replace` mutates its contained value after a
# runtime borrow check. `borrow_copy` keeps that dynamic borrow within one generated
# expression, preventing a RefCell guard from escaping across the Python ABI.
@rust.fn
def interior_mutation() -> rust.u64:
    cell: rust.RefCell[rust.u64] = rust.RefCell(5)
    old: rust.u64 = cell.replace(10)
    return old + cell.borrow_copy()
