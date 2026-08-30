"""Execute the completed Rust Book chapter adaptations as one native crate.

Run from the repository's ``examples`` directory with::

    python -m the_rust_book.run_all

The assertions live in ordinary Python on purpose.  Every imported ``@rust.fn``
body is compiled together into one Rust extension, while this small host program
checks the values crossing the Python/Rust boundary.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from crabwalk import CrabwalkPanicError, CrabwalkRustError, rust

from .ch01_getting_started import hello_world
from .ch02_guessing_game import compare_guess, secret_from_seed
from .ch03_common_concepts import (
    binding_rules,
    compound_types,
    countdown_sum,
    is_crab,
    sum_odd_below,
)
from .ch04_ownership import (
    append_value,
    consume_vector,
    first_word_length,
    vector_length,
)
from .ch05_structs import Rectangle, can_hold, make_square, rectangle_area, square_area
from .ch06_enums import Message, message_weight, optional_or, plus_one
from .ch07_modules import area_through_module
from .ch08_collections import (
    blue_team_score,
    greeting,
    joined_languages,
    normalize_fields,
    normalize_greeting,
    supplied_team_score,
    team_scores,
    total_team_score,
    vector_total,
    word_frequencies,
)
from .ch09_error_handling import (
    doubled_nonzero_or_zero,
    expect_nonzero,
    nonzero_or_default,
    panic_on_zero,
    parse_nonzero,
    read_username_from_file,
    require_nonzero,
)
from .ch10_generics_traits_lifetimes import (
    largest_character,
    largest_number,
    longest_owned,
    trait_argument_demo,
)
from .ch11_automated_tests import (
    add_two,
    can_hold_dimensions,
    greeting as test_greeting,
)
from .ch12_minigrep import (
    build_config,
    search,
    search_case_insensitive,
    search_with_config,
    validate_argument_count,
)
from .ch13_closures_iterators import (
    Shoe,
    explicitly_moved_transform,
    indexed_parallel_values,
    matching_line_count,
    normalize_active_rows,
    parallel_normalize_active_rows,
    shifted_sum,
    shoes_in_size,
    transformed,
)
from .ch14_cargo import contains_number
from .ch15_smart_pointers import boxed_value, interior_mutation, rc_counts
from .ch16_concurrency import (
    SharedReading,
    channel_value,
    moved_vector_length,
    shared_counter,
    shared_reading_total,
)
from .ch17_async_await import (
    run_async_channel,
    run_async_pipeline,
    run_concurrent_sum,
    run_race,
    run_stream_sequence,
)
from .ch18_object_oriented import (
    averaged_collection_demo,
    publish_post,
    screen_draw_total,
)
from .ch19_patterns import (
    captured_id,
    character_band,
    destructured_parameter_total,
    guarded_option,
    ignored_parts_total,
    literal_or_range,
    mixed_destructure,
    nested_color_total,
    option_or_else,
    or_pattern_guard,
    point_region,
    point_x_only,
    setting_can_change,
    tuple_binding_total,
    tuple_ends,
    tuple_loop_total,
    while_some_total,
)
from .ch20_advanced_features import (
    associated_item_demo,
    display_bound_demo,
    dynamically_sized_string_length,
    ffi_absolute,
    function_pointer_demo,
    heterogeneous_closure_demo,
    macro_vector_total,
    metric_operator_demo,
    never_coercion_demo,
    point_operator_demo,
    raw_pointer_demo,
    returned_closure_demo,
    trait_disambiguation_demo,
    type_alias_demo,
    unsafe_split_total,
    unsafe_static_counter,
)
from .ch21_web_server import (
    http_round_trip,
    thread_pool_job_total,
    validated_pool_size,
)


def main() -> None:
    """Assert the observable contract of every completed Book example family."""

    hello_world()

    assert compare_guess(10, 20) == -1
    assert compare_guess(20, 10) == 1
    assert compare_guess(10, 10) == 0
    assert secret_from_seed(0) == 1
    assert secret_from_seed(99) == 100

    assert binding_rules() == 10_806
    assert compound_types() == 515
    assert is_crab("🦀") is True
    assert is_crab("x") is False
    assert sum_odd_below(10) == 25
    assert countdown_sum(5) == 15

    values = rust.Vec[rust.u64]([1, 2, 3])
    assert vector_length(values) == 3
    append_value(values, 4)
    assert values.to_python() == [1, 2, 3, 4]
    assert first_word_length("hello rust book") == 5
    assert consume_vector(values) == 4
    assert values.moved is True

    outer = Rectangle(width=30, height=50)
    inner = Rectangle(width=10, height=40)
    assert rectangle_area(outer) == 1_500
    assert can_hold(outer, inner) is True
    assert square_area(12) == 144
    square = make_square(9)
    assert square.to_python() == {"width": 9, "height": 9}
    assert rectangle_area(square) == 81
    assert square.moved is False
    assert area_through_module(outer) == 1_500

    quit_message = Message.Quit()
    move_message = Message.Move(x=3, y=4)
    write_message = Message.Write("hello")
    color_message = Message.ChangeColor(10, 20, 30)
    assert message_weight(quit_message) == 0
    assert message_weight(move_message) == 7
    assert message_weight(write_message) == 1
    assert message_weight(color_message) == 60
    assert write_message.to_python() == {"variant": "Write", "_0": "hello"}
    assert color_message.to_python() == {
        "variant": "ChangeColor",
        "_0": 10,
        "_1": 20,
        "_2": 30,
    }
    assert optional_or(None, 9) == 9
    assert optional_or(7, 9) == 7
    assert plus_one(None) is None
    assert plus_one(41) == 42

    assert vector_total() == 15
    assert greeting("Ferris") == "Hello, Ferris"
    assert normalize_greeting("hello world") == "hello Rust"
    assert normalize_greeting("hello Crabwalk") == "hello Crabwalk"
    assert normalize_fields("  Rust||PYTHON|Crabwalk  ") == [
        "rust",
        "python",
        "crabwalk",
    ]
    assert joined_languages() == "Rust + Python + Crabwalk"
    assert team_scores() == {"Blue": 25, "Yellow": 50}
    assert total_team_score() == 75
    assert supplied_team_score({"Blue": 25, "Yellow": 50}) == 75
    assert blue_team_score() == 25
    assert word_frequencies("hello world wonderful world") == {
        "hello": 1,
        "world": 2,
        "wonderful": 1,
    }

    assert require_nonzero(5) == 5
    username_path = Path(__file__).with_name("username.txt")
    assert read_username_from_file(str(username_path)).strip() == "Ferris"
    assert parse_nonzero(" 42 ") == 42
    assert nonzero_or_default(0, 7) == 7
    assert nonzero_or_default(9, 7) == 9
    assert doubled_nonzero_or_zero(4) == 8
    assert doubled_nonzero_or_zero(0) == 0
    assert panic_on_zero(8) == 8
    assert expect_nonzero(8) == 8

    try:
        read_username_from_file(str(Path(__file__).with_name("missing-username.txt")))
    except CrabwalkRustError as error:
        assert error.variant == "Io"
        assert error.source_chain[0].rust_type == "rust.IoError"
    else:  # pragma: no cover - this is a failure message for manual runs
        raise AssertionError("a missing file must cross as UsernameError.Io")

    for operation in (
        lambda: require_nonzero(0),
        lambda: parse_nonzero("not-a-number"),
    ):
        try:
            operation()
        except CrabwalkRustError:
            pass
        else:  # pragma: no cover - this is a failure message for manual runs
            raise AssertionError("an Err value must cross as CrabwalkRustError")

    for operation in (lambda: panic_on_zero(0), lambda: expect_nonzero(0)):
        try:
            operation()
        except CrabwalkPanicError:
            pass
        else:  # pragma: no cover - this is a failure message for manual runs
            raise AssertionError("a Rust panic must cross as CrabwalkPanicError")

    assert largest_number() == 100
    assert largest_character() == "y"
    assert longest_owned("abcd", "xyz") == "abcd"
    assert trait_argument_demo(10, 7) == 17

    assert add_two(2) == 4
    assert can_hold_dimensions(8, 7, 5, 1) is True
    assert test_greeting("Carol") == "Hello Carol"

    poem = "Rust:\nsafe, fast, productive.\nPick three.\nTrust me."
    assert search("duct", poem) == ["safe, fast, productive."]
    assert search_case_insensitive("rUsT", poem) == ["Rust:", "Trust me."]
    config = build_config("rust", True)
    assert config.to_python() == {"query": "rust", "ignore_case": True}
    assert search_with_config(config, poem) == ["Rust:", "Trust me."]
    assert config.moved is False
    assert validate_argument_count(3) == 3
    try:
        validate_argument_count(2)
    except CrabwalkRustError:
        pass
    else:  # pragma: no cover - this is a failure message for manual runs
        raise AssertionError("invalid minigrep arguments must return Err")

    assert transformed(4, 2) == [4, 5, 6]
    assert shifted_sum(3) == 15
    assert explicitly_moved_transform(10) == [11, 12, 13]
    assert matching_line_count("Rust", poem) == 1

    shoes = rust.Vec[Shoe](
        [
            {"size": 10, "style": "sneaker"},
            {"size": 13, "style": "sandal"},
            {"size": 10, "style": "boot"},
        ]
    )
    matching_shoes = shoes_in_size(shoes, 10)
    assert shoes.moved is True
    assert matching_shoes.to_python() == [
        {"size": 10, "style": "sneaker"},
        {"size": 10, "style": "boot"},
    ]

    rows = rust.Vec[rust.String](
        [
            "1|ALICE|active|CHICAGO",
            "2|BOB|inactive|MADISON",
            "3|CAROL|active|MILWAUKEE",
        ]
    )
    expected_rows = [
        "1|alice|active|chicago",
        "3|carol|active|milwaukee",
    ]
    assert normalize_active_rows(rows) == expected_rows
    assert rows.moved is False
    parallel_rows = rust.Vec[rust.String](rows.to_python())
    assert parallel_normalize_active_rows(parallel_rows) == expected_rows
    assert parallel_rows.moved is True
    indexed_values = rust.Vec[rust.u64]([10, 20, 30])
    assert indexed_parallel_values(indexed_values) == [(0, 10), (1, 20), (2, 30)]

    assert contains_number("room 7") is True
    assert contains_number("no digits") is False

    assert boxed_value(42) == 42
    assert rc_counts() == 21
    assert interior_mutation() == 15

    assert moved_vector_length() == 3
    assert channel_value() == 42
    assert shared_counter() == 1
    owned_readings = rust.Vec[SharedReading]([{"value": 2}, {"value": 3}])
    shared_readings = owned_readings.freeze()
    with ThreadPoolExecutor(max_workers=4) as executor:
        shared_totals = list(
            executor.map(lambda _: shared_reading_total(shared_readings), range(8))
        )
    assert shared_totals == [5] * 8
    assert owned_readings.moved is True

    assert run_async_pipeline(5) == 20
    assert run_concurrent_sum() == 7
    assert run_race() == 20
    assert run_async_channel() == 30
    assert run_stream_sequence() == 10

    assert averaged_collection_demo() == 15.0
    assert screen_draw_total() == 1_253
    assert publish_post() == "I ate a salad for lunch today"

    assert tuple_binding_total() == 6
    assert tuple_loop_total() == 63
    assert destructured_parameter_total((3, 5)) == 8
    assert option_or_else(7, 99) == 7
    assert option_or_else(None, 99) == 99
    assert while_some_total() == 6
    assert literal_or_range(1) == 10
    assert literal_or_range(5) == 5
    assert literal_or_range(9) == 0
    assert character_band("a") == 1
    assert character_band("d") == 2
    assert character_band("z") == 0
    assert point_region(0, 7) == 7
    assert point_region(4, 4) == 8
    assert point_region(3, 4) == 7
    assert point_x_only(3, 5, 8) == 3
    assert mixed_destructure() == 29
    assert nested_color_total(120, 50, 75) == 245
    assert ignored_parts_total() == 42
    assert tuple_ends(2, 9) == 11
    assert setting_can_change(1, 2) is False
    assert setting_can_change(None, 2) is True
    assert guarded_option(8, 8) == 8
    assert guarded_option(4, 8) == 104
    assert guarded_option(3, 8) == 3
    assert guarded_option(None, 8) == 0
    assert or_pattern_guard(4, False) is False
    assert or_pattern_guard(5, True) is True
    assert captured_id(5) == 5
    assert captured_id(11) == 10
    assert captured_id(20) == 120

    assert raw_pointer_demo() == 59
    assert unsafe_split_total() == 10
    assert ffi_absolute(-42) == 42
    assert unsafe_static_counter(2) == 2
    assert associated_item_demo() == 9
    assert point_operator_demo() == 46
    assert metric_operator_demo() == 2_500
    assert trait_disambiguation_demo() == 123
    assert display_bound_demo() == 42
    assert type_alias_demo(9) == 9
    assert never_coercion_demo() == 4
    assert dynamically_sized_string_length("sized pointer") == 13
    assert function_pointer_demo(5) == 12
    assert returned_closure_demo(5) == 8
    assert heterogeneous_closure_demo(5) == 16
    assert macro_vector_total() == 10

    ok_response = http_round_trip("/")
    missing_response = http_round_trip("/missing")
    slow_response = http_round_trip("/sleep")
    assert ok_response.startswith("HTTP/1.1 200 OK")
    assert "Hi from Rust" in ok_response
    assert missing_response.startswith("HTTP/1.1 404 NOT FOUND")
    assert "Oops!" in missing_response
    assert slow_response.startswith("HTTP/1.1 200 OK")
    assert thread_pool_job_total() == 3
    assert validated_pool_size(2) == 2
    try:
        validated_pool_size(0)
    except CrabwalkPanicError:
        pass
    else:  # pragma: no cover - failure detail for a manual run
        raise AssertionError("a zero-sized ThreadPool must panic")

    print("Rust Book chapters 1-21: all native assertions passed")


if __name__ == "__main__":
    main()
