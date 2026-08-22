"""Chapter 19: patterns and matching, expressed as native Crabwalk Rust.

Python's ``match`` syntax supplies the readable surface notation. Crabwalk checks
each pattern against the subject's Rust type, records the bindings in the arm's
scope, and emits a real exhaustive Rust ``match``. A few Rust spellings need an
explicit bridge: ``rust.Range(a, b)`` means the inclusive pattern ``a..=b``, and
Python's ``pattern as name`` becomes Rust's ``name @ pattern``.
"""

from crabwalk import rust


# Rust Book sources (let, for-loop, and function-parameter patterns; Listings
# 19-1 and 19-5 through 19-7):
# https://doc.rust-lang.org/book/ch19-01-all-the-places-for-patterns.html#let-statements
# https://doc.rust-lang.org/book/ch19-01-all-the-places-for-patterns.html#for-loops
# https://doc.rust-lang.org/book/ch19-01-all-the-places-for-patterns.html#function-parameters
#
# An annotated tuple assignment is lowered directly to `let (x, y, z) = ...`.
# Tuple targets in a Python `for` statement similarly become the pattern after
# Rust's `for`. Python no longer permits tuple patterns in a function signature,
# so the final example destructures immediately inside the function instead.
@rust.fn
def tuple_binding_total() -> rust.u64:
    coordinates: rust.Tuple[rust.u64, rust.u64, rust.u64] = (1, 2, 3)
    x, y, z = coordinates
    return x + y + z


@rust.fn
def tuple_loop_total() -> rust.u64:
    indexed_values: rust.Vec[rust.Tuple[rust.u64, rust.u64]] = rust.Vec(
        [(0, 10), (1, 20), (2, 30)]
    )
    weighted: rust.u64 = 0
    for index, value in indexed_values.iter():
        weighted += index + value
    return weighted


@rust.fn
def destructured_parameter_total(
    point: rust.Tuple[rust.u64, rust.u64],
) -> rust.u64:
    x, y = point
    return x + y


# Rust Book sources (`if let`, `while let`, and refutability; Listings 19-3,
# 19-4, and 19-8 through 19-10):
# https://doc.rust-lang.org/book/ch19-01-all-the-places-for-patterns.html#conditional-if-let-expressions
# https://doc.rust-lang.org/book/ch19-01-all-the-places-for-patterns.html#while-let-conditional-loops
# https://doc.rust-lang.org/book/ch19-02-refutability.html
#
# Python has no `if let` or `let ... else` grammar. An exhaustive match preserves
# the same refutable/irrefutable distinction and lets rustc verify both outcomes.
@rust.fn
def option_or_else(value: rust.Option[rust.u64], fallback: rust.u64) -> rust.u64:
    match value:
        case rust.Some(inner):
            return inner
        case None:
            return fallback


@rust.fn
def while_some_total() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3])
    total: rust.u64 = 0
    while not values.is_empty():
        # This match is the Crabwalk spelling of `while let Some(value) = pop()`.
        # The None arm remains explicit because a Python while condition cannot
        # introduce a statically typed pattern binding.
        current: rust.Option[rust.u64] = values.pop()
        match current:
            case rust.Some(value):
                total += value
            case None:
                break
    return total


# Rust Book sources (literal, named, or, and inclusive-range patterns):
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#matching-literals
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#matching-named-variables
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#matching-multiple-patterns
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#matching-ranges-of-values-with
#
# `case 1 | 2` maps directly to a Rust or-pattern. `rust.Range` is compiler-only:
# no Python helper executes at runtime; it is replaced by a checked Rust range.
@rust.fn
def literal_or_range(value: rust.u64) -> rust.u64:
    match value:
        case 1 | 2:
            return 10
        case rust.Range(3, 7) as matched:
            return matched
        case _:
            return 0


@rust.fn
def character_band(value: rust.char) -> rust.u64:
    match value:
        case "a" | "b":
            return 1
        case rust.Range("c", "f"):
            return 2
        case _:
            return 0


@rust.struct
class PatternPoint:
    x: rust.u64
    y: rust.u64
    z: rust.u64


# Rust Book sources (destructuring structs and mixed nested values; Listings
# 19-13, 19-14, and the example after Listing 19-16):
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#destructuring-structs
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#destructuring-structs-and-tuples
#
# Named class-pattern arguments become Rust record fields. Omitting y and z adds
# `..` in generated Rust, so point_x_only demonstrates selective destructuring.
@rust.fn
def point_region(x: rust.u64, y: rust.u64) -> rust.u64:
    point: PatternPoint = PatternPoint(x=x, y=y, z=99)
    match point:
        case PatternPoint(x=0, y=y_value):
            return y_value
        case PatternPoint(x=x_value, y=0):
            return x_value
        case PatternPoint(x=x_value, y=y_value) if x_value == y_value:
            return x_value * 2
        case PatternPoint(x=x_value, y=y_value):
            return x_value + y_value


