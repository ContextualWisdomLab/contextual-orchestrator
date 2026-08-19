"""Public package exports for the contextual orchestration runtime."""

from .batch_routing import (
    BatchJob,
    BatchRequest,
    BatchResultItem,
    EmbeddingBatchRequest,
    EmbeddingBatchResultItem,
    LocalBatchBackend,
    LocalEmbeddingBatchBackend,
    PgLlmBatchBackend,
    PgLlmBatchEmbeddingBackend,
    RoutingDecision,
    RoutingHints,
    RoutingPolicy,
    build_embeddings_jsonl_body,
    cheapest_upstream,
    heuristic_embedding,
)
from .cost_ledger import (
    ATTRIBUTION_DIMENSIONS,
    AttributionDimensions,
    CostLedger,
    InMemoryLedgerStore,
    InMemoryUsageTelemetrySink,
    NonBlockingLedgerStore,
    NoopUsageTelemetrySink,
    PriceBook,
    PriceEntry,
    SqlLedgerStore,
    UsageTelemetryEvent,
    UsageTelemetryHealth,
    UsageTelemetrySink,
    UsageRecord,
    dimension_catalog,
)
from .cost_router import CostRoutingCoordinator
from .credentials import NotConfigured, get_credential, register_credential
from .kv_config import InMemoryConfigStore, get_config_store
from .model_discovery import (
    DISCOVERY_CREDENTIAL_NAMES,
    FLOOR_DEFAULT_MODEL_ID,
    FLOOR_SMALL_MODEL_ID,
    apply_discovered_pool,
    discover_model_catalog,
    list_served_models,
)
from .orchestrator import ModelAgent, WorkflowStep, load_agents, known_agent_comparison_cost
from .passthrough_failover import ResilientTaskOrchestrator as TaskOrchestrator
from .token_counting import HeuristicTokenCounter, build_token_counter

__all__ = [
    "ModelAgent",
    "TaskOrchestrator",
    "WorkflowStep",
    "load_agents",
    "get_credential",
    "register_credential",
    "NotConfigured",
    "DISCOVERY_CREDENTIAL_NAMES",
    "FLOOR_DEFAULT_MODEL_ID",
    "FLOOR_SMALL_MODEL_ID",
    "apply_discovered_pool",
    "discover_model_catalog",
    "list_served_models",
    "known_agent_comparison_cost",
    # cost review
    "ATTRIBUTION_DIMENSIONS",
    "AttributionDimensions",
    "CostLedger",
    "InMemoryLedgerStore",
    "InMemoryUsageTelemetrySink",
    "NonBlockingLedgerStore",
    "NoopUsageTelemetrySink",
    "SqlLedgerStore",
    "PriceBook",
    "PriceEntry",
    "UsageRecord",
    "UsageTelemetryEvent",
    "UsageTelemetryHealth",
    "UsageTelemetrySink",
    "dimension_catalog",
    # config / tokens
    "InMemoryConfigStore",
    "get_config_store",
    "HeuristicTokenCounter",
    "build_token_counter",
    # routing / batch
    "RoutingPolicy",
    "RoutingHints",
    "RoutingDecision",
    "BatchRequest",
    "BatchJob",
    "BatchResultItem",
    "LocalBatchBackend",
    "PgLlmBatchBackend",
    # embeddings batch
    "EmbeddingBatchRequest",
    "EmbeddingBatchResultItem",
    "LocalEmbeddingBatchBackend",
    "PgLlmBatchEmbeddingBackend",
    "heuristic_embedding",
    "build_embeddings_jsonl_body",
    "cheapest_upstream",
    "CostRoutingCoordinator",
]
