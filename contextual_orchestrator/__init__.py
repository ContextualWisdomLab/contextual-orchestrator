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
from .orchestrator import ModelAgent, ModelClient as _ModelClient, TaskOrchestrator, WorkflowStep, load_agents
from .provider_transport import install_provider_transport as _install_provider_transport
from .token_counting import HeuristicTokenCounter, build_token_counter

_install_provider_transport(_ModelClient)

# The NVIDIA NIM benchmark is an optional evaluation adapter rather than a
# runtime dependency.  Importing the module does not perform network I/O.  Its
# installer reuses the same reviewed provider-egress boundary as the standalone
# runtime and adds evidence/budget contracts to the benchmark functions before
# callers import the adapter from this package.
from . import nim_benchmark as _nim_benchmark  # noqa: E402
from .nim_benchmark_hardening import (  # noqa: E402
    install_nim_benchmark_hardening as _install_nim_benchmark_hardening,
)

_install_nim_benchmark_hardening(_nim_benchmark)

__all__ = [
    "ModelAgent",
    "TaskOrchestrator",
    "WorkflowStep",
    "load_agents",
    "get_credential",
    "register_credential",
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
