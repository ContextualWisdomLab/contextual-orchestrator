"""Contract for the hourly OpenCode maintenance loop."""

import re
from pathlib import Path


def test_hourly_loop_uses_the_local_free_orchestrator_without_copilot_token() -> None:
    """Keep scheduled agent traffic on the governed free pool and required key set."""
    workflow = Path(".github/workflows/opencode-hourly-loop.yml").read_text()
    prompt = Path(".github/opencode/hourly-loop-prompt.md").read_text()

    assert 'cron: "23 * * * *"' in workflow
    assert "--auto-discover-model-agents" in workflow
    assert workflow.count("contextual_orchestrator_gateway/orchestrator/free") == 2
    assert "contextual_orchestrator_gateway/orchestrator/auto" not in workflow
    for credential_name in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert f"{credential_name}: ${{{{ secrets.{credential_name} }}}}" in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "node scripts/ci/install_locked_opencode.mjs" in workflow
    assert "python -m pip install --require-hashes -r requirements.lock" in workflow
    assert "--auth-token-key CONTEXTUAL_ORCHESTRATOR_TOKEN" in workflow
    assert "--auth-token=" not in workflow
    assert "--auth-token " not in workflow
    assert "GATEWAY_BEARER_TOKEN" not in workflow
    assert "umask 077" in workflow
    installer = Path("scripts/ci/install_locked_opencode.mjs").read_text()
    assert "optionalDependencies" in installer
    assert "installed.version !== expectedVersion" in installer
    assert "npm install" not in installer
    assert 'spawnSync(target, ["--version"]' in installer
    assert "no lockfile-authorized OpenCode binary passed its version check" in installer
    assert "fetch(" not in installer
    assert "postinstall.mjs" not in workflow
    assert "pull-requests: write" in workflow
    assert "docs/product-technical-gap-baseline.md" in workflow
    assert "Retry-After" in prompt
    assert "inventing a retry count" in prompt
    assert "Other agents may have pushed concurrently" in prompt
    assert "normal merge" in prompt
    assert "clear redundancy or" in prompt
    assert "Rust is authoritative" in prompt
    assert "LLM-token arithmetic in Python" in prompt


def test_hourly_loop_has_no_repository_authored_model_job_deadline() -> None:
    """Do not terminate model-backed maintenance by a hand-selected wall-clock cap."""
    workflow = Path(".github/workflows/opencode-hourly-loop.yml").read_text()
    prompt = Path(".github/opencode/hourly-loop-prompt.md").read_text()

    loop_header = workflow.split("\n  loop:\n", 1)[1].split("\n    permissions:\n", 1)[0]
    assert "timeout-minutes:" not in loop_header
    assert "at most 45 minutes" not in prompt
    assert "highest-leverage gap" not in prompt
    assert "Do not impose a repository-authored elapsed-time limit on model work" in prompt
    assert "do not invent an ordering" in prompt


def test_hourly_loop_adr_stays_proposed_and_does_not_reopen_auto_routing() -> None:
    """Keep the open-PR decision honest and fail closed without an auto escape hatch."""
    adr = Path("docs/adr/0007-hourly-loop-orchestrator-free-pool-pin.md").read_text()

    assert "- Status: Proposed" in adr
    assert "future GitHub Actions" in adr
    assert "must remain on `orchestrator/free`" in adr
    assert "needs its own ADR amendment" not in adr
    assert "free-catalog exhaustion, not a code defect" not in adr
    assert "not a code defect" not in adr


def test_adr_0007_body_and_index_status_agree_and_stay_proposed_while_open() -> None:
    """Reject a re-run of the Proposed/Accepted contradiction the review comment found.

    ADR-0007's body and its `docs/adr/README.md` index row are two independently
    editable sources of truth for the same status. This PR's review found them
    disagreeing once (body ``Proposed``, index ``Accepted``) while the decision
    was still open/unmerged. Ordinary protected-branch merge with exact-head
    authority is the only event allowed to promote either one to ``Accepted``;
    until then both must read ``Proposed``, and the two must always agree.

    When this ADR is actually accepted, update the body ``Status:`` line, the
    index row, and this test's expected status together in the same commit
    that merges the decision — never one without the other two.
    """
    adr = Path("docs/adr/0007-hourly-loop-orchestrator-free-pool-pin.md").read_text()
    readme = Path("docs/adr/README.md").read_text()

    body_status_match = re.search(r"^- Status:\s*(\S+)\s*$", adr, flags=re.MULTILINE)
    assert body_status_match is not None, "ADR-0007 must declare a `- Status: ...` line"
    body_status = body_status_match.group(1)

    index_row_match = re.search(
        r"^\|\s*\[0007\][^|]*\|[^|]*\|\s*(\S+)\s*\|",
        readme,
        flags=re.MULTILINE,
    )
    assert index_row_match is not None, "docs/adr/README.md must carry an ADR-0007 index row"
    index_status = index_row_match.group(1)

    assert body_status == index_status, (
        "ADR-0007 body status "
        f"({body_status!r}) and docs/adr/README.md index status ({index_status!r}) "
        "must agree"
    )
    # This ADR's implementation PR is still open/unmerged: both sources must
    # read Proposed. Flip this assertion (and the two files) together only in
    # the commit that lands ordinary protected-branch acceptance.
    assert body_status == "Proposed", (
        "ADR-0007 is unmerged: both body and index status must be `Proposed` "
        "until ordinary protected-branch merge grants exact-head acceptance"
    )
