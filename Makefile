.PHONY: rust-extension test

rust-extension:
	uv run --with 'maturin>=1.8,<2' maturin build --manifest-path rust/token_counter/Cargo.toml --locked --out dist

test: rust-extension
	uv run --no-project --with dist/*.whl --with-requirements requirements.lock --with-requirements fuzz/requirements-property.txt python -m pytest -q
