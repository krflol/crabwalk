"""Chapter 5: generated Rust structs and functions over borrowed values."""

from crabwalk import rust


# Rust Book source:
# https://doc.rust-lang.org/book/ch05-01-defining-structs.html
#
# This valid Python class declaration becomes a concrete Rust struct plus a
# move-aware Python constructor. Field reads/writes operate on Rust-owned storage.
@rust.struct
class Rectangle:
    width: rust.u32
    height: rust.u32


# Rust Book sources:
# https://doc.rust-lang.org/book/ch05-02-example-structs.html
# https://doc.rust-lang.org/book/ch05-03-method-syntax.html
#
# Crabwalk's current spelling keeps these as native free functions with explicit
# `Ref[Rectangle]`; they preserve the Book's borrow semantics and compile to direct
# Rust field access. A method-declaration surface is a later Book-evolution wave.
@rust.fn
def rectangle_area(rectangle: rust.Ref[Rectangle]) -> rust.u32:
    return rectangle.width * rectangle.height


@rust.fn
def can_hold(outer: rust.Ref[Rectangle], inner: rust.Ref[Rectangle]) -> rust.bool:
    return outer.width > inner.width and outer.height > inner.height


@rust.fn
def square_area(size: rust.u32) -> rust.u32:
    square: Rectangle = Rectangle(width=size, height=size)
    return square.width * square.height
