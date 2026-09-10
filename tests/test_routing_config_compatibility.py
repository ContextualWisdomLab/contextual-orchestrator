"""Compatibility coverage for the semantic routing-config KV category."""

from contextual_orchestrator.batch_routing import RoutingHints, RoutingPolicy
from contextual_orchestrator.kv_config import InMemoryConfigStore


def test_injected_store_migrates_legacy_routing_values_before_policy_reads() -> None:
    """Directly injected stores retain persisted routing values after the rename.

    RED until the consumption boundary prepares arbitrary injected stores:
    ``get_config_store()`` cannot help a caller that already constructed a
    compatible store and passes it directly to ``RoutingPolicy``.
    """
    config_store = InMemoryConfigStore(
        {"routing": {"batch_enabled": False}}
    )

    routing_policy = RoutingPolicy(config_store)

    assert routing_policy.decide(RoutingHints(latency_tolerant=True)).channel == "sync"
    assert config_store.get("routing_config", "batch_enabled") is False
