# NIM benchmark workflow secret isolation

## Decision

The GitHub Actions benchmark workflow separates deterministic dry execution and
live provider execution into different top-level jobs.

- `dry_run_benchmark` runs only for an explicitly selected manual dry run. It
  receives no GitHub Actions secret expression and invokes the benchmark with
  `--dry-run` against the in-process synthetic provider.
- `live_benchmark` runs only for a monthly schedule or an explicitly selected
  manual live run. It is the sole job that binds `NVIDIA_NIM_API_KEY` from the
  GitHub `secrets` context.
- Both jobs retain read-only repository permissions, immutable action commit
  pins, checkout with `persist-credentials: false`, bounded execution time,
  explicit request limits, and separate artifact names.

This is a workflow-level authority boundary, not merely an application branch.
A dry-run process cannot receive the provider credential and therefore cannot
leak, misuse, or accidentally exercise it even if future dry-run code regresses.

## Threat model

The previous workflow used one job for dry and live operation and always bound
`NVIDIA_NIM_API_KEY` into the process environment. The application intended not
to use that value during a dry run, but the credential was still present within
the job's authority. A logging regression, dependency compromise, shell error,
or future code path could therefore expose or use a secret that dry validation
does not require.

GitHub documents that organization and repository secrets are read when a
workflow run is queued. It also warns that automatic redaction is not guaranteed
for every transformed representation of a secret. The safer control is to avoid
binding an unnecessary credential at all, following least privilege rather than
relying on masking after exposure.

## Executable contract

`tests/test_nim_benchmark_workflow_secret_boundary.py` parses the workflow as a
repository artifact and fails unless all of the following remain true:

1. a dedicated `dry_run_benchmark` job exists;
2. the job is restricted to manual `inputs.dry_run == true` execution;
3. the job invokes `--dry-run`;
4. neither `NVIDIA_NIM_API_KEY` nor any `secrets.` expression appears in that
   job;
5. a dedicated `live_benchmark` job exists;
6. the live job is restricted to a schedule or explicit manual live selection;
7. the live job contains the exact NVIDIA secret binding; and
8. the complete workflow contains exactly one provider-secret reference.

These checks are intentionally static. They verify the authority granted by the
workflow source before any benchmark code executes and do not depend on log
redaction or a live provider call.

## Modular boundary

The split does not alter the benchmark Python API, credential registry,
provider-neutral transport seam, reviewer identities, organization-central
workflows, or runtime gateway. Standalone users can continue to run local dry
or live commands. Naruon and other CWL services can consume benchmark artifacts
without inheriting the GitHub Actions credential boundary.

## Operational verification

Before merge, the exact current head must pass the repository test, fuzz,
security, security-scan, SAST, package, coverage, docstring, and independent
review gates. A dry-run workflow dispatch should produce deterministic artifacts
without any configured NVIDIA secret. A live dispatch must fail closed when the
secret is absent and may use it only through the live job's environment binding
and the benchmark's KV bootstrap contract.

## Rollback

Rollback means reverting both the workflow split and its executable contract in
one reviewed change. Recombining dry and live execution into a secret-bearing
job is a security regression and requires an explicit threat-model revision;
it must not be performed solely to reduce workflow duplication.

## References

Booth, H., Ogata, M., Kent, K., Souppaya, M., & Dodson, D. (2025). *Secure
software development framework (SSDF) version 1.2: Recommendations for
mitigating the risk of software vulnerabilities* (NIST Special Publication
800-218 Rev. 1, Initial Public Draft). National Institute of Standards and
Technology. https://csrc.nist.gov/pubs/sp/800/218/r1/ipd

GitHub. (n.d.-a). *Secrets reference*. GitHub Docs. Retrieved August 5, 2026,
from https://docs.github.com/en/actions/reference/security/secrets

GitHub. (n.d.-b). *Secure use reference*. GitHub Docs. Retrieved August 5,
2026, from https://docs.github.com/en/actions/reference/security/secure-use

GitHub. (n.d.-c). *Using secrets in GitHub Actions*. GitHub Docs. Retrieved
August 5, 2026, from
https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
