# Bytez filtered catalog recovery

Bytez model discovery now treats a successful empty `task=chat` catalog as
unusable and checks the documented chat-completion-compatible
`task=text-generation` catalog before failing closed. It never broadens to an
unfiltered catalog request. Empty and upstream-failure refreshes emit only
bounded task/outcome/error-code telemetry, retain an existing last-known-good
catalog, and persist only allowlisted failure classes such as
`empty_provider_catalog` or `http_status_500`.

This note preserves PR #1050's original release-note delta while avoiding the
shared `CHANGELOG.md` insertion conflict. Production and test blobs are unchanged
from `749ead36fbad5a378746273a2e39a3a771c5a8a2`. Historical upstream probes do not
establish current provider availability or deployed consumer recovery.
