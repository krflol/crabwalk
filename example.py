from crabwalk import rust

python_int = 40
@rust.fn
def fibonacci(n: rust.u64) -> rust.u64:
    if n <= 1:
        return n

    return fibonacci(n - 1) + fibonacci(n - 2)


print(fibonacci(python_int))

while True:
    fib = int(input("input a number to fib: "))
    print(fibonacci(fib))