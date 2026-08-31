---
id: "0036"
title: "Embed a React and Storybook admin interface"
status: proposed
date: 2026-08-27
corrected_date: 2026-08-31
deciders:
  - "repository maintainer"
related:
  - path: "docs/planning/adrs/0033-admin-console-ui-tooling-boundary.md"
    relation: conflicting
---

# ADR 0036: Embedded React and Storybook Admin

Date: 2026-08-27 (status corrected 2026-08-31 — see Implementation Status)

## Status

Proposed. This ADR was originally recorded as "Accepted" on 2026-08-27, the
same PR (#893) that added the `admin_ui/` directory. It is downgraded to
Proposed because no part of the Decision below has actually been carried
out — see [Implementation Status](#implementation-status) — and because it
was never reconciled with [ADR 0033](0033-admin-console-ui-tooling-boundary.md),
an earlier, independently reasoned ADR (accepted 2026-08-23) that
deliberately keeps the admin console as inline stdlib HTML in `admin.py` and
defers a React/Storybook toolchain until one of three concrete triggers is
met. None of those triggers has been met. ADR 0033 remains the operative
decision for what is actually served today; this ADR records a proposed
future direction that conflicts with it and has not been adopted in
practice.

## Implementation Status

An audit of this repository (2026-08-31) found that, four days after this
ADR was accepted, `admin_ui/` is still exactly the unmodified output of the
Vite `react-ts` + Storybook scaffolding command:

- `src/App.tsx` is the default "Get started" counter demo, importing the
  stock `react.svg` / `vite.svg` assets.
- `src/stories/` holds only the default Storybook `Button` / `Header` /
  `Page` stories and their bundled sample assets.
- No file outside `admin_ui/` (other than `pnpm-lock.yaml` and
  `pnpm-workspace.yaml`, which are package-manager bookkeeping, not build or
  serve wiring) references `admin_ui` at all.
- No workflow under `.github/workflows/` builds, lints, or tests it —
  there is no Corepack/pnpm install step, no `vite build`, no
  `build-storybook` step anywhere in CI.
- `contextual_orchestrator/server.py` and `contextual_orchestrator/__main__.py`
  contain no reference to `admin_ui`, a compiled static-asset directory, or
  serving anything other than `admin.py`'s `ADMIN_HTML`.
- `contextual_orchestrator/admin.py` (the 1779-line inline-JS admin
  console) is unchanged and remains the entire `/admin` surface actually
  served in production.

In short: decision item 4 below ("the Python backend will eventually serve
the compiled static assets of this React app") has zero engineering
progress behind it. `admin_ui/` is inert scaffolding, not work in flight.

## Context

The `contextual-orchestrator` repository was originally designed as a strict backend standard-library laboratory without a frontend toolchain (`docs/product-technical-gap-baseline.md` P2 gap). The web admin was a single-file HTML/Vanilla JS string inside `admin.py`.

However, maintaining complex observability, routing metrics, commercial handoff evidence, and a plugin-driven interface requires robust UI/UX, modularity, and accessibility. The business mandates the adoption of React, Storybook, and strict frontend component standards (referencing Figma board `Wr8iMlB9SHkerHSjv0Pe0M`), requiring a fully fledged frontend ecosystem.

## Decision

We will embed a React + Storybook frontend directly within this repository to serve as the Web Admin interface.
1. The frontend code will reside in a dedicated `admin_ui/` (or `frontend/`) directory.
2. Node package management will use Corepack with checked-in lock files, avoiding conflicts with Python's `uv`.
3. UI components will be developed modularly via Storybook, emphasizing responsive layouts and accessibility.
4. The Python backend (e.g., `admin.py`) will eventually serve the compiled static assets of this React app in production, replacing the embedded Vanilla JS string.

None of the above has been executed beyond scaffolding step 1; see
[Implementation Status](#implementation-status).

## Path to Acceptance

Re-promoting this ADR to Accepted requires either:

- Satisfying one of the explicit revisit triggers in
  [ADR 0033](0033-admin-console-ui-tooling-boundary.md) (a second reusable
  screen family, a second consuming repository, or a new component-based
  frontend need) and then actually building out `admin_ui/` past the
  default scaffold, wiring a CI build step, and wiring `server.py` to serve
  its compiled output in place of `admin.py`; or
- A fresh ADR that explicitly reconciles this proposal with ADR 0033's
  reasoning rather than silently overriding it.

Until one of those happens, `admin_ui/` should not be described elsewhere
(docs, roadmap, audits) as delivered or in-progress work.

## Consequences

- **Pros**: Enables a commercial-grade, component-driven UI for the orchestrator without requiring a cross-repository split. Connects directly to Figma designs via Storybook.
- **Cons**: Increases repository footprint. Requires dual build systems (Python `uv` + Node Corepack) during CI/CD. As recorded above, it also introduced an unreconciled conflict with ADR 0033 and an unbuilt, unwired scaffold that read as delivered work until this correction.
