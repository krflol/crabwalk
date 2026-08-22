"""Chapter 7: one package-wide native crate with module-to-module calls."""

from crabwalk import rust

from .ch05_structs import Rectangle, rectangle_area


# Rust Book source:
# https://doc.rust-lang.org/book/ch07-05-separating-modules-into-different-files.html
#
# The Python modules stay ordinary importable files. Crabwalk resolves this relative
# import statically and emits one native Cargo crate; the call never re-enters Python.
@rust.fn
def area_through_module(rectangle: rust.Ref[Rectangle]) -> rust.u32:
    return rectangle_area(rectangle)
