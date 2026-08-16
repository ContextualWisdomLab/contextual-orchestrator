"""Public package exports for the contextual orchestration runtime.

Importing this module is intentionally side-effect free: provider transports and
optional adapters are configured explicitly by their owning runtime components.
"""

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
from .credentials import NotConfigured, get_credential, register_credential, register_credentials
from .kv_config import (
    ConfigBackendUnavailableError,
    InMemoryConfigStore,
    get_config_store,
)
from .orchestrator import ModelAgent, TaskOrchestrator, WorkflowStep, load_agents
from .token_counting import HeuristicTokenCounter, build_token_counter

__all__ = [
    "ModelAgent",
    "TaskOrchestrator",
    "WorkflowStep",
    "load_agents",
    "get_credential",
    "register_credential",
    "register_credentials",
    "NotConfigured",
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
    "ConfigBackendUnavailableError",
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
