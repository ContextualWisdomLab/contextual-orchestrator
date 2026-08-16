"""Lock pytest collection so helper scripts cannot inject tests."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conftest  # noqa: E402


def test_collect_ignore_excludes_scripts_and_fuzz_harnesses() -> None:
    """scripts/*_test.py helpers must not be collected as the suite."""
    assert "fuzz" in conftest.collect_ignore
    assert "scripts" in conftest.collect_ignore


def test_conftest_documents_why_scripts_are_ignored() -> None:
    text = Path(conftest.__file__).read_text(encoding="utf-8")
    assert "scripts/" in text
    assert "*_test.py" in text


if __name__ == "__main__":  # pragma: no cover
    test_collect_ignore_excludes_scripts_and_fuzz_harnesses()
    test_conftest_documents_why_scripts_are_ignored()
    print("ok")
