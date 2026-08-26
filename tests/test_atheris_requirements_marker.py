"""Keep the optional native Atheris dependency out of unsupported interpreters."""

from pathlib import Path


def test_atheris_lock_keeps_exact_cpython_312_marker() -> None:
    """The generated lock must not widen the Atheris marker to Python 3.10."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "fuzz/requirements-atheris.in").read_text(encoding="utf-8")
    lock = (root / "fuzz/requirements-atheris.txt").read_text(encoding="utf-8")
    assert 'python_version == "3.12"' in source
    assert "atheris==3.1.0 ; python_version == '3.12'" in lock
    assert "atheris==3.1.0 ; python_full_version < '3.13'" not in lock
