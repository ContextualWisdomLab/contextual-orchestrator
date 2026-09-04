from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contextual_orchestrator import ModelAgent, TaskOrchestrator  # noqa: E402

ROOT_DIR = Path(__file__).resolve().parents[1]


def _scholarly_ids(text: str) -> set[str]:
    """Return normalized identifiers from the scholarly hosts used here."""
    arxiv_ids = {
        match.lower()
        for match in re.findall(
            r"(?:arxiv(?:\.org/(?:abs|pdf)/|\.))([0-9]{4}\.[0-9]{4,5})",
            text,
            flags=re.IGNORECASE,
        )
    }
    doi_ids: set[str] = set()
    for raw_match in re.findall(
        r'(?:doi\.org/|/doi/(?:pdf/)?)(10\.\d{4,9}/[-._;()/:A-Z0-9]+)',
        text,
        flags=re.IGNORECASE,
    ):
        match = raw_match.rstrip(".,;:)").lower()
        for publisher_suffix in ("/html", "/pdf"):
            if match.endswith(publisher_suffix):
                match = match.removesuffix(publisher_suffix)
        if match.startswith(("10.17487/", "10.6028/")):
            continue
        arxiv_doi = re.fullmatch(r"10\.48550/arxiv\.([0-9]{4}\.[0-9]{4,5})", match)
        doi_ids.add(arxiv_doi.group(1) if arxiv_doi else match)
    hosted_ids = {
        match.rstrip(".,;:").lower()
        for match in re.findall(
            r"https?://(?:aclanthology\.org/[^\s)\]}>]+|"
            r"proceedings\.iclr\.cc/[^\s)\]}>]+|"
            r"openreview\.net/forum\?id=[A-Za-z0-9_-]+|"
            r"www\.anthropic\.com/research/[^\s)\]}>]+)",
            text,
            flags=re.IGNORECASE,
        )
    }
    return arxiv_ids | doi_ids | hosted_ids


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
    """Auto mode fuses a fast direct route with deep orchestrated workflows.

    The split decision is the structured triage verdict (one exact-schema
    model call), not keyword matching; mock transports cannot emit that JSON,
    so the verdicts are pinned here to exercise both arms of the fusion.
    """
    orchestrator = build()
    orchestrator._triage_fn = lambda text: "architecture" in text

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

    worker_prompt = client.calls[1][1][-1]["content"]
    verifier_prompt = client.calls[2][1][-1]["content"]

    assert "Step 0: planner_agent:1" in worker_prompt
    assert "Step 1: builder_agent:2" not in worker_prompt
    assert "Step 0: planner_agent:1" in verifier_prompt
    assert "Step 1: builder_agent:2" in verifier_prompt


def _adr_text(relative_path: str) -> str:
    raw = (ROOT_DIR / relative_path).read_text(encoding="utf-8")
    return " ".join(raw.split())


def test_adr_records_include_verified_paper_and_standard_references() -> None:
    """docs/adr is the citation-backed architecture series, not planning/adrs."""
    index = _adr_text("docs/adr/README.md")
    fallback = _adr_text("docs/adr/0001-tool-execution-fallback-policy.md")
    control_plane = _adr_text("docs/adr/0002-control-plane-orchestrator.md")
    cost_routing = _adr_text("docs/adr/0003-cost-aware-sync-batch-routing.md")
    msa_leaf = _adr_text("docs/adr/0004-msa-leaf-composition.md")

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


def test_paper_inventory_covers_tracked_research_identifiers() -> None:
    """Every scholarly identifier used by code/docs stays in the paper register."""
    inventory_path = ROOT_DIR / "docs/papers/README.md"
    inventory_ids = _scholarly_ids(inventory_path.read_text(encoding="utf-8"))
    referenced_ids: set[str] = set()
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py", "*.md"],
        cwd=ROOT_DIR,
        check=True,
        capture_output=True,
    ).stdout.decode().split("\0")
    for relative in tracked:
        path = ROOT_DIR / relative
        if not relative or path == inventory_path or any(
            part.startswith(".") for part in Path(relative).parts
        ):
            continue
        referenced_ids.update(_scholarly_ids(path.read_text(encoding="utf-8")))

    assert referenced_ids <= inventory_ids, sorted(referenced_ids - inventory_ids)


if __name__ == "__main__":  # pragma: no cover
    test_fugu_contract_fuses_fast_route_and_deep_workflow()
    test_trinity_contract_has_explicit_thinker_worker_verifier_roles()
    test_conductor_contract_uses_access_lists_to_control_context()
    test_adr_records_include_verified_paper_and_standard_references()
    print("ok")
