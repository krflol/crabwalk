use pyo3::prelude::*;
use serde::{Serialize, Deserialize};
#[pyclass]
#[derive(Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum Status {
    Pending,
    Active,
    Failed
}

#[pyclass]
#[derive(Clone, Serialize, Deserialize)]
pub struct Job {
    #[pyo3(get, set)]
    pub id: u64,
    #[pyo3(get, set)]
    pub status: Status,
}
#[pymethods]
impl Job {
    #[new]
    pub fn new() -> Self {
        Self { id: 0, status: Status::Pending }
    }
}

#[pyfunction]
fn process_job(mut job: Job) -> Job {
println!("Native Rust macro: Processing Job #{}", job.id);
if (job.status.clone() == Status::Pending) {
job.status = Status::Active;
}
job.id = job.id * 10 + 5;
return job;
}
#[pymodule]
fn crabwalk_compiled_enums_and_hatches_test(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(process_job, m)?)?;
    m.add_class::<Status>()?;
    m.add_class::<Job>()?;
    Ok(())
}
