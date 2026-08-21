from crabwalk import rust

@rust.struct(derive=[rust.PartialEq, rust.Eq])
class User:
    id: rust.u64
    name: rust.String

@rust.enum()
class Role:
    Admin = 0
    Member = 1

@rust.fn
def check_role(u: User, role: Role) -> rust.Result[rust.bool, rust.String]:
    if role == Role.Admin:
        return rust.Ok(True)
    elif role == Role.Member:
        return rust.Ok(False)
    else:
        return rust.Err("Unknown role")

def main():
    import sys
    rust.compile(sys.modules[__name__])
    u = User(id=1, name="Alice")
    res = check_role(u, Role.Admin)
    print("Check Admin:", res)

if __name__ == "__main__":
    main()
