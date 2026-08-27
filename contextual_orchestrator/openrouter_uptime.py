from __future__ import annotations
"""Background telemetry collector for OpenRouter upstream endpoints."""
import json
import logging
import threading
import time
import urllib.request
import urllib.error
from typing import Any

from .benchmark_priors import resolve_quality_prior
from .model_group import ModelGroupRouter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orchestrator import ModelAgent

logger = logging.getLogger(__name__)

class OpenRouterUptimeCollector:
    """Periodically fetches upstream reliability from OpenRouter for active models."""
    
    def __init__(
        self,
        agents: list[ModelAgent],
        group_router: ModelGroupRouter,
        quality_router: ModelGroupRouter,
        interval_seconds: float = 300.0,
    ) -> None:
        self._openrouter_agents = [a for a in agents if a.provider_name == "openrouter"]
        self._group_router = group_router
        self._quality_router = quality_router
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        
    def start(self) -> None:
        if not self._openrouter_agents:
            return
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run_loop,
                name="OpenRouterUptimeCollector",
                daemon=True,
            )
            self._thread.start()
            
    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            
    def _run_loop(self) -> None:
        # Initial sleep to avoid blocking startup
        if self._stop_event.wait(5.0):
            return
            
        while not self._stop_event.is_set():
            for agent in self._openrouter_agents:
                if self._stop_event.is_set():
                    break
                
                # Fetch endpoint stats
                uptime = self._fetch_uptime(agent.id)
                if uptime is not None:
                    baseline_alpha, baseline_beta = resolve_quality_prior(agent.id)
                    new_alpha, new_beta = self._adjust_prior(baseline_alpha, baseline_beta, uptime)
                    
                    self._group_router.update_prior(agent.id, new_alpha, new_beta)
                    self._quality_router.update_prior(agent.id, new_alpha, new_beta)
                    
                # Rate limit requests
                if self._stop_event.wait(1.0):
                    break
                    
            if self._stop_event.wait(self._interval_seconds):
                break
                
    def _fetch_uptime(self, model_id: str) -> float | None:
        # Example model_id might contain the prefix, OpenRouter expects exactly what was discovered.
        url = f"https://openrouter.ai/api/v1/models/{model_id}/endpoints"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
                endpoints = payload.get("data", {}).get("endpoints", [])
                
                # Average the uptime across all upstreams for this model, or take min?
                # Usually OpenRouter routes to the best one, so max uptime is appropriate.
                uptimes = [
                    float(ep["uptime_last_30m"]) 
                    for ep in endpoints 
                    if ep.get("uptime_last_30m") is not None
                ]
                if uptimes:
                    return max(uptimes)
        except Exception as e:
            logger.debug(f"Failed to fetch OpenRouter uptime for {model_id}: {e}")
        return None
        
    @staticmethod
    def _adjust_prior(alpha: float, beta: float, uptime: float) -> tuple[float, float]:
        if uptime >= 99.9:
            return alpha, beta
        
        # Scale uptime penalty: e.g. 95% -> add 50 beta, 50 alpha
        # Weight of the uptime prior
        weight = 50.0
        uptime_clamped = max(0.0, min(100.0, uptime))
        added_alpha = (uptime_clamped / 100.0) * weight
        added_beta = ((100.0 - uptime_clamped) / 100.0) * weight
        
        return alpha + added_alpha, beta + added_beta
