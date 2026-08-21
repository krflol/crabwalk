use pyo3::prelude::*;
#[pyclass]
#[derive(Clone)]
pub struct Stats {
    #[pyo3(get, set)]
    pub total: f64,
    #[pyo3(get, set)]
    pub count: u32,
}
#[pymethods]
impl Stats {
    #[new]
    pub fn new() -> Self {
        Self { total: 0.0, count: 0 }
    }
}

#[pyfunction]
fn process_data(mut values: Vec<f64>) -> Option<Stats> {
if values.is_empty() {
return None;
}
let mut stats = Stats::new();
for val in values {
stats.total = (stats.total.clone() + val);
stats.count = (stats.count.clone() + 1);
}
return Some(stats);
}
#[pyfunction]
fn find_threshold(mut target: f64) -> f64 {
let mut current = 1.0;
let mut step = 0.5;
while ((current < target) && !(current == target)) {
current = (current + step);
}
return current;
}
#[pymodule]
fn crabwalk_compiled_mvp_test(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(process_data, m)?)?;
    m.add_function(wrap_pyfunction!(find_threshold, m)?)?;
    m.add_class::<Stats>()?;
    Ok(())
}
