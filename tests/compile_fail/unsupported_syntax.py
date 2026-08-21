from crabwalk import rust

@rust.fn
def invalid_loop():
    while True:
        pass
    else:
        print("Not supported")
        
invalid_loop()
