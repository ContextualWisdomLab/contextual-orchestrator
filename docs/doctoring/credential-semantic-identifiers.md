# Credential registry semantic identifiers

## Decision

The credential registry is a reusable security boundary for provider secrets. Repository-owned Python identifiers now carry the bounded-context concepts they represent: `credential_name`, `credential_value`, and `credential_backend`. Casing stays idiomatic Python snake_case; the rule is semantic specificity rather than a casing conversion exercise.

The public helpers `get_credential`, `register_credential`, `delete_credential`, and `set_backend` publish semantic required signatures. Existing external Python callers that still use the historical generic keyword aliases `name=`, `value=`, or `backend=` continue to work through a bounded compatibility adapter. A caller cannot supply both semantic and legacy authority for the same argument, and arbitrary extra compatibility keywords fail closed.

Backend implementations use the same ubiquitous language internally. In-memory state is `credential_store` guarded by `credential_lock`; Postgres query locals are `database_connection`, `database_cursor`, `credential_row`, and `credential_value`. The persistence schema was already compliant and remains unchanged: `provider_credentials`, `credential_name`, `encrypted_value`, and `updated_at`.

## DDD and security boundary

- **Bounded context:** runtime provider credential resolution.
- **Ubiquitous language:** credential name, credential value, credential backend, provider credential.
- **Repository:** `CredentialBackend` abstracts storage without exposing provider secrets to request-time environment lookup.
- **Value identity:** `credential_name` is the stable lookup key; it is not an environment-variable instruction at runtime.
- **Invariant:** runtime provider secret resolution reads the selected KV backend, never `os.getenv` for the provider secret.
- **Invariant:** semantic and legacy keyword forms cannot compete for one argument.
- **Invariant:** unknown compatibility kwargs are rejected rather than silently accepted.
- **Persistence invariant:** Postgres UPSERT remains keyed by `credential_name`; no table, column, encryption, transaction, or conflict-target change is introduced.

## Compatibility contract

The runtime adapter temporarily accepts omitted semantic parameters only so it can translate the legacy keywords. Python's supported `__signature__` introspection hook is installed with `setattr`, not a type-check suppression, so signature-driven callers see the authoritative required semantic parameters while legacy calls remain executable. Positional callers are unchanged.

This is intentionally not a deprecation-warning suppression strategy. No warning is silenced and no security gate is weakened. Legacy keyword aliases remain explicit compatibility behavior until a separately versioned breaking API can retire them.

## Verification

Focused regressions require:

- `inspect.signature` exposes `credential_name`, `credential_value`, and `credential_backend` rather than bare `name`, `value`, or `backend`;
- semantic keyword calls round-trip through the active backend;
- legacy generic keyword calls continue to work;
- semantic-plus-legacy duplicate authority fails closed;
- unknown compatibility keywords fail closed.

The repository's full exact-head Tests, Fuzz, Security, Security Scan, Semgrep, coverage, dependency, OSV, Trivy, Scorecard, OpenCode, Strix, and queue gates remain authoritative.

## Research basis

Identifier research supports conveying the concepts an identifier owns rather than mechanically imposing one spelling style. Schankin et al. reported faster semantic-defect localization with descriptive compound identifiers in an experiment with Java developers. Feitelson et al. found that explicitly choosing the concepts a name should contain, then the words representing those concepts, produced names judged superior to unconstrained choices. Here that means encoding `credential` + `name`, `credential` + `value`, and `credential` + `backend`, while preserving Python's normal naming convention and bounded compatibility aliases.

### References

Feitelson, D. G., Mizrahi, A., Noy, N., Ben Shabat, A., Eliyahu, O., & Sheffer, R. (2022). How developers choose names. *IEEE Transactions on Software Engineering, 48*(1), 37–52. https://doi.org/10.1109/TSE.2020.2976920

Schankin, A., Berger, A., Holt, D. V., Hofmeister, J. C., Riedel, T., & Beigl, M. (2018). Descriptive compound identifier names improve source code comprehension. In *Proceedings of the 26th Conference on Program Comprehension* (pp. 31–40). Association for Computing Machinery. https://doi.org/10.1145/3196321.3196332
