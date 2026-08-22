"""Chapter 12: the native search core of the minigrep command-line project."""

from crabwalk import rust


# Rust Book sources (the evolving `search` implementation, Listings 12-13–12-19):
# https://doc.rust-lang.org/book/ch12-03-improving-error-handling-and-modularity.html#splitting-code-into-a-library-crate
# https://doc.rust-lang.org/book/ch12-04-testing-the-librarys-functionality.html#writing-code-to-pass-the-test
#
# Argument parsing, environment lookup, file I/O, stdout, and stderr stay in the
# ordinary Python command-line shell. The text scan is the computation-heavy,
# deterministic library core and runs as Rust. Rust Book `Vec<&str>` cannot safely
# escape through Python, so the ABI deliberately returns `Vec<String>`: each match
# is copied before its source `contents` borrow ends.
@rust.fn
def search(query: rust.Str, contents: rust.Str) -> rust.Vec[rust.String]:
    matches: rust.Vec[rust.String] = rust.Vec([])
    for line in contents.lines():
        if line.contains(query):
            matches.push(rust.String(line))
    return matches


# Rust Book source (Listings 12-20–12-23):
# https://doc.rust-lang.org/book/ch12-05-working-with-environment-variables.html#implementing-the-search_case_insensitive-function
#
# `to_lowercase` creates owned Rust strings. `as_str` makes the short-lived borrow
# explicit before `contains`, and the original line—not its normalized copy—is
# returned to the Python shell.
@rust.fn
def search_case_insensitive(
    query: rust.Str,
    contents: rust.Str,
) -> rust.Vec[rust.String]:
    lowered_query: rust.String = query.to_lowercase()
    matches: rust.Vec[rust.String] = rust.Vec([])
    for line in contents.lines():
        lowered_line: rust.String = line.to_lowercase()
        if lowered_line.contains(lowered_query.as_str()):
            matches.push(rust.String(line))
    return matches


# Rust Book source (`Config::build` returning `Result`, Listings 12-8–12-10):
# https://doc.rust-lang.org/book/ch12-03-improving-error-handling-and-modularity.html#returning-a-result-instead-of-calling-panic
#
# This helper validates the same minimum argument count. The Python shell owns the
# actual `sys.argv` strings and converts a failure into its preferred exit code.
@rust.fn
def validate_argument_count(count: rust.usize) -> rust.Result[rust.usize, rust.String]:
    if count < 3:
        return rust.Err("not enough arguments")
    return rust.Ok(count)
