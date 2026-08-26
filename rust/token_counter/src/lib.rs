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

fn checked_token_total(current: usize, additional: usize) -> PyResult<usize> {
    current
        .checked_add(additional)
        .ok_or_else(|| PyValueError::new_err("request token total overflow"))
}

#[pyfunction]
fn sum_token_counts(values: Vec<usize>) -> PyResult<usize> {
    values.into_iter().try_fold(0usize, checked_token_total)
}

#[pyfunction]
fn weighted_average_embeddings(parts: Vec<(Vec<f64>, usize)>) -> PyResult<Vec<f64>> {
    let vectors: Vec<&Vec<f64>> = parts
        .iter()
        .filter_map(|(vector, _weight)| (!vector.is_empty()).then_some(vector))
        .collect();
    if vectors.is_empty() {
        return Ok(Vec::new());
    }
    let dimension = vectors.iter().map(|vector| vector.len()).max().unwrap_or(0);
    let weights: Vec<usize> = parts
        .iter()
        .map(|(_vector, weight)| (*weight).max(1))
        .collect();
    let total_weight = sum_token_counts(weights.clone())?;
    (0..dimension)
        .map(|offset| {
            let weighted_sum = parts
                .iter()
                .zip(weights.iter())
                .map(|((vector, _weight), weight)| {
                    vector.get(offset).copied().unwrap_or(0.0) * (*weight as f64)
                })
                .sum::<f64>();
            let reduced = weighted_sum / (total_weight as f64);
            if reduced.is_finite() {
                Ok((reduced * 100_000_000.0).round() / 100_000_000.0)
            } else {
                Err(PyValueError::new_err("embedding reduction is not finite"))
            }
        })
        .collect()
}

#[pyfunction]
fn pack_cl100k(
    texts: Vec<String>,
    max_tokens_per_input: usize,
    max_inputs: usize,
    max_total_tokens: usize,
) -> PyResult<(Vec<PackedPart>, Vec<Vec<usize>>)> {
    if max_tokens_per_input == 0 || max_inputs == 0 || max_total_tokens == 0 {
        return Err(PyValueError::new_err("limits must be positive"));
    }
    if texts.iter().any(String::is_empty) {
        return Err(PyValueError::new_err("embedding input must be non-empty"));
    }
    let tokenizer = cl100k_base().map_err(|_| PyValueError::new_err("cl100k unavailable"))?;
    let encoded: Vec<Vec<u32>> = texts
        .par_iter()
        .map(|text| tokenizer.encode_ordinary(text))
        .collect();
    let mut parts = Vec::new();
    for (source_index, tokens) in encoded.iter().enumerate() {
        let part_count = tokens.len().div_ceil(max_tokens_per_input);
        for (part_index, slice) in tokens.chunks(max_tokens_per_input).enumerate() {
            let token_start = part_index
                .checked_mul(max_tokens_per_input)
                .ok_or_else(|| PyValueError::new_err("token range overflow"))?;
            let token_end = token_start
                .checked_add(slice.len())
                .ok_or_else(|| PyValueError::new_err("token range overflow"))?;
            let text = tokenizer
                .decode(slice.to_vec())
                .map_err(|_| PyValueError::new_err("token decode failed"))?;
            parts.push(PackedPart {
                source_index,
                part_index,
                part_count,
                token_start,
                token_end,
                token_count: slice.len(),
                text,
            });
        }
    }
    let mut shards = Vec::new();
    let mut current = Vec::new();
    let mut current_tokens = 0usize;
    for (index, part) in parts.iter().enumerate() {
        let next = checked_token_total(current_tokens, part.token_count)?;
        if !current.is_empty() && (current.len() >= max_inputs || next > max_total_tokens) {
            shards.push(std::mem::take(&mut current));
            current_tokens = 0;
        }
        current_tokens = checked_token_total(current_tokens, part.token_count)?;
        current.push(index);
    }
    if !current.is_empty() {
        shards.push(current);
    }
    Ok((parts, shards))
}

