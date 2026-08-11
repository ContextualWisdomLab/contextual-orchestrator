# Runtime and deployment UML

**Document state:** `accepted_architecture`

These diagrams are architecture-as-code. Labels use protected-main class and
resource names. Active-pull-request behavior is called out rather than drawn as
shipped runtime behavior.

## Component topology

```mermaid
flowchart TB
    consumer["API consumer"] --> server["server.py delivery"]
    operator["Operator"] --> admin["admin.py and evidence API"]
    server --> coordinator["CostRoutingCoordinator"]
    coordinator --> orchestrator["TaskOrchestrator"]
    coordinator --> ledger["CostLedger"]
    coordinator --> batch["Local or pg-llm-batch backend"]
    server -. passthrough / route stream .-> orchestrator
    admin --> orchestrator
    orchestrator --> provider["ModelClient"]
    orchestrator --> state["Optional state adapters"]
    provider --> model["OpenAI-compatible provider"]
```

The server and admin are delivery adapters. They cannot grant model-provider
authority, change evidence status, or take ownership of host tenancy.

## Route sequence

```mermaid
sequenceDiagram
    actor Caller
    participant Server
    participant Coordinator as CostRoutingCoordinator
    participant Orchestrator as TaskOrchestrator
    participant Provider as Model provider

    Caller->>Server: POST chat completion
    Server->>Server: Authenticate and validate bounds
    Server->>Coordinator: complete(messages, mode, hints)
    Coordinator->>Coordinator: Choose sync and estimate tokens
    Coordinator->>Orchestrator: run(messages, mode)
    Orchestrator->>Orchestrator: Budget, agent, and KV credential
    Orchestrator->>Provider: Bounded compatible request
    alt transient provider failure
        Provider-->>Orchestrator: timeout, 429, or 5xx
        Orchestrator->>Orchestrator: Retry, fail over, update circuit
    else permanent failure
        Provider-->>Orchestrator: stable permanent error
    end
    Provider-->>Orchestrator: answer and optional usage
    Orchestrator-->>Coordinator: route result and workflow evidence
    Coordinator->>Coordinator: Append qualified usage record
    Coordinator-->>Server: compatible result and cost metadata
    Server-->>Caller: compatible response or validated SSE
```

Mock agents return before credential and network operations. The stronger
DNS-pinned and strict response parser path is `active_pr` in #96. Raw
passthrough and route streaming do not follow this coordinator sequence on
protected main; they bypass ledger recording, and streaming also bypasses
durable workflow state.

## Conduct sequence and access lists

```mermaid
sequenceDiagram
    participant Orchestrator as TaskOrchestrator
    participant Thinker as Thinker agent
    participant Worker as Worker agent
    participant Verifier as Verifier agent
    participant Synthesizer as Synthesizer agent

    Orchestrator->>Orchestrator: Admitted complex request
    Orchestrator->>Orchestrator: Template or validated generated plan
    Orchestrator->>Thinker: Step 0 subtask
    Thinker-->>Orchestrator: Step 0 output
    Orchestrator->>Worker: Step 1 plus access [0]
    Worker-->>Orchestrator: Step 1 output
    Orchestrator->>Verifier: Step 2 plus access [0, 1]
    Verifier-->>Orchestrator: Verdict and evidence
    Orchestrator->>Synthesizer: Step 3 plus allowed outputs
    Synthesizer-->>Orchestrator: Final answer
    Orchestrator->>Orchestrator: Store answer and authorized trace projection
```

Role-specific reasoning effort and recursive depth controls are
`active_pr`/`planned`; they are not shown as protected-main authority.

## Credential bootstrap and use

```mermaid
sequenceDiagram
    actor Deployer
    participant CLI as register-credential CLI
    participant KV as Credential backend
    participant Runtime
    participant Provider

    Deployer->>CLI: Secret over stdin
    CLI->>KV: register_credential(name, value)
    KV-->>CLI: Stored or explicit failure
    Runtime->>KV: get_credential(name)
    KV-->>Runtime: Current value or missing
    alt credential present
        Runtime->>Provider: Authorization at request boundary
        Provider-->>Runtime: Response
    else credential missing
        Runtime-->>Runtime: Fail closed as not configured
    end
```

Environment variables may select/connect/unlock the KV at bootstrap. They are
not the request-time provider credential source. The cross-process sequence
requires the durable Postgres credential backend. With the default in-memory
backend, the CLI process exits with its registry; registration must occur in the
same long-lived process as provider use.

## Provider failover and circuit breaker

```mermaid
sequenceDiagram
    participant Orchestrator as TaskOrchestrator
    participant Client as ModelClient
    participant Primary as Primary provider
    participant Circuit as Circuit state
    participant Fallback as Eligible fallback
    Orchestrator->>Orchestrator: Validate caller request and bounds
    alt caller validation error
        Orchestrator-->>Orchestrator: Terminate without provider dispatch
    else admitted request
        Orchestrator->>Circuit: Check primary availability
        Circuit-->>Orchestrator: Closed or half-open
        Orchestrator->>Client: Invoke primary
        Client->>Primary: Bounded request
        alt transient provider failure
            Primary-->>Client: timeout, 429, or 5xx
            Client-->>Orchestrator: Retry budget exhausted
            Orchestrator->>Circuit: Record failure/open threshold
            Orchestrator->>Fallback: Invoke eligible candidate
            Fallback-->>Orchestrator: Valid response or classified failure
        else permanent provider or configuration error
            Primary-->>Client: Stable provider 4xx or configuration failure
            Client-->>Orchestrator: Classified failure without client retry
            Orchestrator->>Fallback: Invoke eligible candidate without client retry
        else success
            Primary-->>Client: Valid response
            Client-->>Orchestrator: Answer and optional usage
            Orchestrator->>Circuit: Reset failure state
        end
    end
```

