"""Chapter 20: unsafe Rust, advanced traits/types/functions, and macros.

These examples keep unsafe code narrow and inspectable. The Python-facing helper
names are deliberately explicit (for example, ``rust.unsafe_read``), while the
generated crate contains the raw pointers, unsafe blocks, trait implementations,
function-pointer types, closure trait objects, aliases, and macro invocations the
chapter teaches.
"""

from crabwalk import rust


# Rust Book sources (raw pointers and unsafe dereferencing; Listings 20-1 to
# 20-3):
# https://doc.rust-lang.org/book/ch20-01-unsafe-rust.html#dereferencing-a-raw-pointer
#
# Both intrinsics only accept a named Copy local. Crabwalk emits `&raw const` or
# `&raw mut`, then isolates the dereference in an `unsafe` block. The restriction
# deliberately excludes Listing 20-2's arbitrary address from dereferencing: the
# Book constructs address 0x012345usize as a pointer but correctly warns that an
# arbitrary pointer must not be read without a validity proof.
@rust.fn
def raw_pointer_demo() -> rust.u64:
    value: rust.u64 = 5
    before: rust.u64 = rust.unsafe_read(value)
    rust.unsafe_write(value, 9)
    after: rust.u64 = rust.unsafe_read(value)
    return before * 10 + after


# Rust Book source (a safe abstraction implemented with unsafe internals;
# Listings 20-4 through 20-7):
# https://doc.rust-lang.org/book/ch20-01-unsafe-rust.html#creating-a-safe-abstraction-over-unsafe-code
#
# `split_at_mut_sum` bounds-checks `mid`, obtains Vec::as_mut_ptr, creates two
# nonoverlapping slices with `from_raw_parts_mut`, and uses them only inside the
# generated expression. The public result is a value, so neither unsafe borrow can
# escape its validity proof. Inspect `crabwalk expand` to see the complete block.
@rust.fn
def unsafe_split_total() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3, 4])
    return values.split_at_mut_sum(2)


# Rust Book sources (calling external code; Listings 20-8 and 20-9):
# https://doc.rust-lang.org/book/ch20-01-unsafe-rust.html#using-extern-functions-to-call-external-code
#
# The generated crate declares C's `abs` in an `unsafe extern "C"` block. It
# rejects i32::MIN before entering C because that value's positive magnitude is
# not representable and C defines the call as undefined behavior. Other values
# cross the focused unsafe FFI boundary normally.
@rust.fn
def ffi_absolute(value: rust.i32) -> rust.i32:
    return rust.c_abs(value)


# Rust Book sources (immutable and mutable statics; Listings 20-10 and 20-11):
# https://doc.rust-lang.org/book/ch20-01-unsafe-rust.html#accessing-or-modifying-a-mutable-static-variable
#
# A literal `static mut` would make Crabwalk's safe Python API capable of causing a
# Rust data race. The reviewed teaching spelling therefore emits AtomicU64 with a
# checked Relaxed update: it still demonstrates global state while keeping every
# safe caller sound. Arc<Mutex<T>> remains the richer Chapter 16 shared-state model.
@rust.fn
def unsafe_static_counter(amount: rust.u64) -> rust.u64:
    return rust.unsafe_static_increment(amount)


# Rust Book sources (unsafe traits, unions, Miri, and correctness discipline):
# https://doc.rust-lang.org/book/ch20-01-unsafe-rust.html#implementing-an-unsafe-trait
# https://doc.rust-lang.org/book/ch20-01-unsafe-rust.html#accessing-fields-of-a-union
# https://doc.rust-lang.org/book/ch20-01-unsafe-rust.html#using-miri-to-check-unsafe-code
# https://doc.rust-lang.org/book/ch20-01-unsafe-rust.html#using-unsafe-code-correctly
#
# Crabwalk does not expose a blanket arbitrary-unsafe escape hatch, unsafe trait
# declaration, or union field API. Those features require user-written safety
# invariants that a Python AST cannot infer. The focused operations above retain
# the Book's key rule: unsafe enables five extra operations; it does not disable
# borrow checking or turn invalid memory into valid memory. Generated Rust remains
# available for `cargo +nightly miri test` once a project supplies Miri fixtures.


