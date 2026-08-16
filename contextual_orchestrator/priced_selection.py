"""Paper-grounded min-cost / max-performance selection of a single worker.

This module is the unique selection slice that PR #642 does not own. It does
**not** walk a ranked next-agent failover list. Fugu's low-latency path picks
one worker without a coordinator search (Sakana AI, 2026). FrugalGPT and
Hybrid LLM then break remaining ties by billed cost, then by capability
(performance) score. Transient retry stays on the chosen worker
(``ModelClient``); a circuit-open agent is excluded from the *next* selection,
not hopped mid-request.

See ``docs/doctoring/priced-selection.md`` for APA 7th citations.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence


def billed_selection_cost(
    agent: Any,
    *,
    price_book: Any | None,
    price_per_million: dict[str, float],
    any_explicit_price: bool,
) -> float | None:
    """Return the billed ranking cost, or ``None`` when the model is unpriced.

    Promotional-free rows (explicit price ``0``) rank as cost ``0``. Unpriced
    models return ``None`` so they are not treated as free. ``original_list_price``
    is never used as the billed cost.
    """
    model = getattr(agent, "model", "")
    provider = getattr(agent, "provider_name", "") or "default"
    if price_book is not None:
        entry = price_book.get_price(provider, model)
        if entry is not None:
            cost, _currency = price_book.compute_cost(provider, model, 1000, 1000)
            return float(cost)
    if model in price_per_million:
        # price_per_million is USD / 1M output tokens; a 1k/1k probe uses output only.
        return float(price_per_million[model]) / 1000.0
    _ = any_explicit_price
    return None


def select_min_cost_max_performance(
    agents: Sequence[Any],
    *,
    role: str,
    capability_score: Callable[[Any], tuple[Any, ...]],
    billed_cost: Callable[[Any], float | None],
    is_circuit_open: Callable[[str], bool],
) -> Any:
    """Pick exactly one eligible agent: min billed cost, then max performance.

    Eligibility: not disabled, role not in ``provider_exclusions``. Circuit-open
    agents are skipped when any healthy eligible agent remains; if every
    eligible agent is open the best eligible agent is still returned so a
    probe can run. The return value is a single agent, never a failover list.
    """
    eligible = [
        agent
        for agent in agents
        if not getattr(agent, "disabled", False)
        and role not in getattr(agent, "provider_exclusions", ())
    ]
    if not eligible:
        raise RuntimeError(f"no eligible agent available for role={role}")
    healthy = [agent for agent in eligible if not is_circuit_open(agent.id)]
    pool = healthy or eligible

    def prefer(agent: Any) -> tuple[Any, ...]:
        cost = billed_cost(agent)
        # Known prices sort before unknown. Among known, lower billed cost wins.
        # Among equal cost, higher capability tuple wins (same orientation as
        # ``_score_agent``: larger is better).
        cost_rank = (0, -cost) if cost is not None else (-1, 0.0)
        return (cost_rank, capability_score(agent), agent.id)

    return max(pool, key=prefer)
