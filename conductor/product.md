# Product Context

## Name

Contextual Orchestrator

## One-Line Description

A small OpenAI-compatible orchestration service that hides a swappable agent pool behind one model-like API.

## Problem

Teams want the resilience and quality benefits of model orchestration without exposing every caller to agent routing, workflow design, verification, provider selection, or compliance exclusions.

## Approach

Provide one API and one domain model:

- route simple work to one selected worker;
- conduct complex work through planner, worker, verifier, and synthesizer steps;
- keep worker visibility explicit with access lists;
- make the agent pool configurable data.
- expose an admin console for operators to inspect agents, policy, workflow trace, and audit state.

## Non-Goals

- Training a learned coordinator.
- Claiming compatibility with or ownership of any vendor model.
- Adding provider SDKs before stdlib HTTP proves insufficient.
