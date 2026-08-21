from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402
from contextual_orchestrator.orchestrator import _responses_to_chat_payload  # noqa: E402


IMAGE_PART = {
    "type": "image_url",
    "image_url": {
        "url": "data:image/png;base64,c3ludGhldGljLWZpeHR1cmU=",
        "detail": "high",
    },
}


class RecordingClient:
    """Record synthetic provider calls without contacting a model."""

    def __init__(self, failing_agent_id: str | None = None) -> None:
        self.failing_agent_id = failing_agent_id
        self.calls: list[tuple[str, list[dict[str, object]]]] = []

    def chat(self, agent: ModelAgent, messages, temperature: float = 0.2) -> str:
        """Return deterministic output, or fail the selected synthetic agent."""
        self.calls.append((agent.id, messages))
        if agent.id == self.failing_agent_id:
            raise RuntimeError("synthetic provider failure")
        return f"{agent.id}:{len(self.calls)}"


def test_conduct_preserves_source_images_for_every_evidence_step() -> None:
    client = RecordingClient()
    orchestrator = TaskOrchestrator(
        [ModelAgent("vision_agent", "mock-vision", tags=("vision",))],
        client=client,
    )

    result = orchestrator.conduct(
        [{"role": "user", "content": [{"type": "text", "text": "Read the table."}, IMAGE_PART]}]
    )

    assert result["mode"] == "conduct"
    assert len(client.calls) == 4
    for agent_id, messages in client.calls:
        assert agent_id == "vision_agent"
        content = messages[-1]["content"]
        assert isinstance(content, list)
        assert content[-1] == IMAGE_PART
        assert "data:image" not in content[0]["text"]


def test_image_route_failover_never_uses_a_text_only_agent() -> None:
    client = RecordingClient(failing_agent_id="vision_primary")
    orchestrator = TaskOrchestrator(
        [
            ModelAgent("text_agent", "mock-text", tags=("reasoning",), priority=100),
            ModelAgent("vision_primary", "mock-vision-primary", tags=("vision",), priority=20),
            ModelAgent("vision_backup", "mock-vision-backup", tags=("vision",), priority=10),
        ],
        client=client,
    )

    result = orchestrator.route_once(
        [{"role": "user", "content": [{"type": "text", "text": "Read the image."}, IMAGE_PART]}]
    )

    assert result["answer"].startswith("vision_backup:")
    assert [agent_id for agent_id, _ in client.calls] == ["vision_primary", "vision_backup"]


def test_image_route_fails_before_io_without_a_vision_agent() -> None:
    client = RecordingClient()
    orchestrator = TaskOrchestrator(
        [ModelAgent("text_agent", "mock-text", tags=("reasoning",))],
        client=client,
    )

    with pytest.raises(RuntimeError, match="required tags.*vision"):
        orchestrator.route_once(
            [{"role": "user", "content": [{"type": "text", "text": "Read it."}, IMAGE_PART]}]
        )

    assert client.calls == []


def test_responses_input_image_is_normalized_for_chat_orchestration() -> None:
    payload = _responses_to_chat_payload(
        {
            "model": "contextual-orchestrator",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Read the table."},
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,c3ludGhldGljLWZpeHR1cmU=",
                            "detail": "high",
                        },
                    ],
                }
            ],
        }
    )

    assert payload["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Read the table."},
                IMAGE_PART,
            ],
        }
    ]


def test_responses_input_image_requires_a_url() -> None:
    with pytest.raises(ValueError, match="image_url"):
        _responses_to_chat_payload(
            {
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_image", "file_id": "synthetic-file"}],
                    }
                ]
            }
        )


def test_responses_image_detail_is_normalized_or_rejected() -> None:
    request = {
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": {"url": "https://example.invalid/synthetic.png", "detail": None},
                    }
                ],
            }
        ]
    }

    assert _responses_to_chat_payload(request)["messages"][0]["content"][0] == {
        "type": "image_url",
        "image_url": {"url": "https://example.invalid/synthetic.png"},
    }
    request["input"][0]["content"][0]["detail"] = "pixel-perfect"
    with pytest.raises(ValueError, match="detail"):
        _responses_to_chat_payload(request)
