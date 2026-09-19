#!/usr/bin/env bash
# Local dev server: loopback-only, auth disabled (allowed for 127.0.0.1). Admin at http://127.0.0.1:8000/admin
# ponytail: --insecure-disable-auth is loopback-only local dev; set CONTEXTUAL_ORCHESTRATOR_TOKEN for shared/exposed binds.
set -euo pipefail
exec python -m contextual_orchestrator --serve \
  --agents examples/agents.mock.json \
  --host 127.0.0.1 --port 8000 \
  --insecure-disable-auth
