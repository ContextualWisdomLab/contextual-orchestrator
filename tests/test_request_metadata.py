from __future__ import annotations

from contextual_orchestrator import ModelAgent, TaskOrchestrator


class RecordingClient:
    def __init__(self) -> None:
        self.metadata = []

    def chat(self, agent, messages, temperature=None, metadata=None):
        self.metadata.append(metadata)
        return "metadata-aware answer"


def test_post_metadata_reaches_provider_and_workflow_record() -> None:
    client = RecordingClient()
    orchestrator = TaskOrchestrator(
        [ModelAgent("worker_agent", "mock-worker", tags=("coding", "reasoning"))],
        client=client,
    )
    metadata = {
        "lineageweave_post_session_id": "session-1",
        "lineageweave_pu": "PU-01",
        "lineageweave_author_id": "author-1",
        "lineageweave_corp_code": "CORP-01",
    }

    result = orchestrator.run(
        [{"role": "user", "content": "Summarize this post."}],
        mode="route",
        metadata=metadata,
    )

    assert client.metadata == [metadata]
    assert result["metadata"] == metadata
