import requests
from crabwalk import rust

serde = rust.crate("serde", version="1.0", features=["derive"])
serde_json = rust.crate("serde_json", version="1.0")

@rust.struct(derive=[serde.Serialize, serde.Deserialize])
class Post:
    userId: rust.u64
    id: rust.u64
    title: rust.String
    body: rust.String

@rust.struct()
class Metrics:
    posts_processed: rust.u64

@rust.fn
def extract_title(json_data: rust.String, metrics: rust.Mut[Metrics]) -> rust.String:
    post = serde_json.from_str(Post, json_data)
    metrics.posts_processed = metrics.posts_processed + 1
    return post.title

def main():
    # 1. Create the global state (owned by Rust natively, but wrapped for Python)
    print("Initializing native Rust state...")
    metrics = Metrics()
    
    print(f"[Python] Posts processed before: {metrics.posts_processed}")

    # 2. Fetch the data using Python
    print("\nFetching data using Python's requests...")
    response = requests.get("https://jsonplaceholder.typicode.com/posts/1")
    
    # 3. Parse data AND mutate state exclusively natively
    print("Parsing JSON and mutating state natively in Rust...")
    title = extract_title(response.text, metrics)
    
    print(f"\n[Python] Rust extracted title: {title}")
    
    # 4. Check state from Python again
    print(f"[Python] Posts processed after: {metrics.posts_processed}")

if __name__ == "__main__":
    main()
