"""OpenAPI contract for governance, workflow, evaluation, and locale APIs."""

from __future__ import annotations

OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "Contextual Orchestrator API",
        "version": "0.1.0",
        "description": "Resource-oriented API for agent pools, workflow runs, policies, and locale bundles.",
    },
    "components": {
        "securitySchemes": {
            "admin_bearer_auth": {"type": "http", "scheme": "bearer"},
            "inference_bearer_auth": {"type": "http", "scheme": "bearer"},
        },
        "schemas": {
            "ReleaseAuthorization": {
                "type": "object",
                "required": ["status", "authorized", "blockers", "evidence_identities"],
                "properties": {
                    "status": {"type": "string", "enum": ["release_authorized", "release_authorization_blocked"]},
                    "authorized": {"type": "boolean"},
                    "blockers": {"type": "array", "items": {"type": "string"}},
                    "evidence_identities": {"type": "object"},
                    "required_checks": {"type": "object"},
                    "review": {"type": "object"},
                    "findings": {"type": "object"},
                },
            },
            "CommercialReleaseCandidate": {
                "type": "object",
                "required": ["release_status", "product_evidence_status", "release_authorization"],
                "properties": {
                    "release_status": {"type": "string"},
                    "product_evidence_status": {"type": "string"},
                    "release_authorization": {"$ref": "#/components/schemas/ReleaseAuthorization"},
                    "release_summary": {"type": "object"},
                },
            },
            "CommercialProcurementReadiness": {
                "type": "object",
                "required": ["procurement_status", "release_authorization"],
                "properties": {
                    "procurement_status": {"type": "string"},
                    "release_authorization": {"$ref": "#/components/schemas/ReleaseAuthorization"},
                    "procurement_summary": {"type": "object"},
                },
            },
            "CommercialContractReadiness": {
                "type": "object",
                "required": ["contract_status", "release_authorization"],
                "properties": {
                    "contract_status": {"type": "string"},
                    "release_authorization": {"$ref": "#/components/schemas/ReleaseAuthorization"},
                    "contract_summary": {"type": "object"},
                },
            },
            "CommercialGapRegister": {
                "type": "object",
                "required": [
                    "gap_register_status",
                    "measurement_status",
                    "gap_summary",
                    "gap_items",
                    "release_authorization",
                    "concrete_blockers",
                ],
                "properties": {
                    "gap_register_status": {
                        "type": "string",
                        "enum": [
                            "commercial_gap_register_clear",
                            "commercial_gap_register_open",
                            "commercial_gap_register_blocked",
                        ],
                    },
                    "target_contract_value_krw": {"type": "integer"},
                    "target_contract_value_display": {"type": "string"},
                    "measurement_status": {"type": "string"},
                    "source_note": {"type": "string"},
                    "gap_summary": {"type": "object"},
                    "gap_items": {"type": "array", "items": {"type": "object"}},
                    "concrete_blockers": {"type": "array", "items": {"type": "string"}},
                    "release_authorization": {"$ref": "#/components/schemas/ReleaseAuthorization"},
                    "gap_status_rules": {"type": "array", "items": {"type": "object"}},
                    "review_process_policy": {"type": "object"},
                    "related_runtime_reports": {"type": "object"},
                    "library_split_decision": {"type": "object"},
                    "plugin_traceability": {"type": "object"},
                    "gap_register_links": {"type": "object"},
                },
            },
        },
    },
    "paths": {
        "/openapi.json": {
            "get": {
                "operationId": "get_openapi_document",
                "summary": "Get this OpenAPI contract",
                "responses": {"200": {"description": "OpenAPI document"}},
            }
        },
        "/healthz": {
            "get": {
                "operationId": "get_health_status",
                "summary": "Get unauthenticated service liveness",
                "responses": {"200": {"description": "Service health"}},
            }
        },
        "/v1/models": {
            "get": {
                "operationId": "list_models",
                "summary": "List models available for inference",
                "security": [{"inference_bearer_auth": []}],
                "responses": {"200": {"description": "Model collection"}},
            }
        },
        "/v1/models/{model_id}": {
            "get": {
                "operationId": "get_model",
                "summary": "Get one inference model",
                "security": [{"inference_bearer_auth": []}],
                "parameters": [
                    {"name": "model_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {"description": "Model"},
                    "404": {"description": "Model not found"},
                },
            }
        },
        "/v1/chat/completions": {
            "post": {
                "operationId": "create_chat_completion",
                "summary": "Create a chat completion",
                "security": [{"inference_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["model", "messages"],
                                "properties": {
                                    "model": {"type": "string"},
                                    "messages": {"type": "array", "items": {"type": "object"}},
                                    "stream": {"type": "boolean"},
                                    "response_format": {"type": "object"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Chat completion or SSE response"},
                    "400": {"description": "Invalid request"},
                },
            }
        },
        "/v1/completions": {
            "post": {
                "operationId": "create_completion",
                "summary": "Create a legacy text completion",
                "security": [{"inference_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["model", "prompt"],
                                "properties": {
                                    "model": {"type": "string"},
                                    "prompt": {"oneOf": [{"type": "string"}, {"type": "array"}]},
                                    "stream": {"type": "boolean"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Text completion"},
                    "400": {"description": "Invalid request"},
                },
            }
        },
        "/v1/embeddings": {
            "post": {
                "operationId": "create_embedding",
                "summary": "Create embeddings for semantic input",
                "security": [{"inference_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["model", "input"],
                                "properties": {
                                    "model": {"type": "string"},
                                    "input": {
                                        "oneOf": [
                                            {"type": "string"},
                                            {"type": "array", "items": {"type": "string"}},
                                        ]
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Embedding response"},
                    "400": {"description": "Invalid request"},
                },
            }
        },
        "/v1/responses": {
            "post": {
                "operationId": "create_response",
                "summary": "Create a Responses API completion",
                "security": [{"inference_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["model", "input"],
                                "properties": {
                                    "model": {"type": "string"},
                                    "input": {"oneOf": [{"type": "string"}, {"type": "array"}]},
                                    "stream": {"type": "boolean"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Responses API result"},
                    "400": {"description": "Invalid request"},
                },
            }
        },
        "/api/v1/agent_pools": {
            "get": {
                "operationId": "list_agent_pools",
                "summary": "List configured model agents",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Agent pool collection"}},
            }
        },
        "/api/v1/agent_pools/{agent_pool_id}/worker_agents/{worker_agent_id}": {
            "patch": {
                "operationId": "patch_worker_agent",
                "summary": "Patch one worker agent in a pool",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [
                    {
                        "name": "agent_pool_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                    {
                        "name": "worker_agent_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "priority": {"type": "integer"},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                    "provider_exclusions": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                    },
                },
                "responses": {"200": {"description": "Worker agent updated"}},
            }
        },
        "/api/v1/orchestration_policies/default_policy": {
            "get": {
                "operationId": "get_default_policy",
                "summary": "Get the active orchestration policy",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Active policy"}},
            }
        },
        "/api/v1/provider_readiness/latest": {
            "get": {
                "operationId": "get_latest_provider_readiness",
                "summary": "Read or explicitly refresh bounded provider chat readiness",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [{
                    "name": "refresh",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "boolean", "default": False},
                }],
                "responses": {"200": {"description": "Provider readiness report"}},
            }
        },
        "/api/v1/analytics_snapshots/latest": {
            "get": {
                "operationId": "get_latest_analytics_snapshot",
                "summary": "Get source-backed local KPI and guardrail metrics",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Analytics snapshot"}},
            }
        },
        "/api/v1/sales_readiness/latest": {
            "get": {
                "operationId": "get_latest_sales_readiness",
                "summary": "Get local sales-readiness criteria and evidence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Sales-readiness report"}},
            }
        },
        "/api/v1/commercial_readiness/latest": {
            "get": {
                "operationId": "get_latest_commercial_readiness",
                "summary": "Get high-value commercial due-diligence criteria and evidence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial-readiness report"}},
            }
        },
        "/api/v1/buyer_evidence_manifests/latest": {
            "get": {
                "operationId": "get_latest_buyer_evidence_manifest",
                "summary": "Get buyer evidence manifest for commercial due diligence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Buyer evidence manifest"}},
            }
        },
        "/api/v1/buyer_handoff_bundles/latest": {
            "get": {
                "operationId": "get_latest_buyer_handoff_bundle",
                "summary": "Get buyer handoff bundle for commercial due diligence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Buyer handoff bundle"}},
            }
        },
        "/api/v1/saleability_decisions/latest": {
            "get": {
                "operationId": "get_latest_saleability_decision",
                "summary": "Get KRW 2B saleability decision gate",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Saleability decision"}},
            }
        },
        "/api/v1/commercial_evidence_exports/latest": {
            "get": {
                "operationId": "get_latest_commercial_evidence_export",
                "summary": "Get portable commercial evidence export for buyer due diligence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial evidence export"}},
            }
        },
        "/api/v1/commercial_acceptance_checks/latest": {
            "get": {
                "operationId": "get_latest_commercial_acceptance_check",
                "summary": "Get commercial acceptance check for buyer due diligence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial acceptance check"}},
            }
        },
        "/api/v1/commercial_release_candidates/latest": {
            "get": {
                "operationId": "get_latest_commercial_release_candidate",
                "summary": "Get commercial release candidate package for buyer due diligence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {
                    "200": {
                        "description": "Commercial release candidate with separate fail-closed release authority",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CommercialReleaseCandidate"}}},
                    }
                },
            }
        },
        "/api/v1/commercial_gap_registers/latest": {
            "get": {
                "operationId": "get_latest_commercial_gap_register",
                "summary": "Get commercial gap register for buyer due diligence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {
                    "200": {
                        "description": "Commercial gap register with release authority",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CommercialGapRegister"}}},
                    }
                },
            }
        },
        "/api/v1/commercial_procurement_readiness/latest": {
            "get": {
                "operationId": "get_latest_commercial_procurement_readiness",
                "summary": "Get commercial procurement readiness for buyer due diligence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial procurement readiness with release authority", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CommercialProcurementReadiness"}}}}},
            }
        },
        "/api/v1/commercial_contract_readiness/latest": {
            "get": {
                "operationId": "get_latest_commercial_contract_readiness",
                "summary": "Get commercial contract readiness for buyer due diligence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial contract readiness with release authority", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CommercialContractReadiness"}}}}},
            }
        },
        "/api/v1/commercial_onboarding_readiness/latest": {
            "get": {
                "operationId": "get_latest_commercial_onboarding_readiness",
                "summary": "Get commercial onboarding readiness for buyer close",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial onboarding readiness"}},
            }
        },
        "/api/v1/commercial_operations_readiness/latest": {
            "get": {
                "operationId": "get_latest_commercial_operations_readiness",
                "summary": "Get commercial operations readiness for buyer handoff",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial operations readiness"}},
            }
        },
        "/api/v1/commercial_security_attestations/latest": {
            "get": {
                "operationId": "get_latest_commercial_security_attestation",
                "summary": "Get commercial security attestation for buyer security review",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial security attestation"}},
            }
        },
        "/api/v1/commercial_value_readiness/latest": {
            "get": {
                "operationId": "get_latest_commercial_value_readiness",
                "summary": "Get commercial value readiness for buyer economic review",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial value readiness"}},
            }
        },
        "/api/v1/commercial_close_readiness/latest": {
            "get": {
                "operationId": "get_latest_commercial_close_readiness",
                "summary": "Get commercial close readiness for buyer signature and go-live review",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial close readiness"}},
            }
        },
        "/api/v1/commercial_go_to_market_readiness/latest": {
            "get": {
                "operationId": "get_latest_commercial_go_to_market_readiness",
                "summary": "Get commercial go-to-market readiness for buyer and stakeholder review",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial go-to-market readiness"}},
            }
        },
        "/api/v1/commercial_launch_readiness/latest": {
            "get": {
                "operationId": "get_latest_commercial_launch_readiness",
                "summary": "Get commercial launch readiness for buyer trial and go-live execution",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial launch readiness"}},
            }
        },
        "/api/v1/commercial_completion_scorecards/latest": {
            "get": {
                "operationId": "get_latest_commercial_completion_scorecard",
                "summary": "Get KRW 2B commercial completion scorecard",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial completion scorecard"}},
            }
        },
        "/api/v1/commercial_buyer_acceptance_workflows/latest": {
            "get": {
                "operationId": "get_latest_commercial_buyer_acceptance_workflow",
                "summary": "Get KRW 2B commercial buyer acceptance workflow",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial buyer acceptance workflow"}},
            }
        },
        "/api/v1/commercial_demo_scenarios/latest": {
            "get": {
                "operationId": "get_latest_commercial_demo_scenarios",
                "summary": "Get KRW 2B commercial demo scenarios",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial demo scenarios"}},
            }
        },
        "/api/v1/commercial_proposal_packets/latest": {
            "get": {
                "operationId": "get_latest_commercial_proposal_packet",
                "summary": "Get KRW 2B commercial proposal packet",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial proposal packet"}},
            }
        },
        "/api/v1/commercial_purchase_approval_packets/latest": {
            "get": {
                "operationId": "get_latest_commercial_purchase_approval_packet",
                "summary": "Get KRW 2B commercial purchase approval packet",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial purchase approval packet"}},
            }
        },
        "/api/v1/commercial_due_diligence_rooms/latest": {
            "get": {
                "operationId": "get_latest_commercial_due_diligence_room",
                "summary": "Get KRW 2B commercial due diligence room",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial due diligence room"}},
            }
        },
        "/api/v1/commercial_investment_committee_memos/latest": {
            "get": {
                "operationId": "get_latest_commercial_investment_committee_memo",
                "summary": "Get KRW 2B commercial investment committee memo",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial investment committee memo"}},
            }
        },
        "/api/v1/workflow_runs": {
            "get": {
                "operationId": "list_workflow_runs",
                "summary": "List recent workflow runs",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Workflow runs"}},
            },
            "post": {
                "operationId": "create_workflow_run",
                "summary": "Run routing or conducted orchestration",
                "security": [{"inference_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["prompt_text"],
                                "properties": {
                                    "prompt_text": {"type": "string"},
                                    "run_mode": {"type": "string", "enum": ["auto", "route", "conduct"]},
                                },
                            },
                        }
                    },
                },
                "responses": {"201": {"description": "Workflow run created"}},
            },
        },
        "/api/v1/workflow_runs/{workflow_run_id}": {
            "get": {
                "operationId": "get_workflow_run",
                "summary": "Get a workflow run and its traces",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [
                    {
                        "name": "workflow_run_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "Workflow run"}},
            }
        },
        "/api/v1/cost_reports/rollup": {
            "get": {
                "operationId": "get_cost_report",
                "summary": "Roll up LLM cost + tokens by an attribution dimension over a time window",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [
                    {
                        "name": "dimension",
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "string",
                            "enum": ["account", "service", "upstream_api", "provider", "model_name", "team", "group", "company"],
                        },
                    },
                    {"name": "start", "in": "query", "required": False, "schema": {"type": "integer"}},
                    {"name": "end", "in": "query", "required": False, "schema": {"type": "integer"}},
                ],
                "responses": {"200": {"description": "Cost rollup report"}},
            }
        },
        "/api/v1/cost_attribution_dimensions": {
            "get": {
                "operationId": "list_cost_attribution_dimensions",
                "summary": "List the attribution dimensions cost can be rolled up by",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Attribution dimension catalog"}},
            }
        },
        "/api/v1/llm_usage_records": {
            "get": {
                "operationId": "list_llm_usage_records",
                "summary": "List recorded per-request usage + cost ledger entries",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [
                    {"name": "start", "in": "query", "required": False, "schema": {"type": "integer"}},
                    {"name": "end", "in": "query", "required": False, "schema": {"type": "integer"}},
                    {"name": "page_number", "in": "query", "required": False, "schema": {"type": "integer"}},
                    {"name": "page_size", "in": "query", "required": False, "schema": {"type": "integer"}},
                ],
                "responses": {"200": {"description": "Usage record collection"}},
            }
        },
        "/api/v1/batch_routing_jobs": {
            "post": {
                "operationId": "create_batch_routing_job",
                "summary": "Submit a batch of latency-tolerant requests to the batch backend (pg-llm-batch)",
                "security": [{"inference_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["requests"],
                                "properties": {
                                    "requests": {"type": "array", "items": {"type": "object"}},
                                    "attribution": {"type": "object"},
                                    "model": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "responses": {"201": {"description": "Batch routing job created"}},
            }
        },
        "/api/v1/batch_routing_jobs/{batch_routing_job_id}": {
            "get": {
                "operationId": "get_batch_routing_job",
                "summary": "Poll a submitted batch routing job",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [
                    {"name": "batch_routing_job_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "Batch routing job status"}},
            }
        },
        "/api/v1/batch_routing_jobs/{batch_routing_job_id}/results": {
            "post": {
                "operationId": "create_batch_routing_job_results",
                "summary": "Retrieve batch results and record their usage + cost",
                "security": [{"inference_bearer_auth": []}],
                "parameters": [
                    {"name": "batch_routing_job_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "Batch results with recorded usage"}},
            }
        },
        "/v1/batch/embeddings": {
            "post": {
                "operationId": "create_batch_embeddings_job",
                "summary": "Submit a bulk, latency-tolerant embeddings batch (token-split, routed via pg-llm-batch, cost-recorded)",
                "security": [{"inference_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["model"],
                                "properties": {
                                    "model": {"type": "string"},
                                    "input": {
                                        "oneOf": [
                                            {"type": "string"},
                                            {"type": "array", "items": {"type": "string"}},
                                        ]
                                    },
                                    "inputs": {"type": "array", "items": {"type": "string"}},
                                    "endpoint": {"type": "string", "description": "batch endpoint alias"},
                                    "metadata": {
                                        "type": "object",
                                        "description": "observability + attribution dims (service, team, group, company, provider)",
                                    },
                                    "attribution": {"type": "object"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": (
                            "Batch completed synchronously: "
                            "{batch_id, status, embeddings:[{index, embedding}], "
                            "cost_micro_usd, token_counts, total_tokens, part_count, "
                            "input_part_counts, map_reduce}"
                        )
                    },
                    "202": {"description": "Batch accepted; poll GET /v1/batch/embeddings/{batch_id}"},
                },
            }
        },
        "/v1/batch/embeddings/{batch_id}": {
            "get": {
                "operationId": "get_batch_embeddings_job",
                "summary": "Poll an embeddings batch; returns reduced vectors + recorded cost once completed",
                "security": [{"inference_bearer_auth": []}],
                "parameters": [
                    {"name": "batch_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {
                        "description": (
                            "{batch_id, status, embeddings:[[...]], cost_micro_usd, "
                            "token_counts, input_part_counts, map_reduce}"
                        )
                    },
                    "404": {"description": "Embeddings batch not found"},
                },
            }
        },
        "/api/v1/access_reports/{workflow_run_id}": {
            "get": {
                "operationId": "get_access_report",
                "summary": "Get access report for a workflow run",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [
                    {
                        "name": "workflow_run_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "Access report"}},
            }
        },
        "/api/v1/evaluation_runs": {
            "post": {
                "operationId": "create_evaluation_run",
                "summary": "Replay prompts for evaluation",
                "security": [{"inference_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["prompts"],
                                "properties": {
                                    "prompts": {"type": "array", "items": {"type": "string"}},
                                    "run_mode": {"type": "string", "enum": ["auto", "route", "conduct"]},
                                },
                            },
                        },
                    },
                },
                "responses": {"201": {"description": "Evaluation run created"}},
            }
        },
        "/api/v1/evaluation_runs/{evaluation_run_id}": {
            "get": {
                "operationId": "get_evaluation_run",
                "summary": "Read evaluation run outputs",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [
                    {
                        "name": "evaluation_run_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
                "responses": {"200": {"description": "Evaluation run"}},
            }
        },
        "/api/v1/locale_bundles/{locale_code}": {
            "get": {
                "operationId": "get_locale_bundle",
                "summary": "Get admin UI translations",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [
                    {
                        "name": "locale_code",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string", "enum": ["en", "ko"]},
                    },
                ],
                "responses": {"200": {"description": "Locale bundle"}, "404": {"description": "Locale not found"}},
            }
        },
    },
}
