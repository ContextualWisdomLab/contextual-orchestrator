# Unbounded model timeout prerequisite

ModelClient and its local-provider admission default to no application timeout instead of an implicit 90-second limit. Equivalent-endpoint races preserve `None`, and synchronous embedding waits for provider completion when no finite limit is configured. Durable embedding claim leases remain positive independently of model waiting. Explicit caller timeouts and existing discovery, probe, retention and benchmark boundaries are unchanged.

This is the bounded prerequisite extracted from PR #1053 through ancestor `661ce8db75460c9f5752ba1493aad026e01f5316` and integrated in PR #1118. Later model-specific administrator policy, audit/API changes and their unresolved review findings remain in #1053; this change does not claim those features are released or repaired.

Conflict resolution preserves protected main's `CHANGELOG.md` verbatim at blob `5adce934a08db3199ce9ca89cbfd7e179f2569a3` and moves only this prerequisite's three-line release note into this repository's existing fragment convention. No production source was changed during that resolution and no prior main release note was removed. Owner merge, immutable release and deployment/consumer verification are separate evidence boundaries.
