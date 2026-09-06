"""Public package exports for the contextual orchestration runtime."""

from . import batch_routing as _batch_routing
from .batch_routing import (
    BatchDownloadError,
    BatchJob,
    BatchRequest,
    BatchResultItem,
    EmbeddingBatchRequest,
    EmbeddingBatchResultItem,
    LocalBatchBackend,
    PgLlmBatchBackend,
    PgLlmBatchEmbeddingBackend,
    ProviderEmbeddingBatchBackend,
    RoutingDecision,
    RoutingHints,
    build_embeddings_jsonl_body,
)
from .evidence_batch_routing import (
    LocalEmbeddingBatchBackend,
    RoutingPolicy,
    cheapest_upstream,
    prohibited_heuristic_embedding,
    resolve_embedding_target_evidence_only,
)

# Patch the already-loaded protocol module before downstream modules import its
# decision surfaces. Direct ``contextual_orchestrator.batch_routing`` imports
# also observe these fail-closed replacements because Python initializes the
# package before returning a submodule to callers. The legacy SHA-derived
# implementation remains unreachable and is exposed only as a tombstone that
# raises instead of fabricating a semantic vector.
_batch_routing.RoutingPolicy = RoutingPolicy
_batch_routing.cheapest_upstream = cheapest_upstream
_batch_routing.LocalEmbeddingBatchBackend = LocalEmbeddingBatchBackend
_batch_routing.heuristic_embedding = prohibited_heuristic_embedding

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
    UsageRecordSink,
    UsageTelemetrySink,
    UsageRecord,
    dimension_catalog,
)
from .metering import CanonicalUsageRecordSink
from .cost_router import CostRoutingCoordinator

# The legacy coordinator still contains a price/order ranking helper used by
# historical tests and non-authoritative diagnostics. Production embedding
# target resolution is replaced at class load so both package and submodule
# imports require explicit or uniquely eligible routing evidence.
CostRoutingCoordinator._resolve_embedding_target = resolve_embedding_target_evidence_only

from .cefr_language_observation import (
    CEFR_LANGUAGE_ASSESSMENT_CONTRACT_V1,
    FAST_MLSIRM_SCORING_SCHEMA_VERSION,
    CefrContractAdapter,
    CefrLanguageObservationRequest,
    CefrObservationError,
    CefrRaterAssignment,
    StructuredObservationGateway,
    TaskOrchestratorCefrGateway,
    observe_language_response_criteria,
)
from .evaluation_criterion_binding import (
    CategoryExecutionBinding,
    CriterionExecutionBinding,
    CriterionSetExecutionBinding,
    EvaluationCriterionBindingError,
)
from .rater_observation import (
    GOVERNED_RATER_OBSERVATION_CONTRACT_V1,
    CriterionObservation,
    RaterConfigurationIdentity,
    RaterInvocation,
    RaterObservationError,
)
from .credentials import NotConfigured, get_credential, register_credential
from .kv_config import InMemoryConfigStore, get_config_store
from .orchestrator import ModelAgent, TaskOrchestrator, WorkflowStep, load_agents
from .evidence_model_selection import (
    get_model_group_diagnostic,
    measured_member_order_fail_closed,
    prohibited_static_rank_key,
    ranked_agents_evidence_only,
    requested_agent_evidence_only,
)

# Runtime model selection must not fall through to the historical static
# priority/cosine/id key or the hand-composed transport score. Keep the
# compatibility source available for incremental deletion, but make every
# package/submodule import observe the fail-closed selection boundary now.
TaskOrchestrator._ranked_agents = ranked_agents_evidence_only
TaskOrchestrator._requested_agent = requested_agent_evidence_only
TaskOrchestrator._static_rank_key = prohibited_static_rank_key
TaskOrchestrator._measured_member_order = measured_member_order_fail_closed
# Admin group serialization remains available without pretending its canonical
# identifier order is an inference preference.
TaskOrchestrator.get_model_group = get_model_group_diagnostic

from .release_authorization import evaluate_release_authorization
from .reasoning_effort_profile import (
    EffortProfileError,
    ReasoningEffortProfile,
    apply_request_profile,
    default_role_effort_catalog,
    parse_reasoning_effort_profile,
    snapshot_role_effort_catalog,
)
from .token_counting import (
    NativeCl100kTokenCounter,
    NativeExactTokenCounter,
    TokenCountUnavailable,
    UnavailableTokenCounter,
    build_embedding_token_counter,
    build_token_counter,
)
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
    "UsageRecordSink",
    "UsageTelemetrySink",
    "CanonicalUsageRecordSink",
    "dimension_catalog",
    # config / tokens
    "InMemoryConfigStore",
    "get_config_store",
    "NativeCl100kTokenCounter",
    "NativeExactTokenCounter",
    "TokenCountUnavailable",
    "UnavailableTokenCounter",
    "build_embedding_token_counter",
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
    "BatchDownloadError",
    "LocalBatchBackend",
    "PgLlmBatchBackend",
    # embeddings batch
    "EmbeddingBatchRequest",
    "EmbeddingBatchResultItem",
    "LocalEmbeddingBatchBackend",
    "PgLlmBatchEmbeddingBackend",
    "ProviderEmbeddingBatchBackend",
    "build_embeddings_jsonl_body",
    "cheapest_upstream",
    "CostRoutingCoordinator",
    # immutable evaluation-criterion binding
    "CategoryExecutionBinding",
    "CriterionExecutionBinding",
    "CriterionSetExecutionBinding",
    "EvaluationCriterionBindingError",
    # generic governed-rater observation context
    "GOVERNED_RATER_OBSERVATION_CONTRACT_V1",
    "CriterionObservation",
    "RaterConfigurationIdentity",
    "RaterInvocation",
    "RaterObservationError",
    # compatibility CEFR profile boundary
    "CEFR_LANGUAGE_ASSESSMENT_CONTRACT_V1",
    "FAST_MLSIRM_SCORING_SCHEMA_VERSION",
    "CefrContractAdapter",
    "CefrLanguageObservationRequest",
    "CefrObservationError",
    "CefrRaterAssignment",
    "StructuredObservationGateway",
    "TaskOrchestratorCefrGateway",
    "observe_language_response_criteria",
    "evaluate_release_authorization",
]
