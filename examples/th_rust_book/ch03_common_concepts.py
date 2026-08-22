"""Chapter 3: bindings, scalar/compound types, functions, and control flow."""

from crabwalk import rust


# Rust Book source:
# https://doc.rust-lang.org/book/ch03-01-variables-and-mutability.html
#
# A Crabwalk local assigned once emits immutable `let`. Reassignment makes that
# binding `let mut`. `rust.shadow(...)` emits a fresh Rust `let` and can therefore
# change type, while `rust.const(...)` emits an actual local Rust `const`.
@rust.fn
def binding_rules() -> rust.u32:
    THREE_HOURS_IN_SECONDS: rust.u32 = rust.const(60 * 60 * 3)
    value: rust.u32 = 5
    value: rust.u32 = rust.shadow(value + 1)
    return THREE_HOURS_IN_SECONDS + value


# Rust Book source:
# https://doc.rust-lang.org/book/ch03-02-data-types.html
#
# The tuple and fixed array are not Python containers in disguise. Their generated
# types are `(u64, u64, u64)` and `[u64; 5]`; indexing uses Rust `usize` values.
@rust.fn
def compound_types() -> rust.u64:
    inventory: rust.Tuple[rust.u64, rust.u64, rust.u64] = (500, 6, 1)
    price, quantity, category = inventory
    values: rust.Array[rust.u64, 5] = [1, 2, 3, 4, 5]
    repeated: rust.Array[rust.u64, 5] = rust.repeat(3, 5)
    return price + quantity + category + values[4] + repeated[2]


# Rust Book source (Unicode scalar values / `char`):
# https://doc.rust-lang.org/book/ch03-02-data-types.html#the-character-type
#
# Python has no separate character syntax, so Crabwalk context-checks a one-character
# string literal and lowers it to Rust `char`, including a four-byte Unicode scalar.
@rust.fn
def is_crab(value: rust.char) -> rust.bool:
    mascot: rust.char = "🦀"
    return value == mascot


# Rust Book sources:
# https://doc.rust-lang.org/book/ch03-03-how-functions-work.html
# https://doc.rust-lang.org/book/ch03-05-control-flow.html
#
# Parameters, expressions, while loops, range loops, break, and continue all lower
# directly. The sum is intentionally explicit so generated Rust is easy to inspect.
@rust.fn
def sum_odd_below(stop: rust.u64) -> rust.u64:
    total: rust.u64 = 0
    for value in range(stop):
        if value % 2 == 0:
            continue
        total += value
    return total


@rust.fn
def countdown_sum(start: rust.u64) -> rust.u64:
    value: rust.u64 = start
    total: rust.u64 = 0
    while value > 0:
        total += value
        value -= 1
    return total
