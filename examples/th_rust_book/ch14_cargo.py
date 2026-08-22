"""Chapter 14: a Cargo dependency resolved for the generated package crate."""

from crabwalk import rust


# Rust Book sources:
# https://doc.rust-lang.org/book/ch14-01-release-profiles.html
# https://doc.rust-lang.org/book/ch14-03-cargo-workspaces.html
#
# All modules in `th_rust_book` are compiled into one Cargo package, which mirrors
# the Book's workspace goal of coordinating related code while avoiding duplicate
# builds. Crabwalk always generates an inspectable release profile with overflow
# checks enabled; `crabwalk expand` exposes its Cargo.toml and `crabwalk check`
# invokes `cargo check --release`.


# Rust Book source (adding and resolving an external package):
# https://doc.rust-lang.org/book/ch14-03-cargo-workspaces.html#depending-on-an-external-package
#
# This declaration becomes a normal Cargo.toml dependency and a persistent
# application Cargo.lock under `crabwalk-locks/`. It is statically bound as `regex`
# inside compiled functions—there is no Python import or foreign-function shim.
regex = rust.crate("regex", version="1")


@rust.fn
def contains_number(value: rust.Str) -> rust.bool:
    return regex.Regex.new(r"\d+").unwrap().is_match(value)


# Rust Book sources (package documentation and public re-exports):
# https://doc.rust-lang.org/book/ch14-02-publishing-to-crates-io.html#making-useful-documentation-comments
# https://doc.rust-lang.org/book/ch14-02-publishing-to-crates-io.html#exporting-a-convenient-public-api
#
# Python docstrings/comments are retained in the source package, while the native
# symbol is re-exported here through an ordinary package import in `run_all.py`.
# Publishing to crates.io itself is intentionally not performed by an example run:
# it is an external account mutation, whereas dependency resolution is local and
# reproducible.
