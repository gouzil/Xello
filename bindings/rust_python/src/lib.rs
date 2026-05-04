use pyo3::prelude::*;

#[pyfunction]
fn hello(caller: &str) -> String {
    format!("hello world from rust implementation, called by {}", caller)
}

#[pymodule]
fn xello_rust_py(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(hello, module)?)?;
    Ok(())
}

