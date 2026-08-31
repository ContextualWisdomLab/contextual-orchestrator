"""OpenAPI contract for governance, workflow, evaluation, and locale APIs."""

from __future__ import annotations

_AGENT_POOL_INTEGER_MAX = 9_223_372_036_854_775_807

OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "Contextual Orchestrator API",
        "version": "0.2.0",
        "description": "Resource-oriented API for agent pools, workflow runs, policies, and locale bundles.",
    },
    "components": {
        "securitySchemes": {
            "admin_bearer_auth": {"type": "http", "scheme": "bearer"},
            "inference_bearer_auth": {"type": "http", "scheme": "bearer"},
            "trace_bearer_auth": {
                "type": "http",
                "scheme": "bearer",
                "description": "Bearer credential verified for the trace purpose",
            },
        },
        "schemas": {
            "ModelGroupWrite": {
                "type": "object",
                "required": ["group_name", "member_agent_ids"],
                "properties": {
                    "group_name": {"type": "string"},
                    "member_agent_ids": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string"},
                    },
                },
            },
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
            "CommercialGapRegister": {
                "type": "object",
                "required": ["gap_register_status", "gap_summary", "gap_items", "release_authorization", "concrete_blockers"],
                "properties": {
                    "gap_register_status": {"type": "string"},
                    "gap_summary": {"type": "object"},
                    "gap_items": {"type": "array", "items": {"type": "object"}},
                    "concrete_blockers": {"type": "array", "items": {"type": "string"}},
                    "release_authorization": {"$ref": "#/components/schemas/ReleaseAuthorization"},
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
            }
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
                "summary": "Get minimal unauthenticated service liveness",
                "responses": {"200": {"description": "Service health"}},
            }
        },
        "/readyz": {
            "get": {
                "operationId": "get_readiness_status",
                "summary": "Get authenticated dependency readiness",
                "security": [{"admin_bearer_auth": []}],
                "responses": {
                    "200": {"description": "Service is ready or has degraded optional dependencies"},
                    "401": {"description": "Admin authentication required"},
                    "503": {"description": "Required service dependency is not ready"},
                },
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
                                "required": ["messages"],
                                "properties": {
                                    "model": {"type": "string"},
                                    "messages": {"type": "array", "items": {"type": "object"}},
                                    "stream": {"type": "boolean"},
                                    "zdr_only": {
                                        "type": "boolean",
                                        "description": "When true, select only model-group members with ZDR evidence.",
                                    },
                                    "response_format": {"type": "object"},
                                    "include_orchestration_trace": {
                                        "type": "boolean",
                                        "description": "Requires the same caller to have the trace purpose",
                                    },
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
                                "required": ["prompt"],
                                "properties": {
                                    "model": {"type": "string"},
                                    "prompt": {"oneOf": [{"type": "string"}, {"type": "array"}]},
                                    "stream": {"type": "boolean"},
                                    "zdr_only": {
                                        "type": "boolean",
                                        "description": "When true, select only model-group members with ZDR evidence.",
                                    },
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
                "summary": "Create embeddings with optional orchestrator-owned model selection",
                "security": [{"inference_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["input"],
                                "properties": {
                                    "model": {
                                        "type": "string",
                                        "description": "Optional enabled embedding-capable pool model; omitted selects one.",
                                    },
                                    "input": {
                                        "oneOf": [
                                            {"type": "string"},
                                            {"type": "array", "items": {"type": "string"}},
                                        ]
                                    },
                                    "zdr_only": {
                                        "type": "boolean",
                                        "description": "When true, select only embedding-capable model-group members with ZDR evidence.",
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Embedding response"},
                    "400": {"description": "Invalid request"},
                    "503": {"description": "No enabled embedding-capable agent is available"},
                },
            }
        },
        **{
            path: {
                "post": {
                    "operationId": operation_id,
                    "summary": summary,
                    "security": [{"inference_bearer_auth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": schema}},
                    },
                    "responses": {
                        "200": {
                            "description": "Capability response",
                            "content": (
                                {"audio/mpeg": {"schema": {"type": "string", "format": "binary"}}}
                                if path == "/v1/audio/speech"
                                else {"application/json": {"schema": {"type": "object"}}}
                            ),
                        },
                        "400": {"description": "Invalid request"},
                        "503": {"description": "No capable model group member is available"},
                    },
                }
            }
            for path, operation_id, summary, schema in (
                ("/v1/images/generations", "create_image", "Generate an image", {"type": "object", "required": ["prompt"], "properties": {"model": {"type": "string"}, "prompt": {"type": "string"}, "zdr_only": {"type": "boolean", "description": "When true, select only capable model-group members with ZDR evidence."}}}),
                ("/v1/videos", "create_video", "Submit video generation", {"type": "object", "required": ["prompt"], "properties": {"model": {"type": "string"}, "prompt": {"type": "string"}, "zdr_only": {"type": "boolean", "description": "When true, select only capable model-group members with ZDR evidence."}}}),
                ("/v1/audio/speech", "create_speech", "Synthesize speech", {"type": "object", "required": ["input", "voice"], "properties": {"model": {"type": "string"}, "input": {"type": "string"}, "voice": {"type": "string"}, "zdr_only": {"type": "boolean", "description": "When true, select only capable model-group members with ZDR evidence."}}}),
                ("/v1/audio/transcriptions", "create_transcription", "Transcribe audio", {"type": "object", "required": ["input_audio"], "properties": {"model": {"type": "string"}, "input_audio": {"type": "object", "required": ["data", "format"]}, "zdr_only": {"type": "boolean", "description": "When true, select only capable model-group members with ZDR evidence."}}}),
                ("/v1/rerank", "create_rerank", "Rerank documents", {"type": "object", "required": ["query", "documents"], "properties": {"model": {"type": "string"}, "query": {"type": "string"}, "documents": {"type": "array", "minItems": 1}, "zdr_only": {"type": "boolean", "description": "When true, select only capable model-group members with ZDR evidence."}}}),
                ("/v1/audio/generations", "create_audio", "Generate audio", {"type": "object", "required": ["messages"], "properties": {"model": {"type": "string"}, "messages": {"type": "array", "minItems": 1}, "zdr_only": {"type": "boolean", "description": "When true, select only capable model-group members with ZDR evidence."}}}),
            )
        },
        "/v1/videos/{video_job_id}": {
            "get": {
                "operationId": "get_video",
                "summary": "Check video generation status",
                "security": [{"inference_bearer_auth": []}],
                "parameters": [{
                    "name": "video_job_id", "in": "path", "required": True,
                    "schema": {"type": "string"},
                }],
                "responses": {
                    "200": {"description": "Video job status"},
                    "404": {"description": "Video job not found"},
                    "503": {"description": "Owning provider is unavailable"},
                },
            }
        },
        "/v1/videos/{video_job_id}/content": {
            "get": {
                "operationId": "download_video",
                "summary": "Download a completed video",
                "security": [{"inference_bearer_auth": []}],
                "parameters": [{
                    "name": "video_job_id", "in": "path", "required": True,
                    "schema": {"type": "string"},
                }],
                "responses": {
                    "200": {
                        "description": "Video content",
                        "content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}},
                    },
                    "404": {"description": "Video job not found"},
                    "503": {"description": "Owning provider is unavailable"},
                },
            }
        },
        "/v1/files": {
            "get": {
                "operationId": "list_files",
                "summary": "List principal-owned files",
                "security": [{"inference_bearer_auth": []}],
                "responses": {"200": {"description": "File list"}},
            },
            "post": {
                "operationId": "create_file",
                "summary": "Upload a file of up to 512 MB",
                "security": [{"inference_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["file", "purpose"],
                                "properties": {
                                    "file": {"type": "string", "format": "binary"},
                                    "purpose": {"type": "string"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "201": {"description": "Uploaded file"},
                    "413": {"description": "File or Batch limit exceeded"},
                },
            },
        },
        "/v1/files/{file_id}": {
            "get": {
                "operationId": "retrieve_file",
                "parameters": [{"name": "file_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "summary": "Retrieve file metadata",
                "security": [{"inference_bearer_auth": []}],
                "responses": {"200": {"description": "File metadata"}, "404": {"description": "File not found"}},
            },
            "delete": {
                "operationId": "delete_file",
                "parameters": [{"name": "file_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "summary": "Delete a file",
                "security": [{"inference_bearer_auth": []}],
                "responses": {"200": {"description": "File deleted"}, "404": {"description": "File not found"}},
            },
        },
        "/v1/files/{file_id}/content": {
            "get": {
                "operationId": "download_file",
                "parameters": [{"name": "file_id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "summary": "Download file content",
                "security": [{"inference_bearer_auth": []}],
                "responses": {"200": {"description": "File content"}, "404": {"description": "File not found"}},
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
                                "required": ["input"],
                                "properties": {
                                    "model": {"type": "string"},
                                    "input": {"oneOf": [{"type": "string"}, {"type": "array"}]},
                                    "stream": {"type": "boolean"},
                                    "zdr_only": {
                                        "type": "boolean",
                                        "description": "When true, select only model-group members with ZDR evidence.",
                                    },
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
                                    "group_name": {"type": "string"},
                                    "max_output_tokens": {
                                        "anyOf": [
                                            {
                                                "type": "integer",
                                                "minimum": 1,
                                                "maximum": _AGENT_POOL_INTEGER_MAX,
                                            },
                                            {"type": "null"},
                                        ]
                                    },
                                    "context_window": {
                                        "anyOf": [
                                            {
                                                "type": "integer",
                                                "minimum": 1,
                                                "maximum": _AGENT_POOL_INTEGER_MAX,
                                            },
                                            {"type": "null"},
                                        ]
                                    },
                                    "stream_usage_supported": {"type": "boolean"},
                                },
                            },
                        },
                    },
                },
                "responses": {"200": {"description": "Worker agent updated"}},
            }
        },
        "/api/v1/model_groups": {
            "get": {
                "operationId": "list_model_groups",
                "summary": "List logical model groups and measured member evidence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Model group collection"}},
            },
            "post": {
                "operationId": "create_model_group",
                "summary": "Create a logical model group from configured agents",
                "security": [{"admin_bearer_auth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ModelGroupWrite"}
                        }
                    },
                },
                "responses": {"201": {"description": "Model group created"}},
            },
        },
        "/api/v1/model_groups/{group_name}": {
            "get": {
                "operationId": "get_model_group",
                "summary": "Get one logical model group",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [{"name": "group_name", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Model group"}, "404": {"description": "Not found"}},
            },
            "patch": {
                "operationId": "replace_model_group_members",
                "summary": "Replace group membership",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [{"name": "group_name", "in": "path", "required": True, "schema": {"type": "string"}}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["member_agent_ids"],
                                "properties": {
                                    "member_agent_ids": {
                                        "type": "array",
                                        "minItems": 1,
                                        "uniqueItems": True,
                                        "items": {"type": "string"},
                                    },
                                },
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "Model group updated"}},
            },
            "delete": {
                "operationId": "delete_model_group",
                "summary": "Delete group membership without deleting agents",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [{"name": "group_name", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {"200": {"description": "Model group deleted"}},
            },
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
        "/api/v1/commercial_evidence_manifests/latest": {
            "get": {
                "operationId": "get_latest_commercial_evidence_manifest",
                "summary": "Review evidence gaps before commercial due diligence",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial evidence manifest"}},
            }
        },
        "/api/v1/commercial_handoff_bundles/latest": {
            "get": {
                "operationId": "get_latest_commercial_handoff_bundle",
                "summary": "Review handoff evidence and resolve remaining commercial gaps",
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial handoff bundle"}},
            }
        },
        "/api/v1/buyer_evidence_manifests/latest": {
            "get": {
                "operationId": "get_latest_buyer_evidence_manifest",
                "summary": "Deprecated alias; use the commercial evidence manifest",
                "deprecated": True,
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial evidence manifest"}},
            }
        },
        "/api/v1/buyer_handoff_bundles/latest": {
            "get": {
                "operationId": "get_latest_buyer_handoff_bundle",
                "summary": "Deprecated alias; use the commercial handoff bundle",
                "deprecated": True,
                "security": [{"admin_bearer_auth": []}],
                "responses": {"200": {"description": "Commercial handoff bundle"}},
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
                "summary": "Submit a principal-owned batch of latency-tolerant requests to the batch backend (pg-llm-batch)",
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
                                    "zdr_only": {
                                        "type": "boolean",
                                        "description": "When true, select only model-group members with ZDR evidence.",
                                    },
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
                "summary": "Poll a submitted batch routing job owned by the authenticated principal",
                "security": [{"admin_bearer_auth": []}],
                "parameters": [
                    {"name": "batch_routing_job_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {"description": "Batch routing job status"},
                    "404": {
                        "description": "Batch job is missing or is not owned by the authenticated principal"
                    },
                },
            }
        },
        "/api/v1/batch_routing_jobs/{batch_routing_job_id}/results": {
            "post": {
                "operationId": "create_batch_routing_job_results",
                "summary": "Retrieve principal-owned batch results and record their usage + cost",
                "security": [{"inference_bearer_auth": [], "trace_bearer_auth": []}],
                "parameters": [
                    {"name": "batch_routing_job_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "200": {"description": "Batch results with recorded usage"},
                    "404": {
                        "description": "Batch job is missing or is not owned by the authenticated principal"
                    },
                },
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
                                "properties": {
                                    "model": {
                                        "type": "string",
                                        "description": "Optional enabled embedding-capable pool model; omitted selects one.",
                                    },
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
                                    "zdr_only": {
                                        "type": "boolean",
                                        "description": "When true, select only embedding-capable model-group members with ZDR evidence.",
                                    },
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
                    "503": {"description": "No enabled embedding-capable agent is available"},
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
                "security": [{"admin_bearer_auth": [], "trace_bearer_auth": []}],
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
