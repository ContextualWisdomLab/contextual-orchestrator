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
        }
    },
    "paths": {
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