@rust.fn
def point_x_only(x: rust.u64, y: rust.u64, z: rust.u64) -> rust.u64:
    point: PatternPoint = PatternPoint(x=x, y=y, z=z)
    match point:
        case PatternPoint(x=x_value):
            return x_value


@rust.fn
def mixed_destructure() -> rust.u64:
    value: rust.Tuple[
        rust.Tuple[rust.u64, rust.u64],
        PatternPoint,
    ] = ((3, 10), PatternPoint(x=3, y=5, z=8))
    match value:
        case ((feet, inches), PatternPoint(x=x, y=y, z=z)):
            return feet + inches + x + y + z


@rust.enum
class PatternColor:
    Rgb = rust.variant(rust.u64, rust.u64, rust.u64)
    Hsv = rust.variant(rust.u64, rust.u64, rust.u64)


@rust.enum
class PatternMessage:
    Quit = rust.variant()
    Move = rust.variant(x=rust.u64, y=rust.u64)
    Write = rust.variant(rust.String)
    ChangeColor = rust.variant(PatternColor)


# Rust Book sources (enum and nested-enum destructuring; Listings 19-15 and
# 19-16):
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#enums
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#nested-structs-and-enums
#
# PatternColor is a typed payload of PatternMessage. This required Crabwalk's
# enum model to evolve beyond primitive-only fields; generated Rust now retains
# the nested enum and lets rustc check the full pattern tree for exhaustiveness.
@rust.fn
def nested_color_total(
    hue: rust.u64, saturation: rust.u64, value: rust.u64
) -> rust.u64:
    color: PatternColor = PatternColor.Hsv(hue, saturation, value)
    message: PatternMessage = PatternMessage.ChangeColor(color)
    match message:
        case PatternMessage.ChangeColor(PatternColor.Rgb(red, green, blue)):
            return red + green + blue
        case PatternMessage.ChangeColor(PatternColor.Hsv(h, s, v)):
            return h + s + v
        case PatternMessage.Move(x=x, y=y):
            return x + y
        case PatternMessage.Write(_):
            return 1
        case PatternMessage.Quit:
            return 0


# Rust Book sources (wildcards, nested `_`, and `..`; Listings 19-17 through
# 19-25):
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#ignoring-values-in-a-pattern
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#remaining-parts-of-a-value-with
#
# `_` never binds. Python writes the unambiguous tuple rest pattern as `*_`;
# Crabwalk emits Rust's `..` and rejects multiple or ambiguous rest positions.
@rust.fn
def ignored_parts_total() -> rust.u64:
    values: rust.Tuple[
        rust.u64,
        rust.u64,
        rust.u64,
        rust.u64,
        rust.u64,
    ] = (2, 4, 8, 16, 32)
    match values:
        case (first, _, third, _, fifth):
            return first + third + fifth


@rust.fn
def tuple_ends(first: rust.u64, last: rust.u64) -> rust.u64:
    values: rust.Tuple[
        rust.u64,
        rust.u64,
        rust.u64,
        rust.u64,
    ] = (first, 20, 30, last)
    match values:
        case (head, *_, tail):
            return head + tail


@rust.fn
def setting_can_change(
    current: rust.Option[rust.u64], proposed: rust.Option[rust.u64]
) -> rust.bool:
    pair: rust.Tuple[rust.Option[rust.u64], rust.Option[rust.u64]] = (current, proposed)
    match pair:
        case (rust.Some(_), rust.Some(_)):
            return False
        case _:
            return True


# Rust Book sources (match guards and their precedence; Listings 19-26 through
# 19-28):
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#adding-conditionals-with-match-guards
#
# Arm bindings are added to the guard's static environment before lowering it.
# The final example proves a guard applies to the whole `4 | 5 | 6` pattern.
@rust.fn
def guarded_option(value: rust.Option[rust.u64], target: rust.u64) -> rust.u64:
    match value:
        case rust.Some(number) if number == target:
            return number
        case rust.Some(number) if number % 2 == 0:
            return number + 100
        case rust.Some(number):
            return number
        case None:
            return 0


@rust.fn
def or_pattern_guard(value: rust.u64, enabled: rust.bool) -> rust.bool:
    match value:
        case 4 | 5 | 6 if enabled:
            return True
        case _:
            return False


@rust.enum
class IdMessage:
    Hello = rust.variant(id=rust.u64)


# Rust Book source (`@` bindings, Listing 19-29):
# https://doc.rust-lang.org/book/ch19-03-pattern-syntax.html#using-bindings
#
# Python's `pattern as captured` reads in the opposite order from Rust's
# `captured @ pattern`; the IR stores the binding type and emits the Rust order.
@rust.fn
def captured_id(identifier: rust.u64) -> rust.u64:
    message: IdMessage = IdMessage.Hello(id=identifier)
    match message:
        case IdMessage.Hello(id=rust.Range(3, 7) as found):
            return found
        case IdMessage.Hello(id=rust.Range(10, 12)):
            return 10
        case IdMessage.Hello(id=other):
            return other + 100
