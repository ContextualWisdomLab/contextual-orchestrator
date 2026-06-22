from __future__ import annotations


OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "Contextual Orchestrator API",
        "version": "0.1.0",
        "description": "Resource-oriented API for agent pools, workflow runs, policies, and locale bundles.",
    },
    "paths": {
        "/api/v1/agent_pools": {
            "get": {
                "operationId": "list_agent_pools",
                "summary": "List configured model agents",
                "responses": {"200": {"description": "Agent pool collection"}},
            }
        },
        "/api/v1/orchestration_policies/default_policy": {
            "get": {
                "operationId": "get_default_policy",
                "summary": "Get the active orchestration policy",
                "responses": {"200": {"description": "Active policy"}},
            }
        },
        "/api/v1/workflow_runs": {
            "post": {
                "operationId": "create_workflow_run",
                "summary": "Run routing or conducted orchestration",
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
                            }
                        }
                    },
                },
                "responses": {"201": {"description": "Workflow run created"}},
            }
        },
        "/api/v1/locale_bundles/{locale_code}": {
            "get": {
                "operationId": "get_locale_bundle",
                "summary": "Get admin UI translations",
                "parameters": [
                    {
                        "name": "locale_code",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string", "enum": ["en", "ko"]},
                    }
                ],
                "responses": {"200": {"description": "Locale bundle"}, "404": {"description": "Locale not found"}},
            }
        },
    },
}

