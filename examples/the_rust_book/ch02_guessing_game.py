"""Chapter 2: the typed native core of the guessing-game tutorial."""

from crabwalk import rust


# Rust Book source:
# https://doc.rust-lang.org/book/ch02-00-guessing-game-tutorial.html
#
# Terminal input belongs to the ordinary Python shell in this adaptation. The
# comparison—the part whose integer types and branching semantics matter—is native
# Rust. Returning -1/0/1 makes the result easy for a Python UI to consume.
@rust.fn
def compare_guess(guess: rust.u32, secret: rust.u32) -> rust.i8:
    if guess < secret:
        return -1
    if guess > secret:
        return 1
    return 0


# Rust Book source (random secret-number section):
# https://doc.rust-lang.org/book/ch02-00-guessing-game-tutorial.html#generating-a-secret-number
#
# The Book introduces a random crate. This deterministic helper isolates the same
# inclusive 1..=100 domain rule, so examples and tests remain reproducible. Chapter
# 14 demonstrates Crabwalk's actual Cargo dependency surface.
@rust.fn
def secret_from_seed(seed: rust.u32) -> rust.u32:
    return (seed % 100) + 1
