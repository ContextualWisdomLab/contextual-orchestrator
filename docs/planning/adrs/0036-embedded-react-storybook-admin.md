---
id: "0036"
title: "Embed a React and Storybook admin interface"
status: accepted
date: 2026-08-27
deciders:
  - "repository maintainer"
---

# ADR 0036: Embedded React and Storybook Admin

Date: 2026-08-27

## Status

Accepted

## Context

The `contextual-orchestrator` repository was originally designed as a strict backend standard-library laboratory without a frontend toolchain (`docs/product-technical-gap-baseline.md` P2 gap). The web admin was a single-file HTML/Vanilla JS string inside `admin.py`.

However, maintaining complex observability, routing metrics, commercial handoff evidence, and a plugin-driven interface requires robust UI/UX, modularity, and accessibility. The business mandates the adoption of React, Storybook, and strict frontend component standards (referencing Figma board `Wr8iMlB9SHkerHSjv0Pe0M`), requiring a fully fledged frontend ecosystem.

## Decision

We will embed a React + Storybook frontend directly within this repository to serve as the Web Admin interface.
1. The frontend code will reside in a dedicated `admin_ui/` (or `frontend/`) directory.
2. Node package management will use Corepack with checked-in lock files, avoiding conflicts with Python's `uv`.
3. UI components will be developed modularly via Storybook, emphasizing responsive layouts and accessibility.
4. The Python backend (e.g., `admin.py`) will eventually serve the compiled static assets of this React app in production, replacing the embedded Vanilla JS string.

## Consequences

- **Pros**: Enables a commercial-grade, component-driven UI for the orchestrator without requiring a cross-repository split. Connects directly to Figma designs via Storybook.
- **Cons**: Increases repository footprint. Requires dual build systems (Python `uv` + Node Corepack) during CI/CD.
