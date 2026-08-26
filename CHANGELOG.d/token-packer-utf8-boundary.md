- Preserve complete UTF-8 scalar values when the Rust embedding token packer
  divides an input at a provider token ceiling, and fail closed when the
  configured ceiling cannot contain one decodable scalar.
