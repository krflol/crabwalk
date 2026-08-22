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
# `rust.try_(...)` is valid Python syntax that emits Rust's `?` operator. The caller
# and callee keep the same `Result<T, E>` error type, so rustc checks propagation.
@rust.fn
def increment_nonzero(value: rust.u64) -> rust.Result[rust.u64, rust.String]:
    checked: rust.u64 = rust.try_(require_nonzero(value))
    return rust.Ok(checked + 1)


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
