use pyo3::prelude::*;
use serde::{Serialize, Deserialize};
#[pyclass]
#[derive(Serialize, Deserialize, Clone)]
pub struct Token {
    #[pyo3(get, set)]
    pub id: u64,
    #[pyo3(get, set)]
    pub value: String,
}
#[pymethods]
impl Token {
    #[new]
    pub fn new() -> Self {
        Self { id: 0, value: String::new() }
    }
}

#[pyfunction]
fn consume_token(token: Token) -> Token {
let mut stolen_token = token;
return token;
}
#[pymodule]
fn crabwalk_compiled_move_error(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(consume_token, m)?)?;
    m.add_class::<Token>()?;
    Ok(())
}
