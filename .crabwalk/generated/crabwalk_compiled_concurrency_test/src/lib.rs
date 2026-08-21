use pyo3::prelude::*;
use rayon::prelude::*;

#[pyfunction]
fn parallel_math(py: Python, mut data: Vec<f64>) -> Vec<f64> {
    py.allow_threads(move || {
        
                data.par_iter_mut().for_each(|x| {
                    // Expensive computation to show off concurrency
                    *x = (*x * 3.14159).sqrt().sin().cos().tan().exp();
                });
            
        return data;
    })
}
#[pyfunction]
fn single_threaded_math(mut data: Vec<f64>) -> Vec<f64> {

        data.iter_mut().for_each(|x| {
            *x = (*x * 3.14159).sqrt().sin().cos().tan().exp();
        });
    
return data;
}
#[pymodule]
fn crabwalk_compiled_concurrency_test(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parallel_math, m)?)?;
    m.add_function(wrap_pyfunction!(single_threaded_math, m)?)?;
    Ok(())
}
