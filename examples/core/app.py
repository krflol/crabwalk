from crabwalk import rust


@rust.fn
def sum_to(n: rust.u64) -> rust.u64:
    total: rust.u64 = 0
    for value in range(n):
        total += value
    return total


@rust.fn
def count_to(n: rust.u64) -> rust.u64:
    value: rust.u64 = 0
    while value < n:
        value += 1
    return value


@rust.fn
def vector_len(n: rust.u64) -> rust.usize:
    values: rust.Vec[rust.u64] = rust.Vec([n, 1])
    values.push(2)
    return values.len()


@rust.fn
def maybe(n: rust.u64) -> rust.Option[rust.u64]:
    if n == 0:
        return None
    return rust.Some(n)


@rust.fn
def validate(n: rust.u64) -> rust.Result[rust.u64, rust.String]:
    if n == 0:
        return rust.Err("zero")
    return rust.Ok(n)


@rust.fn
def python_hello(name: rust.Str) -> rust.String:
    print(name)
    rust.println(name)
    return rust.String(name)


@rust.fn
def call_python_hello(name: rust.Str) -> rust.String:
    return python_hello(name)


if __name__ == "__main__":
    print(sum_to(10))
    print(count_to(7))
    print(vector_len(9))
    print(maybe(0))
    print(maybe(5))
    print(validate(5))
    try:
        validate(0)
    except RuntimeError as error:
        print(type(error).__name__, str(error))
    print(call_python_hello("boundary"))
