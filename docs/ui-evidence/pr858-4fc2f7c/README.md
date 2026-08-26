# Admin UI runtime audit — PR #858 predecessor `4fc2f7c4`

This evidence was captured on 2026-08-26 from PR #858 exact head
`4fc2f7c4c211f00b8f578f062224a9fdd39e9c47`, plus the uncommitted minimal
audit repair represented by the files in this directory's eventual commit.
It is local runtime evidence, not hosted-check or protected-main evidence.

## Runtime evidence

- `desktop-overview.png`: authenticated overview at 1440 x 1000.
- `mobile-overview.png`: authenticated overview at 390 x 844.
- `mobile-models-scrolled.png`: the same mobile viewport after keyboard focus
  and horizontal scroll expose Recent latency and Success.
- `desktop-session-required.png`: unauthenticated edge state with an actionable
  path to Access Control.
- `runtime-report.txt`: browser-observed overflow, navigation visibility, edge
  copy, and model status values. Both tested viewports reported zero document
  overflow; the mobile selector was visible and sidebar hidden. The keyboard
  focusable model-table region measured 560 px of content in a 364 px viewport
  and reached `scrollLeft=196`; all three mock models displayed their
  backend-provided `active` status.

Commands (the token is a disposable loopback-only development value):

```sh
uv run --no-project --with-requirements fuzz/requirements-property.txt \
  python -m contextual_orchestrator --serve \
  --agents examples/agents.mock.json --host 127.0.0.1 --port 8858 \
  --auth-token pr858-local-ui-audit --insecure-admin-session-cookie

PLAYWRIGHT_BROWSERS_PATH=/tmp/pr858-playwright \
  uv run --no-project --with playwright python /tmp/pr858_capture.py

uv run --no-project --with-requirements fuzz/requirements-property.txt \
  python -m pytest -q tests/test_admin_contract.py
```

## Reality-based findings

The model table previously assigned `degraded` to the second row solely by
array position. It now renders the existing admin payload's `active` or
`disabled` state without inventing a health score or threshold. The existing
measured latency and success columns remain unknown (`—`) until observations
exist. Keyboard focus is visible, mobile form controls have a 44 px target,
and reduced-motion users do not receive smooth scrolling. The unauthenticated
overview now exposes a translated action that opens the existing session form.

The repository records an editable Figma file and FigJam board in
`docs/figma_artifacts.md`. No Storybook configuration or stories exist in this
source tree. ADR 0033 deliberately defers Storybook until a second reusable
screen family, a second consuming repository, or a component-based frontend
exists; adoption remains an acceptance condition at that boundary, not a
capability claimed by this audit.
