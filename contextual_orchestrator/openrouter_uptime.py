"""Background availability telemetry for the OpenRouter transport ledger.

Each poll converts the provider's own ``uptime_last_30m`` measurement into
exactly one window's worth of equivalent Bernoulli evidence:

    successes += uptime / 100 ; failures += (100 - uptime) / 100

This retains the existing transport prior's window-equivalent accounting.
Overlapping rolling windows are not independent request trials, and the
provider's best endpoint is not a measured delivered-route success rate.
These summaries never update the answer-quality ledger or its prior.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from .model_group import (
    BETA_PRIOR_FAILURE_COUNT,
    BETA_PRIOR_SUCCESS_COUNT,
    ModelGroupRouter,
)

if TYPE_CHECKING:
    from .orchestrator import ModelAgent

logger = logging.getLogger(__name__)

# Fixed provider origin; only discovery-sourced path segments vary, and
# they are percent-encoded below before request assembly.
_OPENROUTER_UPTIME_ORIGIN = "https://openrouter.ai/api/v1"


class OpenRouterUptimeCollector:
    """Periodically fold upstream availability into the transport prior."""

    def __init__(
        self,
        agents: list[ModelAgent],
        group_router: ModelGroupRouter,
        interval_seconds: float = 300.0,
        startup_delay_seconds: float = 5.0,
    ) -> None:
        """Start bounded to openrouter members owned by the caller.

        Args:
            agents: Orchestrator candidates scanned for openrouter members.
            group_router: Transport ledger receiving uptime evidence.
            interval_seconds: Wall-clock pause between full sweeps.
            startup_delay_seconds: Pause before the first sweep so orchestrator
                construction stays non-blocking; tests inject smaller values.
        """
        self._interval_seconds = interval_seconds
        self._startup_delay_seconds = startup_delay_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._group_router = group_router
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
        """Fold one endpoint measurement into transport window evidence."""
        if agent.provider_name != "openrouter":
            return
        uptime = self._fetch_uptime(agent.model)
        if uptime is None:
            return
        successes = uptime / 100.0
        failures = 1.0 - successes
        prev_alpha, prev_beta = self._window_evidence.get(agent.id, (0.0, 0.0))
        next_alpha = prev_alpha + successes
        next_beta = prev_beta + failures
        self._window_evidence[agent.id] = (next_alpha, next_beta)
        self._group_router.update_prior(
            agent.id,
            BETA_PRIOR_SUCCESS_COUNT + next_alpha,
            BETA_PRIOR_FAILURE_COUNT + next_beta,
        )

    def _fetch_uptime(self, model_id: str) -> float | None:
        """Fetch best-endpoint 30-minute availability for one logical model.

        Args:
            model_id: Discovery-sourced ``author/slug`` model identifier.

        Returns:
            The highest finite numeric endpoint uptime in ``[0, 100]``, or
            ``None`` when any supplied percentage is invalid or none exists.
            Null/missing measurements are absent, not observed failures.
        """
        model_parts = model_id.split("/")
        if len(model_parts) != 2 or any(part in {"", ".", ".."} for part in model_parts):
            return None
        model_path = "/".join(urllib.parse.quote(part, safe="") for part in model_parts)
        url = f"{_OPENROUTER_UPTIME_ORIGIN}/models/{model_path}/endpoints"
        request = urllib.request.Request(url, method="GET")
        try:
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected - scheme/host is the fixed constant origin; author and slug are separately percent-encoded and cannot reach the scheme/authority.
            with urllib.request.urlopen(request, timeout=10.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                endpoints = payload.get("data", {}).get("endpoints", [])
                uptimes = [
                    endpoint["uptime_last_30m"]
                    for endpoint in endpoints
                    if isinstance(endpoint, dict)
                    and endpoint.get("uptime_last_30m") is not None
                ]
                # Validate before aggregation: coercion or clamping can turn
                # booleans, NaN, or out-of-range values into availability mass.
                if any(type(value) not in (int, float) or not 0 <= value <= 100 for value in uptimes):
                    raise ValueError("endpoint uptime must be a numeric percentage in [0, 100]")
                if uptimes:
                    # Best reported endpoint availability, not the actual
                    # caller's route mix or an answer-correctness measurement.
                    return float(max(uptimes))
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