DNS pinning, ambient-proxy and redirect rejection, and strict response parsing
are `active_pr` in #96. This diagram therefore describes the accepted control
flow while `ARCHITECTURE.md` and `TRACEABILITY.md` retain the shipped boundary.

## Sync-versus-batch sequence

```mermaid
sequenceDiagram
    actor Caller
    participant Server
    participant Router as CostRoutingCoordinator
    participant Orchestrator as TaskOrchestrator
    participant Backend as BatchBackend

    Caller->>Server: Request plus routing hints
    Server->>Router: complete(...)
    Router->>Router: Policy and token estimate
    alt interactive or sync decision
        Router->>Orchestrator: run route or conduct
        Orchestrator-->>Router: Answer and workflow identity
        Router->>Router: Record qualified ledger usage
        Router-->>Server: Completion
        Server-->>Caller: Completion
    else latency-tolerant batch decision
        Router->>Backend: Submit bounded batch
        Backend-->>Router: Batch job identity
        Router-->>Server: Submitted state
        Server-->>Caller: Submitted state
        Caller->>Server: Poll or retrieve
        Server->>Router: poll_batch(...) or retrieve_batch(...)
        Router->>Backend: poll(...) or retrieve(...)
        Backend-->>Router: State or results
        opt Retrieved completion results
            Router->>Router: Record qualified result usage
        end
        Router-->>Server: State or qualified results
        Server-->>Caller: State or qualified results
    end
```

The local backend preserves standalone operation. External job persistence and
execution are owned by the injected `pg-llm-batch` contract, but coordinator
handles and result mappings are process-local. Restart loses lookup authority;
chat result replay is not idempotent on protected main.

## Request and provider state machine

```mermaid
stateDiagram-v2
    [*] --> Received
    Received --> Rejected: auth or validation failure
    Received --> Admitted: bounds and budget pass
    Admitted --> Routed: route mode
    Admitted --> Planned: conduct mode
    Planned --> Executing: valid bounded workflow
    Routed --> Executing
    Executing --> Retrying: transient failure
    Retrying --> Executing: retry or failover available
    Retrying --> Failed: budget or candidates exhausted
    Executing --> Failed: permanent failure
    Executing --> Completed: valid answer
    Completed --> Persisted: optional store succeeds
    Completed --> DegradedEvidence: optional export fails
    Persisted --> [*]
    DegradedEvidence --> [*]
    Rejected --> [*]
    Failed --> [*]
```

`DegradedEvidence` is never converted into complete durable evidence. A model
answer and its export health remain separate facts.

## Evidence and merge authority

```mermaid
stateDiagram-v2
    [*] --> CandidateHead
    CandidateHead --> DeterministicEvidence: tests and security execute
    DeterministicEvidence --> ReviewEvidence: exact-head reviews execute
    ReviewEvidence --> Approved: eligible independent approval
    Approved --> Mergeable: all protected gates agree
    Mergeable --> ProtectedMain: protected merge
    CandidateHead --> Blocked: failed, absent, stale, or synthetic evidence
    DeterministicEvidence --> Blocked: valid finding or missing gate
    ReviewEvidence --> Blocked: unresolved finding
    Blocked --> CandidateHead: deliberate new head
```

A status, check, model review, and human approval are distinct. No transition
may manufacture another authority.

## Deployment topology

```mermaid
flowchart TB
    subgraph Host["Host-owned boundary"]
        ingress["Ingress and identity"]
        tenancy["Tenant and purpose policy"]
        business["Business records"]
    end
    subgraph Orchestrator["Contextual Orchestrator"]
        api["Compatible API"]
        policy["Orchestration policy"]
        provider_adapter["Provider adapter"]
        evidence["Trace, cost, and audit evidence"]
    end
    subgraph Dependencies["Optional dependencies"]
        kv["Credential registry"]
        provider["OpenAI-compatible provider"]
        batch["pg-llm-batch"]
        viewer["Clearfolio"]
    end
    ingress --> api
    tenancy --> api
    api --> policy
    policy --> evidence
    policy --> provider_adapter
    provider_adapter --> kv
    provider_adapter --> provider
    policy --> batch
    evidence --> viewer
    business -. purpose-bound request .-> ingress
```

The dotted edge is a request projection, not a transfer of business-record
ownership.

## Degraded-mode topology

```mermaid
flowchart LR
    request["Admitted request"] --> provider["Provider execution"]
    provider --> answer["Qualified answer"]
    answer --> optional["Optional state, ledger, or evidence export"]
    optional -->|success| durable["Durable qualified evidence"]
    optional -->|failure| degraded["Degraded evidence state"]
    degraded --> operator["Operator alert and incident runbook"]
    degraded -. never promoted .-> blocked["Release evidence incomplete"]
```

Optional persistence failure may leave a model answer usable only when the
contract permits it, but it cannot be reported as complete durable evidence.
