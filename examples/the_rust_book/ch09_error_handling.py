"""Chapter 9: panic containment, Result values, expect, and propagation."""

from crabwalk import rust


# Rust Book source:
# https://doc.rust-lang.org/book/ch09-02-recoverable-errors-with-result.html
#
# Exported `Err(String)` becomes `CrabwalkRustError`; `Ok` converts normally.
@rust.fn
def require_nonzero(value: rust.u64) -> rust.Result[rust.u64, rust.String]:
    if value == 0:
        return rust.Err("value must not be zero")
    return rust.Ok(value)


# Rust Book source (`?` propagation):
# https://doc.rust-lang.org/book/ch09-02-recoverable-errors-with-result.html#a-shortcut-for-propagating-errors-the--operator
#
# `rust.try_(...)` is the Python-valid spelling of postfix Rust `?`. This version
# follows Listing 9-7 instead of substituting a synthetic validator:
#
# * `rust.File.open(path)` emits `std::fs::File::open(path)`.
# * `File.read_to_string()` is a typed Crabwalk adapter around
#   `std::io::Read::read_to_string`. It owns the destination `String` internally
#   and returns `Result[String, IoError]`.
# * Each `rust.try_` unwraps `Ok` or immediately returns the real `io::Error`.
#
# Crabwalk currently requires the operand and enclosing function to use the same
# error type; it does not yet model arbitrary `From` conversions performed by `?`.
@rust.fn
def read_username_from_file(
    path: rust.Str,
) -> rust.Result[rust.String, rust.IoError]:
    username_file: rust.File = rust.try_(rust.File.open(path))
    username: rust.String = rust.try_(username_file.read_to_string())
    return rust.Ok(username)


# Rust Book source (propagating and composing Result values):
# https://doc.rust-lang.org/book/ch09-02-recoverable-errors-with-result.html#propagating-errors
#
# The expected local type selects Rust's `parse::<u64>()`. `and_then` receives a
# typed closure returning the same `Result[_, String]` error family, so parsing and
# semantic validation remain one recoverable native pipeline.
@rust.fn
def parse_nonzero(text: rust.Str) -> rust.Result[rust.u64, rust.String]:
    parsed: rust.Result[rust.u64, rust.String] = text.trim().parse()
    return parsed.and_then(lambda number: require_nonzero(number))


# Rust Book source (`match` over Result):
# https://doc.rust-lang.org/book/ch09-02-recoverable-errors-with-result.html#matching-on-different-errors
#
# Result is a real typed sum in pattern position. This helper keeps both branches
# inside Rust and returns an ordinary value, making recovery visible without an
# exception crossing the Python boundary.
@rust.fn
def nonzero_or_default(value: rust.u64, fallback: rust.u64) -> rust.u64:
    checked: rust.Result[rust.u64, rust.String] = require_nonzero(value)
    match checked:
        case rust.Ok(number):
            return number
        case rust.Err(_):
            return fallback


# `map` transforms only Ok; `unwrap_or` supplies a value only for Err. The adapter
# chain is lazy native control flow, not Python exception handling.
@rust.fn
def doubled_nonzero_or_zero(value: rust.u64) -> rust.u64:
    return require_nonzero(value).map(lambda number: number * 2).unwrap_or(0)


# Rust Book source:
# https://doc.rust-lang.org/book/ch09-01-unrecoverable-errors-with-panic.html
#
# The generated Rust really panics. Crabwalk catches the unwind before it crosses
# PyO3 and raises `CrabwalkPanicError` in Python.
@rust.fn
def panic_on_zero(value: rust.u64) -> rust.u64:
    if value == 0:
        return rust.panic("zero is not accepted")
    return value


# Rust Book source (`expect`):
# https://doc.rust-lang.org/book/ch09-02-recoverable-errors-with-result.html#shortcuts-for-panic-on-error-unwrap-and-expect
@rust.fn
def expect_nonzero(value: rust.u64) -> rust.u64:
    return require_nonzero(value).expect("expected a nonzero value")
