from crabwalk import rust


regex = rust.crate("regex", version="1")


@rust.fn
def contains_number(value: rust.Str) -> rust.bool:
    return regex.Regex.new(r"\d+").unwrap().is_match(value)


if __name__ == "__main__":
    print(contains_number("abc123"))
    print(contains_number("no digits"))
