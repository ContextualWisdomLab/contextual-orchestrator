"""Buyer-facing ecosystem pairing note stays present and policy-safe."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_ecosystem_doc_pairs_gateway_with_org_connectors() -> None:
    text = (ROOT / "docs" / "ecosystem.md").read_text(encoding="utf-8")
    for term in (
        "free-router",
        "clearfolio",
        "pg-llm-batch",
        "NVIDIA_NIM_API_KEY",
        "COPILOT_GITHUB_TOKEN",
        "model_group",
        "OpenAI-compatible",
    ):
        assert term in text
    # Live LLM tests must never use review tokens.
    assert "never" in text.lower() and "COPILOT_GITHUB_TOKEN" in text
    assert "docs/ecosystem.md" in (ROOT / "README.md").read_text(encoding="utf-8")


if __name__ == "__main__":
    test_ecosystem_doc_pairs_gateway_with_org_connectors()
    print("ok")
