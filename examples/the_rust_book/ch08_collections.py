"""Chapter 8: composable Vec, String, and HashMap operations."""

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


# Rust Book source (UTF-8 strings and iteration):
# https://doc.rust-lang.org/book/ch08-02-strings.html#methods-for-iterating-over-strings
#
# This is deliberately a multi-stage, non-Copy pipeline. `trim()` and `split()`
# yield borrowed `&str` items, `filter` keeps nonempty fields, `map` allocates owned
# lowercase Strings, and only `collect_vec()` materializes the final Vec.
@rust.fn
def normalize_fields(record: rust.Str) -> rust.Vec[rust.String]:
    fields = record.trim().split("|").filter(lambda field: not field.is_empty())
    normalized = fields.map(lambda field: field.to_lowercase())
    return normalized.collect_vec()


# Rust Book source (building Strings from collections):
# https://doc.rust-lang.org/book/ch08-02-strings.html#creating-a-new-string
#
# `join` executes on Rust string slices. No Python list or Python join call appears
# inside the compiled function.
@rust.fn
def joined_languages() -> rust.String:
    languages: rust.Vec[rust.String] = rust.Vec(["Rust", "Python", "Crabwalk"])
    return " + ".join(languages)


# Rust Book source:
# https://doc.rust-lang.org/book/ch08-03-hash-maps.html
#
# The map is a real `std::collections::HashMap<String, u64>`. `add` is Crabwalk's
# expression-safe spelling of the Book's `entry(...).or_insert(0)` increment.
@rust.fn
def team_scores() -> rust.HashMap[rust.String, rust.u64]:
    scores: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    scores.insert("Blue", 10)
    scores.insert("Yellow", 50)
    scores.add("Blue", 15)
    return scores


# Borrowed map values form an iterator of `&u64`; `copied()` makes the sum's item
# type explicit without cloning the map or crossing into Python between stages.
@rust.fn
def total_team_score() -> rust.u64:
    scores: rust.HashMap[rust.String, rust.u64] = team_scores()
    return scores.values().copied().sum()


@rust.fn
def blue_team_score() -> rust.u64:
    scores: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    scores.insert("Blue", 10)
    scores.insert("Yellow", 50)
    scores.add("Blue", 15)
    return scores.get_or("Blue", 0)


# Rust Book source (word counting with `entry`):
# https://doc.rust-lang.org/book/ch08-03-hash-maps.html#updating-a-value-based-on-the-old-value
#
# `split_whitespace()` lends each word to the loop. `to_lowercase()` creates the
# owned String required by the map, and returning the map explicitly converts it
# to a Python dict at the ABI boundary.
@rust.fn
def word_frequencies(text: rust.Str) -> rust.HashMap[rust.String, rust.u64]:
    counts: rust.HashMap[rust.String, rust.u64] = rust.HashMap()
    for word in text.split_whitespace():
        counts.add(word.to_lowercase(), 1)
    return counts
