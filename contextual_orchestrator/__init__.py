"""Public package exports for the contextual orchestration runtime."""

from pkgutil import extend_path

# The ABI3 Rust extension is installed by a wheel while local development and
# CI import Python sources from the checkout. Extend the regular package path so
# the source package can find the wheel-owned native submodule.
__path__ = extend_path(__path__, __name__)

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
    ProviderEmbeddingBatchBackend,
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
from .orchestrator import ModelAgent, TaskOrchestrator, WorkflowStep, load_agents
from .release_authorization import evaluate_release_authorization
from .reasoning_effort_profile import (
    EffortProfileError,
    ReasoningEffortProfile,
    apply_request_profile,
    default_role_effort_catalog,
    parse_reasoning_effort_profile,
    snapshot_role_effort_catalog,
)
from .token_counting import HeuristicTokenCounter, RustCl100kTokenCounter, build_token_counter
from .response_cache import (
    RedisResponseCacheProvider,
    ResponseCacheProvider,
    build_response_cache_key,
)
from .tool_fallback import (
    MAX_TOOL_RETRY_ATTEMPTS,
    ToolExecutionError,
    ToolFallbackAction,
    ToolFallbackStoppedError,
    ToolFailureDecision,
    ToolFailureKind,
    classify_tool_failure,
)

__all__ = [
    "ModelAgent",
    "TaskOrchestrator",
    "WorkflowStep",
    "load_agents",
    "ReasoningEffortProfile",
    "EffortProfileError",
    "apply_request_profile",
    "default_role_effort_catalog",
    "parse_reasoning_effort_profile",
    "snapshot_role_effort_catalog",
    "MAX_TOOL_RETRY_ATTEMPTS",
    "ToolExecutionError",
    "ToolFallbackAction",
    "ToolFallbackStoppedError",
    "ToolFailureDecision",
    "ToolFailureKind",
    "classify_tool_failure",
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
    "RustCl100kTokenCounter",
    "build_token_counter",
    "ResponseCacheProvider",
    "RedisResponseCacheProvider",
    "build_response_cache_key",
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
    "ProviderEmbeddingBatchBackend",
    "heuristic_embedding",
    "build_embeddings_jsonl_body",
    "cheapest_upstream",
    "CostRoutingCoordinator",
    "evaluate_release_authorization",
]
