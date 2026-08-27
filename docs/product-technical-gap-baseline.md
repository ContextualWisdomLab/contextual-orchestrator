# Product and Technical Gap Baseline

This document summarizes the gap analysis of the `contextual-orchestrator` system against enterprise readiness (CSAP, SOC 2), multi-model orchestration requirements, integration points with ContextualWisdomLab ecosystem, and UI/UX standards.

## 1. Ecosystem Integration Gaps
- **fast-mlsirm & Psychometrics**: The orchestrator currently delegates quality control to `fast-mlsirm`. However, time-aware modeling (Temporal Event Psychometrics) and multi-level / multi-membership models (atomistic fallacy prevention) are not natively integrated in the routing decisions yet.
- **TEPP (Temporal Event Psychometrics Platform)**: Real-time integration of temporal latency tracking using TEPP is missing.
- **wardnet**: SOC control plane integration for WAF/IDS is partially complete. We need to formalize the gateway trust boundary with `wardnet` via Rust-based modules.
- **naruon**: PIM/DOM decomposition graphs from `naruon` are not directly queryable via our model's tool calls yet.

## 2. Core Orchestration Gaps (Conductor, Fugu, TRINITY)
- **Calculation Allocation**: Dynamic adjustment of inference-time compute (workflow depth, iterations, self-reflection depth) based on `fast-mlsirm` true parameter estimation is not explicitly surfaced in the `orchestrator/auto` policy yet.
- **Reasoning Effort Profiles**: Temperature is currently misconstrued as reasoning effort in some legacy paths. True $\theta$ ablations using equal-budget profiling are needed to map `lite` vs `full` vs `pro` execution.
- **ZDR Discovery**: While OpenRouter and internal configured gateways now discover ZDR models and parse privacy policies, a gap remains for automated compliance verifications against DPA limits. 
- **Omni-modal support**: We must add seamless audio/video routing natively without explicit `mode` specification if the input contains base64 audio/video chunks.

## 3. Compliance and Security (SOC 2, CSAP)
- **PII Handling**: Masking PII breaks core workflow semantics. A gap exists to implement field-level encryption or purpose-limited access (ADR 0027, 0028) instead of masking.
- **Hot Partitions**: The PostgreSQL schema does not currently enforce consistent hashing or partitioning on `cost_ledger` for high-traffic writes. We must split Read/Write DBs or use UPSERT with distributed locking.
- **Rust Transition**: Core token-counting, vector metrics, and latency matrix calculations are currently in Python. These must migrate to Rust with `pyo3` and MLX/CUDA capabilities.

## 4. Documentation & Research
- APA 7th citations are required for routing strategies (e.g., FrugalGPT, RouteLLM).
- 100% Docstring and Code Coverage required.
- Figma / Storybook integration is required for admin UI components (tracking accessibility, mobile responsiveness, and interaction events).

## Current PR Status & Loops
- Continuous remediation loops are active. PR #868 (`fix/gateway-default-chat-model`) is now updated with empty model defaults and comprehensive ZDR discovery logic.
- We must review open PRs and continuously merge ready features.

*Scheduled for hourly updates.*
