"""Chapter 10: native generics, trait bounds, and named lifetimes."""

from crabwalk import rust


# Rust Book sources:
# https://doc.rust-lang.org/book/ch10-01-syntax.html#in-function-definitions
# https://doc.rust-lang.org/book/ch10-02-traits.html#traits-as-parameters
#
# `T` is a genuine Rust type parameter, not `typing.TypeVar`. The helper is
# native-only because a Python extension ABI must have concrete argument types.
# The exported functions below provide those concrete types; rustc then performs
# ordinary monomorphization for `u64` and `char`.
T = rust.typevar("T")


@rust.generic(T, bounds=[rust.PartialOrd, rust.Copy])
def largest(values: rust.Ref[rust.Vec[T]]) -> T:
    index: rust.usize = 1
    largest_value: T = values[0]
    while index < values.len():
        candidate: T = values[index]
        if candidate > largest_value:
            largest_value = candidate
        index += 1
    return largest_value


@rust.fn
def largest_number() -> rust.u64:
    numbers: rust.Vec[rust.u64] = rust.Vec([34, 50, 25, 100, 65])
    return largest(numbers)


@rust.fn
def largest_character() -> rust.char:
    characters: rust.Vec[rust.char] = rust.Vec(["y", "m", "a", "q"])
    return largest(characters)


# Rust Book source:
# https://doc.rust-lang.org/book/ch10-03-lifetime-syntax.html#generic-lifetimes-in-functions
#
# The lowercase marker becomes Rust lifetime `'a`. Both parameters and the return
# type use that same lifetime, expressing the relationship that the returned slice
# cannot outlive either input. `longest` remains internal because returning a
# borrowed slice directly to Python would let it escape its Rust borrow. The public
# wrapper copies the chosen slice into an owned `String` at the boundary.
a = rust.lifetime("a")


@rust.generic(a)
def longest(
    left: rust.Borrow[a, rust.Str],
    right: rust.Borrow[a, rust.Str],
) -> rust.Borrow[a, rust.Str]:
    if left.len() > right.len():
        return left
    return right


@rust.fn
def longest_owned(left: rust.Str, right: rust.Str) -> rust.String:
    return rust.String(longest(left, right))
