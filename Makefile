.PHONY: test

test:
	uv run --locked --extra api --extra db --extra queue --group dev python -m pytest -q
