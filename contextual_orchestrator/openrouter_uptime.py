"""Background telemetry collector for OpenRouter upstream endpoints.

Each poll converts the provider's own ``uptime_last_30m`` measurement into
exactly one window's worth of equivalent Bernoulli evidence:

    successes += uptime / 100 ; failures += (100 - uptime) / 100

so the accumulated ``(alpha, beta)`` mass converges to true availability
without any invented weighting constant — every count traces to a poll
outcome and the failure denominator is the number of polls performed.
Auditable counters are exposed for verification.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from .benchmark_priors import resolve_quality_prior
from .model_group import ModelGroupRouter

if TYPE_CHECKING:
    from .orchestrator import ModelAgent

logger = logging.getLogger(__name__)

# Fixed provider origin; only discovery-sourced path segments vary, and
# they are percent-encoded below before request assembly.
_OPENROUTER_UPTIME_ORIGIN = "https://openrouter.ai/api/v1"


class OpenRouterUptimeCollector:
    """Periodically fold measured upstream availability into prior ledgers."""

    def __init__(
        self,
        agents: list["ModelAgent"],
        group_router: ModelGroupRouter,
        quality_router: ModelGroupRouter,
        interval_seconds: float = 300.0,
        startup_delay_seconds: float = 5.0,
    ) -> None:
        """Start bounded to openrouter members owned by the caller.

        Args:
            agents: Orchestrator candidates scanned for openrouter members.
            group_router: Transport ledger receiving uptime evidence.
            quality_router: Quality ledger receiving uptime evidence.
            interval_seconds: Wall-clock pause between full sweeps.
            startup_delay_seconds: Pause before the first sweep so orchestrator
                construction stays non-blocking; tests inject smaller values.
        """
        self._interval_seconds = interval_seconds
        self._startup_delay_seconds = startup_delay_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._group_router = group_router
        self._quality_router = quality_router
        self._openrouter_agents = [a for a in agents if a.provider_name == "openrouter"]
        # agent.id -> empirical window-equivalent (successes, failures).
        self._window_evidence: dict[str, tuple[float, float]] = {}

    def start(self) -> None:
        """Launch the single background sweep thread when work exists."""
        if not self._openrouter_agents or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            name="OpenRouterUptimeCollector",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the sweep thread and wait briefly for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def window_evidence(self, agent_id: str) -> tuple[float, float]:
        """Return accumulated ``(successes, failures)`` window mass, auditable."""
        return self._window_evidence.get(agent_id, (0.0, 0.0))

    def _run_loop(self) -> None:
        """Sweep members until stopped; sleeps stay interruptible."""
        if self._stop_event.wait(self._startup_delay_seconds):
            return
        while not self._stop_event.is_set():
            for agent in self._openrouter_agents:
                if self._stop_event.is_set():
                    break
                self._poll_agent(agent)
                if self._stop_event.wait(1.0):
                    break
            if self._stop_event.wait(self._interval_seconds):
                break

    def _poll_agent(self, agent: ModelAgent) -> None:
        """Fold one endpoint measurement into ledgers as window evidence."""
        if agent.provider_name != "openrouter":
            return
        uptime = self._fetch_uptime(agent.model)
        if uptime is None:
            return
        successes = max(0.0, min(1.0, uptime / 100.0))
        failures = 1.0 - successes
        base_alpha, base_beta = resolve_quality_prior(agent.id)
        prev_alpha, prev_beta = self._window_evidence.get(agent.id, (0.0, 0.0))
        next_alpha = prev_alpha + successes
        next_beta = prev_beta + failures
        self._window_evidence[agent.id] = (next_alpha, next_beta)
        self._apply_to_routers(
            agent.id,
            base_alpha + next_alpha,
            base_beta + next_beta,
        )

    def _apply_to_routers(
        self,
        member_id: str,
        alpha: float,
        beta: float,
    ) -> None:
        """Publish one member's blended prior into both ledgers."""
        self._group_router.update_prior(member_id, alpha, beta)
        self._quality_router.update_prior(member_id, alpha, beta)

    def _fetch_uptime(self, model_id: str) -> float | None:
        """Fetch best-endpoint 30-minute availability for one logical model.

        Args:
            model_id: Discovery-sourced logical model identifier.

        Returns:
            The highest reported endpoint uptime in ``[0, 100]``, or
            ``None`` when the provider response cannot yield one.
        """
        segment = urllib.parse.quote(model_id, safe="")
        url = f"{_OPENROUTER_UPTIME_ORIGIN}/models/{segment}/endpoints"
        request = urllib.request.Request(url, method="GET")
        try:
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected - scheme/host is the fixed constant origin; model_id is percent-encoded before interpolation and never reaches the scheme/authority.
            with urllib.request.urlopen(request, timeout=10.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                endpoints = payload.get("data", {}).get("endpoints", [])
                uptimes = [
                    float(endpoint["uptime_last_30m"])
                    for endpoint in endpoints
                    if isinstance(endpoint, dict)
                    and endpoint.get("uptime_last_30m") is not None
                ]
                if uptimes:
                    # Provider routes to its strongest upstream, so the
                    # observed maximum reflects delivered reliability.
                    return max(uptimes)
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            logger.debug("Failed to fetch OpenRouter uptime for %s: %s", model_id, exc)
        return None
