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
Proposed because the substantive parts of the Decision below — items 3 and
4, the actual UI development and backend wiring — have not been carried out
(item 2, Corepack package management, has been; see
[Implementation Status](#implementation-status)) — and because it
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
- Decision item 2 (Corepack + checked-in lockfile) is executed: root
  `package.json` declares `"packageManager": "pnpm@11.24.0+..."` and the
  checked-in `pnpm-lock.yaml` resolves a real `admin_ui` workspace entry.
  That is package-manager bookkeeping, not build or serve wiring — no file
  outside `admin_ui/` otherwise references `admin_ui` at all.
- No workflow under `.github/workflows/` builds, lints, or tests it —
  there is no Corepack/pnpm install step, no `vite build`, no
  `build-storybook` step anywhere in CI.
- `contextual_orchestrator/server.py` and `contextual_orchestrator/__main__.py`
  contain no reference to `admin_ui`, a compiled static-asset directory, or
  serving anything other than `admin.py`'s `ADMIN_HTML`.
- `contextual_orchestrator/admin.py` (the 1779-line inline-JS admin
  console) is unchanged and remains the entire `/admin` surface actually
  served in production.

In short: decision items 3 and 4 below (modular Storybook component
development, and "the Python backend will eventually serve the compiled
static assets of this React app") have zero engineering progress behind
them. Apart from its Corepack package-manager setup (item 2), `admin_ui/`
is inert scaffolding, not work in flight on the actual UI.

## Context

The `contextual-orchestrator` repository was originally designed as a strict backend standard-library laboratory without a frontend toolchain (`docs/product-technical-gap-baseline.md` P2 gap). The web admin was a single-file HTML/Vanilla JS string inside `admin.py`.

However, maintaining complex observability, routing metrics, commercial handoff evidence, and a plugin-driven interface requires robust UI/UX, modularity, and accessibility. The business mandates the adoption of React, Storybook, and strict frontend component standards (referencing Figma board `Wr8iMlB9SHkerHSjv0Pe0M`), requiring a fully fledged frontend ecosystem.

## Decision

We will embed a React + Storybook frontend directly within this repository to serve as the Web Admin interface.
1. The frontend code will reside in a dedicated `admin_ui/` (or `frontend/`) directory.
2. Node package management will use Corepack with checked-in lock files, avoiding conflicts with Python's `uv`.
3. UI components will be developed modularly via Storybook, emphasizing responsive layouts and accessibility.
4. The Python backend (e.g., `admin.py`) will eventually serve the compiled static assets of this React app in production, replacing the embedded Vanilla JS string.

Item 2 (Corepack package-manager pinning with a checked-in lockfile) has
also been executed: `package.json` declares `"packageManager":
"pnpm@11.24.0+..."` and `pnpm-lock.yaml` is checked in with a resolved
`admin_ui` workspace entry. Items 3 and 4 have not been executed beyond the
initial scaffold; see [Implementation Status](#implementation-status).

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
