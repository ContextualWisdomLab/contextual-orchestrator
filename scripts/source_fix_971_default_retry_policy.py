#!/usr/bin/env python3
"""One-shot repair: remove the unproven default provider retry allocation."""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact replacement, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, addition: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + addition.strip() + "\n", encoding="utf-8")


replace_once(
    "contextual_orchestrator/orchestrator.py",
    "        max_retries: int = 2,\n",
    "        max_retries: int = 0,\n",
)
replace_once(
    "contextual_orchestrator/orchestrator.py",
    'class ModelClient:\n    """Small chat-completions client with retry, backoff, and mock support."""\n',
    'class ModelClient:\n    """Small chat-completions client with fail-closed default transport semantics.\n\n    Automatic provider retries are disabled by default. A nonzero ``max_retries``\n    remains an explicit caller policy surface for separately governed callers;\n    this package does not infer a retry count from provider/model identity.\n    """\n',
)

append_once(
    "docs/adr/0001-tool-execution-fallback-policy.md",
    "## Amendment (2026-09-02): no library-authored default provider retry count",
    '''## Amendment (2026-09-02): no library-authored default provider retry count

The earlier provider-transport amendment stated that retryable model-provider
failures receive one same-agent retry before failover. That count was not
identified by RFC 9110, NIST SP 800-204, Fugu, Conductor, TRINITY, or a
repository experiment estimating an optimal retry allocation. It is therefore
not an authoritative default under the no-heuristics contract.

`ModelClient` now defaults `max_retries` to `0` for remote and local providers.
A default request makes exactly one provider attempt and then exposes the typed
provider failure to the orchestrator/caller. The failure taxonomy remains useful
for audit and for callers that bring an independently governed explicit retry
policy; taxonomy membership alone no longer manufactures an extra inference
attempt. The default is provider-, model-, and reasoning-capability-neutral.

RFC 9110 section 9.2.2 constrains *when* automatic retries can be safe for
idempotent semantics, but it does not prescribe a retry count. NIST SP 800-204
similarly discusses retry/circuit-breaker patterns without identifying this
package's previous count. When no count is identified by evidence, the known
fail-closed state is no automatically allocated retry.

This amendment supersedes only the previous statement assigning one default
same-agent provider retry. Explicit tool side-effect safety and typed provider
failure classification remain unchanged.''',
)

append_once(
    "docs/product-technical-gap-baseline.md",
    "## 2026-09-02 — default provider retry allocation fails closed",
    '''## 2026-09-02 — default provider retry allocation fails closed

**Live gap / RCA.** `ModelClient(max_retries=2)` allocated two additional
provider attempts to every default remote model request. PR #971 also depended
on a separately chosen one-retry caller policy for transient HTTP failures.
RFC 9110 and NIST SP 800-204 support idempotency-aware retry safety and
resilience patterns, but neither identifies the repository's numeric retry
budget. Fugu, Conductor, and TRINITY likewise do not establish that count.
The causal owner is the contextual-orchestrator transport default, not any
particular provider or reasoning-model family.

**Owner repair.** The library default is now `max_retries=0`. Default inference
therefore performs one provider attempt and exposes typed failure evidence;
it does not synthesize additional test-time compute from an HTTP status,
provider name, model name, or capability flag. Existing explicit nonzero retry
arguments remain caller-owned compatibility configuration and are not promoted
by this change into evidence-backed defaults.

**Verification contract.** `tests/test_no_heuristic_default_transport_retry.py`
requires zero default retry allocation for arbitrary providers/models and proves
reasoning capability cannot change it. The one-shot repair workflow must first
observe that regression RED on the pre-repair tree, then apply this exact
source/docs change, run the focused provider suites, self-remove, and publish
only by non-force fast-forward. Hosted exact-head checks remain authoritative.''',
)

changelog = Path("CHANGELOG.md")
text = changelog.read_text(encoding="utf-8")
entry = (
    "- Default provider transport no longer invents two same-agent retries: "
    "`ModelClient` now fails closed with `max_retries=0` unless a caller supplies "
    "a separately governed explicit policy; ADR 0001 and the product-gap baseline "
    "record why RFC 9110/NIST resilience guidance does not identify the retired count.\n"
)
if entry not in text:
    if "## [Unreleased]" in text:
        text = text.replace("## [Unreleased]\n", "## [Unreleased]\n" + entry, 1)
    elif "## Unreleased" in text:
        text = text.replace("## Unreleased\n", "## Unreleased\n" + entry, 1)
    else:
        text = entry + "\n" + text
    changelog.write_text(text, encoding="utf-8")

print("source-fix-971: default transport retry allocation removed")