# Rust Book source (Iterator's associated Item type; Listings 20-13 and 20-14):
# https://doc.rust-lang.org/book/ch20-02-advanced-traits.html#defining-traits-with-associated-types
#
# Vec.iter() produces a real std::slice::Iter whose `Iterator::Item` associated
# type is fixed by rustc. Crabwalk tracks that Item in TypeRef so each adapter and
# the final sum remain statically typed without asking callers to choose it again.
@rust.fn
def associated_item_demo() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3])
    return values.iter().map(lambda value: value + 1).sum()


@rust.struct
class AdvancedPoint:
    x: rust.i64
    y: rust.i64


# Rust Book source (default generic parameters and Add; Listing 20-15):
# https://doc.rust-lang.org/book/ch20-02-advanced-traits.html#using-default-generic-parameters-and-operator-overloading
#
# @rust.operator emits `impl Add<AdvancedPoint> for AdvancedPoint` with an
# associated Output type. The Python `+` is accepted only because this visible,
# statically checked implementation exists for the left and right domain types.
@rust.operator(AdvancedPoint, name="add")
def add_advanced_points(
    left: rust.Owned[AdvancedPoint], right: AdvancedPoint
) -> AdvancedPoint:
    return AdvancedPoint(x=left.x + right.x, y=left.y + right.y)


@rust.fn
def point_operator_demo() -> rust.i64:
    left: AdvancedPoint = AdvancedPoint(x=1, y=2)
    right: AdvancedPoint = AdvancedPoint(x=3, y=4)
    combined: AdvancedPoint = left + right
    return combined.x * 10 + combined.y


@rust.struct
class Millimeters:
    value: rust.u64


@rust.struct
class Meters:
    value: rust.u64


# Rust Book source (choosing a nondefault Add RHS; Listing 20-16):
# https://doc.rust-lang.org/book/ch20-02-advanced-traits.html#using-default-generic-parameters-and-operator-overloading
#
# The two newtypes prevent unit confusion. Generated Rust implements Add<Meters>
# for Millimeters and returns Millimeters as its associated Output.
@rust.operator(Millimeters, name="add")
def add_metric_lengths(left: rust.Owned[Millimeters], right: Meters) -> Millimeters:
    return Millimeters(value=left.value + right.value * 1000)


@rust.fn
def metric_operator_demo() -> rust.u64:
    millimeters: Millimeters = Millimeters(value=500)
    meters: Meters = Meters(value=2)
    combined: Millimeters = millimeters + meters
    return combined.value


Pilot = rust.trait("Pilot", fly=rust.u64)
Wizard = rust.trait("Wizard", fly=rust.u64)


@rust.struct
class Human:
    marker: rust.u64


@rust.impl(Pilot, Human, name="fly")
def pilot_fly(human: rust.Ref[Human]) -> rust.u64:
    return 1


@rust.impl(Wizard, Human, name="fly")
def wizard_fly(human: rust.Ref[Human]) -> rust.u64:
    return 2


@rust.method(Human, name="fly")
def human_fly(human: rust.Ref[Human]) -> rust.u64:
    return 3


# Rust Book sources (same-named methods and fully qualified syntax; Listings
# 20-17 through 20-22):
# https://doc.rust-lang.org/book/ch20-02-advanced-traits.html#disambiguating-between-identically-named-methods
#
# `person.fly()` selects the inherent method. `rust.trait_call` emits UFCS such as
# `<Human as Pilot>::fly(&person)`, preserving precisely which implementation the
# call intends even though all three Rust methods have the name `fly`.
@rust.fn
def trait_disambiguation_demo() -> rust.u64:
    person: Human = Human(marker=0)
    return (
        rust.trait_call(Pilot, person, "fly") * 100
        + rust.trait_call(Wizard, person, "fly") * 10
        + person.fly()
    )


