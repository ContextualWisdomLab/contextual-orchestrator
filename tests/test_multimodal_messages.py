"""Native multimodal message validation for the public Chat Completions boundary."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator.orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.server import RequestError, _validate_messages  # noqa: E402


def test_validate_messages_preserves_safe_text_and_image_blocks() -> None:
    messages = _validate_messages([
        {"role": "system", "content": "evidence only"},
        {"role": "user", "content": [
            {"type": "text", "text": "read"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,x", "detail": "high", "extra": "drop"}},
        ]},
    ])

    assert messages[0] == {"role": "system", "content": "evidence only"}
    assert messages[1]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,x", "detail": "high"},
    }


@pytest.mark.parametrize("url", ["http://insecure.example/image.png", "file:///tmp/image.png"])
def test_validate_messages_rejects_unsafe_image_urls(url: str) -> None:
    with pytest.raises(RequestError):
        _validate_messages([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": url}}]}])


def test_latest_user_text_marks_image_content_without_leaking_data() -> None:
    orchestrator = TaskOrchestrator([ModelAgent("general_agent", "mock-model")])

    assert orchestrator._latest_user_text([
        {"role": "assistant", "content": "old"},
        {"role": "user", "content": [
            {"type": "text", "text": "question"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,secret"}},
        ]},
    ]) == "question\n[image]"
