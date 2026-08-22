from crabwalk import CrabwalkMoveError, rust


@rust.fn
def total(values: rust.Ref[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()


@rust.fn
def append(values: rust.Mut[rust.Vec[rust.u64]], value: rust.u64) -> None:
    values.push(value)


@rust.fn
def consume(values: rust.Owned[rust.Vec[rust.u64]]) -> rust.usize:
    return values.len()


values = rust.Vec[rust.u64]([1, 2, 3])
alias = values

print(total(values))
append(values, 4)
print(values.to_python())
print(consume(values))

try:
    print(len(alias))
except CrabwalkMoveError as error:
    print(type(error).__name__, error)
