from crabwalk import rust


@rust.fn
def fibonacci(n: rust.u64) -> rust.u64:
    if n <= 1:
        return n

    return fibonacci(n - 1) + fibonacci(n - 2)


if __name__ == "__main__":
    print(fibonacci(40))
