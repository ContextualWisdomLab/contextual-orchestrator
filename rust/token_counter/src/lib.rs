//! Exact cl100k child chunking and provider-request packing for Python.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;
use tiktoken_rs::cl100k_base;

#[pyclass(get_all)]
#[derive(Clone)]
struct PackedPart {
    source_index: usize,
    part_index: usize,
    part_count: usize,
    token_start: usize,
    token_end: usize,
    token_count: usize,
    text: String,
}

#[pyfunction]
fn pack_cl100k(
    texts: Vec<String>, max_tokens_per_input: usize, max_inputs: usize,
    max_total_tokens: usize,
) -> PyResult<(Vec<PackedPart>, Vec<Vec<usize>>)> {
    if max_tokens_per_input == 0 || max_inputs == 0 || max_total_tokens == 0 {
        return Err(PyValueError::new_err("limits must be positive"));
    }
    if texts.iter().any(String::is_empty) {
        return Err(PyValueError::new_err("embedding input must be non-empty"));
    }
    let tokenizer = cl100k_base().map_err(|_| PyValueError::new_err("cl100k unavailable"))?;
    let encoded: Vec<Vec<u32>> = texts.par_iter().map(|text| tokenizer.encode_ordinary(text)).collect();
    let mut parts = Vec::new();
    for (source_index, tokens) in encoded.iter().enumerate() {
        let part_count = tokens.len().div_ceil(max_tokens_per_input);
        for (part_index, slice) in tokens.chunks(max_tokens_per_input).enumerate() {
            let token_start = part_index.checked_mul(max_tokens_per_input).ok_or_else(|| PyValueError::new_err("token range overflow"))?;
            let token_end = token_start.checked_add(slice.len()).ok_or_else(|| PyValueError::new_err("token range overflow"))?;
            let text = tokenizer.decode(slice.to_vec()).map_err(|_| PyValueError::new_err("token decode failed"))?;
            parts.push(PackedPart { source_index, part_index, part_count, token_start, token_end, token_count: slice.len(), text });
        }
    }
    let mut shards = Vec::new(); let mut current = Vec::new(); let mut current_tokens = 0usize;
    for (index, part) in parts.iter().enumerate() {
        let next = current_tokens.checked_add(part.token_count).ok_or_else(|| PyValueError::new_err("request token total overflow"))?;
        if !current.is_empty() && (current.len() >= max_inputs || next > max_total_tokens) {
            shards.push(std::mem::take(&mut current)); current_tokens = 0;
        }
        current_tokens = current_tokens.checked_add(part.token_count).ok_or_else(|| PyValueError::new_err("request token total overflow"))?;
        current.push(index);
    }
    if !current.is_empty() { shards.push(current); }
    Ok((parts, shards))
}

#[pymodule]
fn _token_packer(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PackedPart>()?;
    module.add_function(wrap_pyfunction!(pack_cl100k, module)?)?;
    Ok(())
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn utf8_and_boundaries_preserve_order() {
        Python::with_gil(|_| {
            let (parts, shards) = pack_cl100k(vec!["a ".repeat(8192), "한국어🙂e\u{301}".into()], 8192, 2048, 300_000).unwrap();
            assert!(parts.iter().all(|part| part.token_count <= 8192));
            assert_eq!(parts.last().unwrap().source_index, 1);
            assert_eq!(parts.last().unwrap().text, "한국어🙂e\u{301}");
            assert_eq!(shards.iter().flatten().count(), parts.len());
        });
    }
    #[test] fn official_input_boundary_shards_2049() {
        Python::with_gil(|_| { let (_, shards) = pack_cl100k(vec!["x".into();2049],8192,2048,300_000).unwrap(); assert_eq!(shards.iter().map(Vec::len).collect::<Vec<_>>(),vec![2048,1]); });
    }
}
