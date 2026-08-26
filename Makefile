.PHONY: test

test:
	uv run --no-project --with-requirements requirements.lock --with-requirements fuzz/requirements-property.txt python -m pytest -q
