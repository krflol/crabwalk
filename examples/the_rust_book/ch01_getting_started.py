"""Chapter 1: getting started with one genuinely native function."""

from crabwalk import rust


# Rust Book source:
# https://doc.rust-lang.org/book/ch01-02-hello-world.html
#
# The Book uses `println!`; Crabwalk spells the native macro boundary
# `rust.println(...)`. This is deliberately different from Python's `print`, which
# is a visible Python-runtime effect and would keep/reacquire the GIL.
@rust.fn
def hello_world() -> None:
    rust.println("Hello, world!")
