from crabwalk import rust

@rust.struct()
class Stats:
    total: rust.f64
    count: rust.u32

@rust.fn
def process_data(values: rust.Vec[rust.f64]) -> rust.Option[Stats]:
    if values.is_empty():
        return None
        
    stats = Stats(0.0, 0)
    
    # For loop test
    for val in values:
        stats.total = stats.total + val
        stats.count = stats.count + 1
        
    return rust.Some(stats)

@rust.fn
def find_threshold(target: rust.f64) -> rust.f64:
    current = 1.0
    step = 0.5
    
    # While loop test & boolean logic
    while (current < target) and not (current == target):
        current = current + step
        
    return current

def main():
    import sys
    rust.compile(sys.modules[__name__])
    print("Testing Crabwalk Full MVP Architecture...")
    
    # Test 1: Option and For Loop
    print("\n--- Test 1: For Loops and Options ---")
    data = [1.5, 2.5, 3.5]
    result = process_data(data)
    
    if result is not None:
        print(f"Stats - Total: {result.total}, Count: {result.count}")
    else:
        print("No data provided.")
        
    empty_result = process_data([])
    print(f"Empty data result: {empty_result}")
    
    # Test 2: While loop and Boolean logic
    print("\n--- Test 2: While Loops and Boolean Logic ---")
    threshold = find_threshold(5.0)
    print(f"Reached threshold: {threshold}")

if __name__ == "__main__":
    main()
