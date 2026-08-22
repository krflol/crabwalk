"""Python test-harness adaptation of the Rust Book's Chapter 11 examples."""

import pytest

from crabwalk import CrabwalkPanicError

from .ch11_automated_tests import (
    add_two,
    can_hold_dimensions,
    greeting,
    guarded_value,
)


def test_add_two_equality() -> None:
    assert add_two(2) == 4


def test_larger_rectangle_holds_smaller_one() -> None:
    assert can_hold_dimensions(8, 7, 5, 1)


def test_smaller_rectangle_does_not_hold_larger_one() -> None:
    assert not can_hold_dimensions(5, 1, 8, 7)


def test_greeting_contains_the_name() -> None:
    result = greeting("Carol")
    assert "Carol" in result, f"Greeting did not contain name; value was {result!r}"


def test_guard_panics_with_the_documented_message() -> None:
    with pytest.raises(CrabwalkPanicError, match="value must be at least 1"):
        guarded_value(0)
