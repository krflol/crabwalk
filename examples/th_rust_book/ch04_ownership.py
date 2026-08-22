"""Chapter 4: ownership, borrowing, mutation, and slice-like string borrows."""

from crabwalk import rust


# Rust Book source:
# https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html
#
# `Ref`, `Mut`, and `Owned` are explicit at the Python/native boundary. They become
# `&T`, `&mut T`, and `T` in the generated native signature; no Python list is
# silently copied. The Python handle records moves and call-scoped borrow conflicts.
@rust.fn
def vector_length(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()


@rust.fn
def append_value(values: rust.Mut[rust.Vec[rust.u64]], value: rust.u64) -> None:
    values.push(value)


@rust.fn
def consume_vector(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()


# Rust Book source:
# https://doc.rust-lang.org/book/ch04-03-slices.html
#
# `rust.Str` is a call-scoped `&str`. `find` returns `Option<usize>` and avoids
# manufacturing an escaping borrowed substring; the returned length remains valid.
@rust.fn
def first_word_length(text: rust.Str) -> rust.usize:
    boundary: rust.Option[rust.usize] = text.find(" ")
    return boundary.unwrap_or(text.len())
