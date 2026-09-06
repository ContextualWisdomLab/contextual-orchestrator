# Inference-only review preflight, version 1

Status: proposed consumer contract over existing HTTP endpoints. This change
does not publish a release, deploy a gateway, or prove live provider availability.
The existing API requires no new endpoint or administrator privilege.

The canonical request fixture is
[`review_inference_preflight_v1.json`](../tests/fixtures/review_inference_preflight_v1.json).
Consumers must pin the reviewed immutable owner revision containing this fixture.
The CO owner controls discovery, pricing admission and fallback; consumers select
only `orchestrator/free`, never a provider or a paid alternative.

## Request sequence

1. Use a deployment-authorized HTTPS origin and inference bearer credential.
   Validate TLS and prohibit redirects before sending a token or review content.
   Do not accept an origin from PR-controlled data. Keep the bearer in a private
   file, not logs, artifacts, or an exported environment value. Credential
   lifecycle and trusted-origin validation belong to the invoking deployment.
2. GET `/v1/models` with that bearer. Require successful JSON and an exact
   `orchestrator/free` model id. Listing establishes inventory only, not working
   upstream calls, tool support, or ZDR eligibility.
3. POST each required capability request from the fixture to
   `/v1/chat/completions`, using the same inference bearer. For JSON responses,
   parse `choices[0].message.content` and require exactly
   `{"probe_status":"ready"}`. For the tool response, require a `review_probe`
   function call whose parsed arguments equal that object. Never execute the
   requested function; it has no side effects. A 200 response without the
   expected capability result fails preflight.
4. Emit only the fixture's safe evidence fields. Set `requested_model` from the
   request contract to exactly `orchestrator/free`; never copy the response
   `model` or any upstream-selected identity into evidence. Bind
   `gateway_revision` to
   deployment evidence obtained from the trusted operator configuration; do
   not fabricate a revision from `/healthz` or `/v1/models`. Record the UTC
   observation time. Discard raw bodies, headers, model identities selected
   upstream, prompts and credentials. Use a finite error category such as
   authentication_failed, capability_unavailable, transport_failed,
   invalid_response, or policy_unavailable; never copy exception messages.

All fixture requests require `zdr_only: true`. Every subsequent private review
request must carry the same flag: successful preflight does not establish a
session policy. A public-only consumer may explicitly choose `false`, but must
record that choice and cannot claim ZDR enforcement. Failure must stop the review
with a nonzero check and no paid/provider fallback. Cancellation is distinct
from provider failure; this contract adds no model-duration timeout.

Do not call `/readyz`: it intentionally requires admin scope, while `/healthz`
only proves process liveness. Never request an admin token to make preflight
pass. An unavailable free pool, no free ZDR route, failed provider, unsupported
tool/schema request, or missing model must remain a failure.

## Meaning and limits of evidence

CO's existing free admission uses explicit zero-cost metadata; ZDR filtering
uses the operator-provided `privacy:zdr` marker. Tests verify those configured
policies exclude paid or non-ZDR candidates. These markers do not attest actual
provider retention practices or independently validate a provider's pricing.
Operator provenance for those assertions remains required before private use.
Preflight is an observation of these request shapes at that time, not proof
that all future prompts, model routes, or response sizes work.

The regression starts the real split-token HTTP server with deterministic
provider doubles and no provider credentials. It covers scope separation,
free selection, JSON object/schema and tool passthrough, and rejection when
free or ZDR routes are absent or exhausted. These are unit contract tests;
external HTTPS, live free capability and exact-head review evidence remain
deployment verification requirements.

## Consumer adoption prerequisite

`ContextualWisdomLab/.github` must consume this contract in its trusted gateway
bootstrap path, replacing provider-secret sidecar startup without dropping
its evidence gates. Its Strix and Noema trusted-origin rules must be updated
before accepting a non-loopback gateway. The deployment must preserve
`zdr_only` on every private model request. Adoption requires the owner's
reviewed immutable release and successful live capability evidence.

## Credential example reference

The README streams the private token file into curl's header input, rather than
exporting the bearer or including it in command arguments. The documented shell
pipeline is executed by a unit test using a local curl double; it performs no
provider call. curl documents `--header @-` as reading headers from stdin.

curl project. (n.d.). *curl man page: --header*.
<https://curl.se/docs/manpage.html#-H>
