//! Exact cl100k token-count service for provider request packing.

use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::io::{self, BufRead, Write};
use tiktoken_rs::cl100k_base;

#[derive(Deserialize)]
struct Request {
    texts: Vec<String>,
}

#[derive(Serialize)]
struct Response {
    counts: Vec<usize>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let tokenizer = cl100k_base()?;
    let stdin = io::stdin();
    let mut stdout = io::BufWriter::new(io::stdout().lock());
    for line in stdin.lock().lines() {
        let request: Request = serde_json::from_str(&line?)?;
        let counts = request
            .texts
            .par_iter()
            .map(|text| tokenizer.encode_ordinary(text).len())
            .collect();
        serde_json::to_writer(&mut stdout, &Response { counts })?;
        writeln!(&mut stdout)?;
        stdout.flush()?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cl100k_reference_fixture_counts_are_exact() {
        let tokenizer = cl100k_base().expect("cl100k vocabulary");
        assert_eq!(tokenizer.encode_ordinary("").len(), 0);
        assert_eq!(tokenizer.encode_ordinary("hello world").len(), 2);
        assert_eq!(tokenizer.encode_ordinary("hello, world!").len(), 4);
    }
}