# Rust Book sources (supertraits and the newtype pattern; Listings 20-23 and
# 20-24):
# https://doc.rust-lang.org/book/ch20-02-advanced-traits.html#using-supertraits
# https://doc.rust-lang.org/book/ch20-02-advanced-traits.html#implementing-external-traits-with-the-newtype-pattern
#
# Millimeters/Meters above are the newtype solution to Rust's orphan rule. For a
# required capability, Crabwalk's generic bound produces the same `T: Display`
# obligation a supertrait would inherit; rustc, not Crabwalk, proves the bound.
DisplayValue = rust.typevar("DisplayValue")


@rust.generic(DisplayValue, bounds=[rust.Display])
def display_preserving(value: DisplayValue) -> DisplayValue:
    return value


@rust.fn
def display_bound_demo() -> rust.u64:
    value: rust.u64 = 42
    return display_preserving(value)


# Rust Book sources (newtypes, aliases, never, and dynamically sized types):
# https://doc.rust-lang.org/book/ch20-03-advanced-types.html#type-safety-and-abstraction-with-the-newtype-pattern
# https://doc.rust-lang.org/book/ch20-03-advanced-types.html#type-synonyms-and-type-aliases
# https://doc.rust-lang.org/book/ch20-03-advanced-types.html#the-never-type-that-never-returns
# https://doc.rust-lang.org/book/ch20-03-advanced-types.html#dynamically-sized-types-and-the-sized-trait
#
# `type_alias_identity` creates a local Rust `type` item and typed binding. The
# continue arm below has type `!`, which coerces to the surrounding arm type. The
# borrowed `rust.Str` parameter is a fat pointer (`&str`); its size is known even
# though bare `str` is dynamically sized.
@rust.fn
def type_alias_demo(value: rust.u64) -> rust.u64:
    return rust.type_alias_identity(value)


@rust.fn
def never_coercion_demo() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3])
    total: rust.u64 = 0
    for value in values.iter():
        match value:
            case 2:
                continue
            case _:
                total += value
    return total


@rust.fn
def dynamically_sized_string_length(value: rust.Str) -> rust.usize:
    return value.len()


@rust.fn
def add_one_advanced(value: rust.u64) -> rust.u64:
    return value + 1


# Rust Book sources (function pointers and returned closures; Listings 20-28
# through 20-34):
# https://doc.rust-lang.org/book/ch20-04-advanced-functions-and-closures.html#function-pointers
# https://doc.rust-lang.org/book/ch20-04-advanced-functions-and-closures.html#returning-closures
#
# call_twice emits a local `fn(u64) -> u64` pointer. boxed_closure_call defines a
# helper returning `Box<dyn Fn(u64) -> u64>`, and closure_vector_total stores two
# closure types behind the same trait-object type in a Vec.
@rust.fn
def function_pointer_demo(value: rust.u64) -> rust.u64:
    return rust.call_twice(add_one_advanced, value)


@rust.fn
def returned_closure_demo(value: rust.u64) -> rust.u64:
    return rust.boxed_closure_call(value, 3)


@rust.fn
def heterogeneous_closure_demo(value: rust.u64) -> rust.u64:
    return rust.closure_vector_total(value)


# Rust Book sources (declarative and procedural macros; Listings 20-35 through
# 20-42 plus attribute-like and function-like macro forms):
# https://doc.rust-lang.org/book/ch20-05-macros.html#declarative-macros-for-general-metaprogramming
# https://doc.rust-lang.org/book/ch20-05-macros.html#procedural-macros-for-generating-code-from-attributes
# https://doc.rust-lang.org/book/ch20-05-macros.html#custom-derive-macros
# https://doc.rust-lang.org/book/ch20-05-macros.html#attribute-like-macros
# https://doc.rust-lang.org/book/ch20-05-macros.html#function-like-macros
#
# rust.Vec([...]) emits the real declarative `vec![...]` macro. The generated
# extension already uses PyO3's attribute procedural macros (`#[pyfunction]`,
# `#[pyclass]`, and `#[pymodule]`) throughout. Defining a new proc-macro crate is a
# separate Cargo package concern, so this chapter demonstrates consuming generated
# macro output while linking directly to the Book's multi-crate definition steps.
@rust.fn
def macro_vector_total() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3, 4])
    return values.iter().sum()
