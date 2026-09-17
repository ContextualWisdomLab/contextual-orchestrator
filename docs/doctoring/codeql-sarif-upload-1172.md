# CodeQL SARIF upload failure after analysis (#1172)

## Evidence (2026-09-13)

Two required `CodeQL, supply chain, and SBOM` jobs failed at step 8
("Run CodeQL analysis") **after** query evaluation and SARIF export:

| PR | run | attempt | CodeQL job | Outcome |
| --- | --- | --- | --- | --- |
| #1166 | [34748646494](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34748646494) | 1 | 103701120056 | step 8 failure at upload |
| #1167 | [34749024920](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/34749024920) | 1 | 103702151080 | same shape |

Identical log shape on both jobs (`codeql-action` pin
`cdf488f595d80d6e07e03d4674febd5ab45fa938` / CLI 2.27.0):

1. Full query suite evaluated.
2. `Exported results to SARIF (195ms)`.
3. `Uploading results`.
4. ~17 seconds later: `Post job cleanup` with **no** `##[error]` line and no
   "Successfully uploaded results" line.
5. Post step uploaded `codeql-failed-run.sarif`.

`pip-audit`, CycloneDX SBOM, Tests, and Fuzz all succeeded in those runs.
Reruns of the same heads passed. The first failure coincided with a GitHub API
502/500 window observed from this machine.

## Root cause

Transient **code-scanning SARIF upload** failure (GitHub API), not analysis,
permissions, SARIF size, or `pip-audit`. `wait-for-processing` never started:
the step died during the upload HTTP call itself, with no status text flushed to
the step log.

## Fix (this repo)

In `.github/workflows/security.yml`:

1. Bump `github/codeql-action` init/analyze to v4.38.0
   (`b96794f015dfd88f77b49b1c93e0fa7110f94c63`).
2. Run analyze with `upload: never` and `wait-for-processing: false`.
3. Upload via `codeql github upload-results` in a fail-closed retry loop
   (5 attempts, backoff). Do **not** use `continue-on-error`.

## Local reproduction

The upload path is GitHub-hosted and not reproducible offline. Locally you can
only confirm analysis-side health (CodeQL CLI analyze) and that the workflow
YAML still fails closed when upload exhausts retries.
