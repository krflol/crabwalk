"""Chapter 8: Vec, String, and HashMap backed by standard Rust collections."""

from crabwalk import rust


# Rust Book source:
# https://doc.rust-lang.org/book/ch08-01-vectors.html
#
# A local `rust.Vec[T]` is emitted as `Vec<T>`. Indexing is checked by Rust and a
# bounds panic is contained by Crabwalk's ABI panic boundary.
@rust.fn
def vector_total() -> rust.u64:
    values: rust.Vec[rust.u64] = rust.Vec([1, 2, 3, 4, 5])
    index: rust.usize = 0
    total: rust.u64 = 0
    while index < values.len():
        total += values[index]
        index += 1
    return total


# Rust Book source:
# https://doc.rust-lang.org/book/ch08-02-strings.html
#
# `String` is owned and mutable; `Str` is borrowed. `push_str`, `contains`, and
# `replace` call the standard Rust methods rather than Python string operations.
@rust.fn
def greeting(name: rust.Str) -> rust.String:
    text: rust.String = rust.String("Hello, ")
    text.push_str(name)
    return text


@rust.fn
def normalize_greeting(text: rust.Str) -> rust.String:
    if text.contains("world"):
        return text.replace("world", "Rust")
    return rust.String(text)


# Rust Book source:
# https://doc.rust-lang.org/book/ch08-03-hash-maps.html
#
# The map is a real `std::collections::HashMap<String, u64>`. `add` is Crabwalk's
# expression-safe spelling of the Book's `entry(...).or_insert(0)` increment.
@rust.fn
def blue_team_score() -> rust.u64:
    scores: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    scores.insert("Blue", 10)
    scores.insert("Yellow", 50)
    scores.add("Blue", 15)
    return scores.get_or("Blue", 0)
