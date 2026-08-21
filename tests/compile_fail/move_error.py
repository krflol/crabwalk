# expected-rustc: E0382
from crabwalk import rust

serde = rust.crate("serde", version="1.0", features=["derive"])

@rust.struct(derive=[serde.Serialize, serde.Deserialize])
class Token:
    id: rust.u64
    value: rust.String

@rust.fn
def consume_token(token: Token) -> Token:
    # This will generate: let mut stolen_token = token;
    # Which moves the ownership of the Token struct in Rust!
    stolen_token = token
    
    # This will attempt to return the originally named token,
    # resulting in a strict Rust compile-time move error!
    return token

def main():
    print("Attempting to compile consume_token...")
    consume_token(Token(id=1, value="secret"))

if __name__ == "__main__":
    main()
