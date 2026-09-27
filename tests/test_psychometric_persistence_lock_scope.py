"""Concurrency contract for psychometric observation persistence."""

from __future__ import annotations

import threading

from contextual_orchestrator import ModelAgent, TaskOrchestrator


def test_contextual_quality_embedding_runs_outside_persistence_lock(monkeypatch) -> None:
    """Provider-latency work must not serialize unrelated psychometric persistence."""
    orchestrator = TaskOrchestrator([ModelAgent("model_a", "model-a")])
    probe_done = threading.Event()
    lock_available: list[bool] = []

    def probe_embed(_prompt: str) -> list[float]:
        """Probe the persistence lock from another thread while embedding is in flight."""

        def probe() -> None:
            acquired = orchestrator._psychometric_persistence_lock.acquire(timeout=0.2)
            lock_available.append(acquired)
            if acquired:
                orchestrator._psychometric_persistence_lock.release()
            probe_done.set()

        thread = threading.Thread(target=probe)
        thread.start()
        assert probe_done.wait(timeout=1)
        thread.join(timeout=1)
        assert not thread.is_alive()
        return [0.1, 0.2]

    monkeypatch.setattr(orchestrator, "_embed_cached", probe_embed)
    try:
        orchestrator._observe_contextual_quality(
            "system/user",
            "model_a",
            accepted=True,
            latency_seconds=0.1,
            output_tokens=10,
        )
        assert lock_available == [True]
    finally:
        orchestrator.close()


def test_contextual_quality_revalidates_candidate_after_embedding(monkeypatch) -> None:
    """Drop an observation when the served deployment changes during embedding."""
    orchestrator = TaskOrchestrator(
        [ModelAgent("model_a", "model-a", priority=1)]
    )
    patch_done = threading.Event()
    patch_threads: list[threading.Thread] = []
    patch_errors: list[BaseException] = []
    completed_during_embedding: list[bool] = []

    def patch_candidate() -> None:
        try:
            orchestrator.patch_agent("default", "model_a", {"priority": 2})
        except BaseException as error:  # noqa: BLE001 - preserve worker failure for the joining test
            patch_errors.append(error)
        finally:
            patch_done.set()

    def probe_embed(_prompt: str) -> list[float]:
        """Change the candidate deployment while provider-latency work is in flight."""
        thread = threading.Thread(target=patch_candidate)
        patch_threads.append(thread)
        thread.start()
        completed_during_embedding.append(patch_done.wait(timeout=0.2))
        return [0.1, 0.2]

    monkeypatch.setattr(orchestrator, "_embed_cached", probe_embed)
    try:
        orchestrator._observe_contextual_quality(
            "system/user",
            "model_a",
            accepted=True,
            latency_seconds=0.1,
            output_tokens=10,
        )
        for thread in patch_threads:
            thread.join(timeout=1)
            assert not thread.is_alive()
        assert patch_errors == []
        assert completed_during_embedding == [True]
        assert orchestrator._psychometric_router.records() == []
    finally:
        orchestrator.close()


def test_contextual_quality_rejects_deployment_edited_during_judging(monkeypatch) -> None:
    """An old answer must not become evidence for a newly edited deployment."""
    orchestrator = TaskOrchestrator([ModelAgent("model_a", "model-a", priority=1)])
    monkeypatch.setattr(
        orchestrator, "_invoke",
        lambda *_args, **_kwargs: ("answer", "model_a", "model-a", None),
    )

    def judge(*_args, **_kwargs):
        orchestrator.patch_agent("default", "model_a", {"priority": 2})
        return {"accepted": True, "reason": "accepted", "verifier_output": "answer", "judge": "model"}

    monkeypatch.setattr(orchestrator, "_model_judge_verification", judge)
    monkeypatch.setattr(orchestrator, "_embed_cached", lambda _prompt: [0.1, 0.2])
    try:
        orchestrator.route_once([{"role": "user", "content": "task"}])
        assert orchestrator._psychometric_router.records() == []
    finally:
        orchestrator.close()
