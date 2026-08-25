from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402

ROOT_DIR = Path(__file__).resolve().parents[1]


class RecordingClient:
    def __init__(self) -> None:
        self.calls = []

    def chat(self, agent: ModelAgent, messages, temperature: float = 0.2) -> str:
        self.calls.append((agent.id, messages))
        return f"{agent.id}:{len(self.calls)}"


def build(client: RecordingClient | None = None) -> TaskOrchestrator:
    return TaskOrchestrator(
        [
            ModelAgent("planner_agent", "mock-planner", tags=("planning", "reasoning")),
            ModelAgent("builder_agent", "mock-builder", tags=("coding", "implementation"), priority=1),
            ModelAgent("reviewer_agent", "mock-reviewer", tags=("verification", "security", "review"), priority=2),
        ],
        client=client,
    )


def test_fugu_contract_fuses_fast_route_and_deep_workflow() -> None:
    orchestrator = build()

    fast = orchestrator.complete([{"role": "user", "content": "Write one sentence."}], mode="auto")
    deep = orchestrator.complete(
        [{"role": "user", "content": "Analyze the architecture, implement the code, and verify risks."}],
        mode="auto",
    )

    assert fast["mode"] == "route"
    assert deep["mode"] == "conduct"


def test_trinity_contract_has_explicit_thinker_worker_verifier_roles() -> None:
    result = build().conduct([{"role": "user", "content": "Analyze and implement a safe parser."}])

    assert ["thinker", "worker", "verifier"] == [step["role"] for step in result["trace"][:3]]


def test_conductor_contract_uses_access_lists_to_control_context() -> None:
    client = RecordingClient()
    build(client).conduct([{"role": "user", "content": "Analyze, implement, verify, and synthesize."}])

    worker_prompt = client.calls[1][1][1]["content"]
    verifier_prompt = client.calls[2][1][1]["content"]

    assert "Step 0: planner_agent:1" in worker_prompt
    assert "Step 1: builder_agent:2" not in worker_prompt
    assert "Step 0: planner_agent:1" in verifier_prompt
    assert "Step 1: builder_agent:2" in verifier_prompt


def test_adr_records_include_verified_paper_and_standard_references() -> None:
    """docs/adr is the citation-backed architecture series, not planning/adrs."""
    index = (ROOT_DIR / "docs/adr/README.md").read_text(encoding="utf-8")
    fallback = (ROOT_DIR / "docs/adr/0001-tool-execution-fallback-policy.md").read_text(
        encoding="utf-8"
    )
    control_plane = (ROOT_DIR / "docs/adr/0002-control-plane-orchestrator.md").read_text(
        encoding="utf-8"
    )
    cost_routing = (ROOT_DIR / "docs/adr/0003-cost-aware-sync-batch-routing.md").read_text(
        encoding="utf-8"
    )
    msa_leaf = (ROOT_DIR / "docs/adr/0004-msa-leaf-composition.md").read_text(encoding="utf-8")

    assert "docs/planning/adrs/" in index
    assert "not a second source of truth for the same number" in index
    assert "0001-tool-execution-fallback-policy.md" in index
    assert "0002-control-plane-orchestrator.md" in index
    assert "0003-cost-aware-sync-batch-routing.md" in index
    assert "0004-msa-leaf-composition.md" in index

    assert "## References" in fallback
    assert "https://doi.org/10.17487/RFC9110" in fallback
    assert "https://doi.org/10.6028/NIST.SP.800-53r5" in fallback
    assert "https://doi.org/10.6028/NIST.SP.800-204" in fallback
    assert "section 9.2.2" in fallback
    assert "SI-11" in fallback
    assert "SC-24" in fallback

    assert "https://doi.org/10.48550/arXiv.2512.04695" in control_plane
    assert "https://doi.org/10.48550/arXiv.2512.04388" in control_plane
    assert "https://sakana.ai/fugu-release/" in control_plane
    assert "[Preprint]" in control_plane
    assert "deterministic capability-hint heuristic" in control_plane
    assert "not a trained Fugu, TRINITY, or Conductor clone" in control_plane

    assert "https://doi.org/10.48550/arXiv.2305.05176" in cost_routing
    assert "https://doi.org/10.48550/arXiv.2406.18665" in cost_routing
    assert "https://doi.org/10.48550/arXiv.2404.14618" in cost_routing
    assert "Learned routers are future work" in cost_routing
    assert "deterministic and config-driven" in cost_routing

    assert "injected client" in msa_leaf
    assert "same interpreter" in msa_leaf
    assert "planning ADR 0001" in msa_leaf
    assert "naruon and gyeot are permitted callers" in msa_leaf
    assert "https://doi.org/10.6028/NIST.SP.800-204" in msa_leaf


if __name__ == "__main__":  # pragma: no cover
    test_fugu_contract_fuses_fast_route_and_deep_workflow()
    test_trinity_contract_has_explicit_thinker_worker_verifier_roles()
    test_conductor_contract_uses_access_lists_to_control_context()
    test_adr_records_include_verified_paper_and_standard_references()
    print("ok")
