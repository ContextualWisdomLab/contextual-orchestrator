# Operability: CEFR language observations

## Signals

Record these fields from the returned bounded artifact, not raw provider text:

- `request_replay_identity` and `observation_id`;
- rater family/version, served model, provider, and provider-version evidence;
- `parse_state`, `verifier_state`, `failure_code`, and sanitized usage counts;
- `human_review.required` and sorted reason codes;
- panel size, observed count, incomplete count, and disagreement count.

## Runbook

1. If `missing_contract` or `contract_incompatible` appears, stop the operation
   and deploy the released adapter matching both contract versions.
2. If `capability_mismatch` or `unsupported_response_format` appears, inspect
   the discovered catalog's structured-output declaration. Do not send the
   request directly to a provider.
3. If `timeout` or `provider_error` rises, retain the failed denominator and
   verify provider health, KV credential resolution, and gateway capacity.
4. If `malformed_json`, `unsupported_evidence`, `disagreement`, or `uncertain`
   appears, route the criterion to the governed human-review owner. Do not
   convert the result to a CEFR level or score.
5. Replaying the same request uses the same `request_replay_identity`; compare
   contract, prompt, model, and workflow revisions before interpreting changes.

The operation is bounded by `MAX_CEFR_RATERS`, `MAX_CEFR_REFERENCE_COUNT`, the
response byte limit, and caller-selected `max_concurrency`. Provider outages
must remain visible as failed or incomplete observations rather than clean
quality evidence.
