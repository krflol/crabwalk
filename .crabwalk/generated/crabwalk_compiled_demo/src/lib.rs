use pyo3::prelude::*;
use serde::{Serialize, Deserialize};
#[pyclass]
#[derive(Serialize, Deserialize, Clone)]
pub struct Post {
    #[pyo3(get, set)]
    pub userId: u64,
    #[pyo3(get, set)]
    pub id: u64,
    #[pyo3(get, set)]
    pub title: String,
    #[pyo3(get, set)]
    pub body: String,
}
#[pymethods]
impl Post {
    #[new]
    pub fn new() -> Self {
        Self { userId: 0, id: 0, title: String::new(), body: String::new() }
    }
}

#[pyclass]
#[derive(Serialize, Deserialize, Clone)]
pub struct Metrics {
    #[pyo3(get, set)]
    pub posts_processed: u64,
}
#[pymethods]
impl Metrics {
    #[new]
    pub fn new() -> Self {
        Self { posts_processed: 0 }
    }
}

#[pyfunction]
fn extract_title(json_data: String, metrics: &mut Metrics) -> String {
let mut post = serde_json::from_str::<Post>(&json_data).unwrap();
metrics.posts_processed = metrics.posts_processed.clone() + 1;
return post.title.clone();
}
#[pymodule]
fn crabwalk_compiled_demo(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(extract_title, m)?)?;
    m.add_class::<Post>()?;
    m.add_class::<Metrics>()?;
    Ok(())
}
