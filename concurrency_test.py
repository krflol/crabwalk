import time
import threading
from crabwalk import rust

rayon = rust.crate("rayon", version="1.8")

@rust.fn(release_gil=True)
def parallel_math(data: rust.Vec[rust.f64]) -> rust.Vec[rust.f64]:
    # Use rust.raw to drop down into a native Rayon iterator
    rust.raw('''
        data.par_iter_mut().for_each(|x| {
            // Expensive computation to show off concurrency
            *x = (*x * 3.14159).sqrt().sin().cos().tan().exp();
        });
    ''')
    return data

@rust.fn(release_gil=False)
def single_threaded_math(data: rust.Vec[rust.f64]) -> rust.Vec[rust.f64]:
    # Same thing, single threaded
    rust.raw('''
        data.iter_mut().for_each(|x| {
            *x = (*x * 3.14159).sqrt().sin().cos().tan().exp();
        });
    ''')
    return data

def run_background_task():
    # A background task that just spins to see if it gets execution time during the Rust call
    print("[Background Thread] Starting...")
    count = 0
    start = time.time()
    while time.time() - start < 1.0:
        count += 1
    print(f"[Background Thread] Finished, counted to {count}")

def main():
    print("Testing Rayon Concurrency and GIL Release...")
    
    # 10 million elements
    size = 10_000_000
    data = [float(i) for i in range(size)]
    
    print(f"Data size: {len(data)}")
    
    # Test 1: Single Threaded (Blocks GIL)
    print("\n--- Test 1: Single Threaded (GIL Locked) ---")
    data_clone = data.copy()
    start_time = time.time()
    
    # Start background thread
    bg_thread = threading.Thread(target=run_background_task)
    bg_thread.start()
    
    # Run heavy compute
    result1 = single_threaded_math(data_clone)
    bg_thread.join()
    
    single_duration = time.time() - start_time
    print(f"Single threaded took: {single_duration:.4f} seconds")
    
    # Test 2: Multi Threaded (GIL Released)
    print("\n--- Test 2: Rayon Multi-Threaded (GIL Released) ---")
    data_clone = data.copy()
    start_time = time.time()
    
    bg_thread = threading.Thread(target=run_background_task)
    bg_thread.start()
    
    result2 = parallel_math(data_clone)
    bg_thread.join()
    
    multi_duration = time.time() - start_time
    print(f"Multi-threaded took: {multi_duration:.4f} seconds")
    
    speedup = single_duration / multi_duration
    print(f"\nSpeedup: {speedup:.2f}x")

if __name__ == "__main__":
    main()
