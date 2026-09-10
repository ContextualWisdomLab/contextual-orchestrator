"""RED for issue #1015: governed reference-case terminology.

The operator UI must present "Reference cases" (ko "참조 평가 사례"), not
"Golden prompts". Currently fails by design.
"""

import pathlib

ADMIN = pathlib.Path(__file__).resolve().parents[1] / "contextual_orchestrator" / "admin.py"


def test_reference_cases_terminology():
    text = ADMIN.read_text(encoding="utf-8")
    assert "Reference cases" in text
    assert "참조 평가 사례" in text
    assert "Golden prompts" not in text
    assert "골든 프롬프트" not in text