#[pymodule]
fn _token_packer(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PackedPart>()?;
    module.add_function(wrap_pyfunction!(pack_cl100k, module)?)?;
    module.add_function(wrap_pyfunction!(sum_token_counts, module)?)?;
    module.add_function(wrap_pyfunction!(weighted_average_embeddings, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn exact_token_text(token_count: usize) -> String {
        let tokenizer = cl100k_base().unwrap();
        let unit = tokenizer.encode_ordinary(" x");
        assert_eq!(unit.len(), 1);
        tokenizer.decode(vec![unit[0]; token_count]).unwrap()
    }

    #[test]
    fn utf8_korean_emoji_combining_and_order_are_preserved() {
        Python::with_gil(|_| {
            let inputs = vec!["한국어🙂e\u{301}".into(), "두 번째🙂".into()];
            let (parts, shards) = pack_cl100k(inputs.clone(), 8192, 2048, 300_000).unwrap();
            assert!(parts.iter().all(|part| part.token_count <= 8192));
            assert_eq!(parts.last().unwrap().source_index, 1);
            assert_eq!(
                parts
                    .iter()
                    .map(|part| part.text.as_str())
                    .collect::<Vec<_>>(),
                inputs.iter().map(String::as_str).collect::<Vec<_>>()
            );
            assert_eq!(shards.iter().flatten().count(), parts.len());
        });
    }

    #[test]
    fn rejects_empty_input_and_nonpositive_limits() {
        Python::with_gil(|_| {
            assert!(pack_cl100k(vec![String::new()], 8192, 2048, 300_000).is_err());
            assert!(pack_cl100k(vec!["x".into()], 0, 2048, 300_000).is_err());
        });
    }

    #[test]
    fn per_input_boundary_is_exact_at_8192_and_8193() {
        Python::with_gil(|_| {
            let (exact, _) =
                pack_cl100k(vec![exact_token_text(8192)], 8192, 2048, 300_000).unwrap();
            assert_eq!(
                exact
                    .iter()
                    .map(|part| part.token_count)
                    .collect::<Vec<_>>(),
                vec![8192]
            );
            let (over, _) = pack_cl100k(vec![exact_token_text(8193)], 8192, 2048, 300_000).unwrap();
            assert_eq!(
                over.iter().map(|part| part.token_count).collect::<Vec<_>>(),
                vec![8192, 1]
            );
            assert_eq!(
                (
                    over[0].token_start,
                    over[0].token_end,
                    over[1].token_start,
                    over[1].token_end
                ),
                (0, 8192, 8192, 8193)
            );
        });
    }

    #[test]
    fn total_token_boundary_is_exact_at_300000_and_300001() {
        Python::with_gil(|_| {
            let inputs = vec![exact_token_text(7500); 40];
            let (_, exact) = pack_cl100k(inputs, 8192, 2048, 300_000).unwrap();
            assert_eq!(exact.len(), 1);
            assert_eq!(exact[0].len(), 40);
            let mut over_inputs = vec![exact_token_text(7500); 40];
            over_inputs.push(exact_token_text(1));
            let (_, over) = pack_cl100k(over_inputs, 8192, 2048, 300_000).unwrap();
            assert_eq!(over.iter().map(Vec::len).collect::<Vec<_>>(), vec![40, 1]);
        });
    }

    #[test]
    fn input_count_boundary_is_exact_at_2048_and_2049() {
        Python::with_gil(|_| {
            let (_, exact) = pack_cl100k(vec!["x".into(); 2048], 8192, 2048, 300_000).unwrap();
            assert_eq!(exact.iter().map(Vec::len).collect::<Vec<_>>(), vec![2048]);
            let (_, over) = pack_cl100k(vec!["x".into(); 2049], 8192, 2048, 300_000).unwrap();
            assert_eq!(over.iter().map(Vec::len).collect::<Vec<_>>(), vec![2048, 1]);
        });
    }

    #[test]
    fn checked_total_fails_closed_on_integer_overflow() {
        Python::with_gil(|_| {
            assert!(checked_token_total(usize::MAX, 1).is_err());
            assert!(sum_token_counts(vec![usize::MAX, 1]).is_err());
        });
    }

    #[test]
    fn vector_reduction_and_token_sum_are_rust_owned() {
        Python::with_gil(|_| {
            assert_eq!(sum_token_counts(vec![2, 3, 5]).unwrap(), 10);
            assert_eq!(
                weighted_average_embeddings(vec![(vec![1.0, 3.0], 1), (vec![3.0, 5.0], 3)])
                    .unwrap(),
                vec![2.5, 4.5]
            );
            assert!(weighted_average_embeddings(vec![(vec![f64::INFINITY], 1)]).is_err());
        });
    }
}
