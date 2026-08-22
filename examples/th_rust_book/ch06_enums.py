"""Chapter 6: data-carrying enums and exhaustive match."""

from crabwalk import rust


# Rust Book source:
# https://doc.rust-lang.org/book/ch06-01-defining-an-enum.html
#
# Unit, tuple, and record variants share one generated Rust enum. Payload fields use
# owned Rust values so no hidden Python object crosses into the native match.
@rust.enum
class Message:
    Quit = rust.variant()
    Move = rust.variant(x=rust.i32, y=rust.i32)
    Write = rust.variant(rust.String)
    ChangeColor = rust.variant(rust.i32, rust.i32, rust.i32)


# Rust Book source:
# https://doc.rust-lang.org/book/ch06-02-match.html
#
# Python structural-match syntax is statically restricted to enum variants. rustc
# remains the final exhaustiveness checker, just as in the original Rust example.
@rust.fn
def message_weight(message: rust.Ref[Message]) -> rust.i32:
    match message:
        case Message.Quit:
            return 0
        case Message.Move(x=x, y=y):
            return x + y
        case Message.Write(_):
            return 1
        case Message.ChangeColor(red, green, blue):
            return red + green + blue


# Rust Book source (`Option<T>`):
# https://doc.rust-lang.org/book/ch06-01-defining-an-enum.html#the-option-enum-and-its-advantages-over-null-values
@rust.fn
def optional_or(value: rust.Option[rust.u64], fallback: rust.u64) -> rust.u64:
    return value.unwrap_or(fallback)
