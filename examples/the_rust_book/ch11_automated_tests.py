"""Chapter 11: small native units designed to be exercised by pytest."""

from crabwalk import rust


# Rust Book source (`assert_eq!` around `add_two`):
# https://doc.rust-lang.org/book/ch11-01-writing-tests.html#testing-equality-with-the-assert_eq-and-assert_ne-macros
@rust.fn
def add_two(value: rust.u64) -> rust.u64:
    return value + 2


# Rust Book source (`Rectangle::can_hold` tests):
# https://doc.rust-lang.org/book/ch11-01-writing-tests.html#checking-results-with-the-assert-macro
#
# The test behavior matters here, so dimensions are passed directly. Chapter 5's
# `Rectangle` example separately demonstrates generated Rust domain storage.
@rust.fn
def can_hold_dimensions(
    outer_width: rust.u32,
    outer_height: rust.u32,
    inner_width: rust.u32,
    inner_height: rust.u32,
) -> rust.bool:
    return outer_width > inner_width and outer_height > inner_height


# Rust Book source (custom assertion messages):
# https://doc.rust-lang.org/book/ch11-01-writing-tests.html#adding-custom-failure-messages
@rust.fn
def greeting(name: rust.Str) -> rust.String:
    message: rust.String = rust.String("Hello ")
    message.push_str(name)
    return message


# Rust Book source (`should_panic(expected = ...)`):
# https://doc.rust-lang.org/book/ch11-01-writing-tests.html#using-should_panic-with-an-expected-message
@rust.fn
def guarded_value(value: rust.u64) -> rust.u64:
    if value < 1:
        return rust.panic("value must be at least 1")
    return value
