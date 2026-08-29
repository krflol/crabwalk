"""Chapter 5: generated Rust structs, methods, and owned domain returns."""

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
# `@rust.method` emits an inherent Rust method. The first ownership annotation
# selects `&self`, `&mut self`, or `self`; these two shared receivers therefore
# preserve the Book's borrowing contract rather than copying a Rectangle.
@rust.method(Rectangle, name="area")
def rectangle_area_method(rectangle: rust.Ref[Rectangle]) -> rust.u32:
    return rectangle.width * rectangle.height


@rust.method(Rectangle, name="can_hold")
def rectangle_can_hold_method(
    outer: rust.Ref[Rectangle], inner: rust.Ref[Rectangle]
) -> rust.bool:
    return outer.width > inner.width and outer.height > inner.height


# Exported wrappers make the method results callable from Python while the actual
# dispatch and field access stay inside generated Rust.
@rust.fn
def rectangle_area(rectangle: rust.Ref[Rectangle]) -> rust.u32:
    return rectangle.area()


@rust.fn
def can_hold(outer: rust.Ref[Rectangle], inner: rust.Ref[Rectangle]) -> rust.bool:
    return outer.can_hold(inner)


@rust.fn
def square_area(size: rust.u32) -> rust.u32:
    square: Rectangle = Rectangle(width=size, height=size)
    return square.area()


# Rust Book source (associated `square` constructor):
# https://doc.rust-lang.org/book/ch05-03-method-syntax.html#associated-functions
#
# Crabwalk exposes the constructor as an exported factory because static inherent
# methods do not need a Python-specific syntax. `Owned[Rectangle]` returns the real
# native allocation as a move-aware handle instead of flattening it into a dict.
@rust.fn
def make_square(size: rust.u32) -> rust.Owned[Rectangle]:
    return Rectangle(width=size, height=size)
