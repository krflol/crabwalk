from crabwalk import rust

@rust.pyclass
class Counter:
    count: rust.u64

    def __init__(self, start: rust.u64):
        self.count = start

    def increment(self, amount: rust.u64) -> rust.u64:
        self.count = self.count + amount
        return self.count

import sys

if __name__ == "__main__":
    rust.compile(sys.modules[__name__])
    
    print("Creating Counter...")
    c = Counter(10)
    print("Initial count:", c.count)
    
    c.increment(5)
    print("After increment:", c.count)
    
    c.count = 100
    print("After manual set:", c.count)
