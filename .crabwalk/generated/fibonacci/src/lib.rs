        use pyo3::prelude::*;

        #[pyfunction]
fn fibonacci(n: u64) -> u64 {
if n <= 1 {
return n;
}
return fibonacci(n - 1) + fibonacci(n - 2);
}

        #[pymodule]
        fn crabwalk_generated(_py: Python, m: &PyModule) -> PyResult<()> {
            m.add_function(wrap_pyfunction!(fibonacci, m)?)?;
            Ok(())
        }
