from crabwalk import rust

serde = rust.crate("serde", version="1.0", features=["derive"])

@rust.enum(derive=[serde.Serialize, serde.Deserialize])
class Status:
    Pending = 0
    Active = 1
    Failed = 2

@rust.struct()
class Job:
    id: rust.u64
    status: Status

@rust.fn
def process_job(job: Job) -> Job:
    # Use rust.raw to invoke a native Rust macro
    rust.raw('println!("Native Rust macro: Processing Job #{}", job.id);')
    
    if job.status == Status.Pending:
        job.status = Status.Active
    
    # Use rust.expr to inject raw Rust mathematics
    job.id = rust.expr("job.id * 10 + 5")
    return job

def main():
    print("Testing Enums and Escape Hatches...")
    
    job = Job()
    job.id = 1
    job.status = Status.Pending
    
    print(f"\n[Python] Job before processing: id={job.id}, status={job.status}")
    
    processed = process_job(job)
    
    print(f"[Python] Job after processing: id={processed.id}, status={processed.status}")

if __name__ == "__main__":
    main()
