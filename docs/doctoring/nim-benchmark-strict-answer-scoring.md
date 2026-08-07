# NIM benchmark strict complete-answer scoring

## Decision

The supported `python -m contextual_orchestrator nim-benchmark` composition root
uses versioned complete-answer scorers for every locked evaluation task. Legacy
containment scorers remain registered only for historical compatibility and the
exploratory tuning split. They are not used for headline policy comparison.

The strict scoring policy is activated explicitly by the benchmark command. It
is not imported or installed by ordinary `import contextual_orchestrator`, so
the optional benchmark remains outside the standalone gateway's import path and
does not mutate runtime globals eagerly.

## Validity gap

The original numeric scorer awarded credit when an expected number appeared
anywhere in a response. The original text scorer awarded credit when an expected
string appeared as a case-insensitive substring. Those contracts were useful as
simple smoke-test fixtures, but they were not defensible quality evidence:

- `not 21` could receive the same numeric score as `21`;
- `Australia` could satisfy an expected chemical symbol of `Au`;
- explanatory prose, contradictory alternatives, units, and multiple answers
  could receive credit despite prompts requiring an answer only.

This is construct-irrelevant score inflation. It can change policy means,
bootstrap differences, Pareto membership, and the apparent advantage of direct,
route-once, or conduct policies without any real improvement in task accuracy.

## Versioned scoring contracts

### Exact finite number, version 2

`exact_number_match` version `2` requires the entire trimmed response to be one
finite ASCII decimal literal. The literal is parsed with decimal arithmetic, so
numerically equivalent forms such as `21`, `21.0`, and `2.1e1` compare equally
without binary floating-point rounding. Prose, units, negation, multiple values,
`NaN`, and infinities score zero. The expected value itself must be a string
containing one finite decimal literal; malformed answer keys fail before
provider egress.

Version `1` remains unchanged for backward compatibility and is excluded from
the derived locked evidence manifest.

### Exact normalized text, version 1

`exact_text_match` version `1` compares the complete response against an
explicit non-empty list of accepted answers. Both sides use Unicode NFC,
whitespace trimming and collapse, and Unicode case folding. This treats
canonically equivalent text consistently while avoiding compatibility
normalization that could erase meaningful distinctions. Substrings,
explanations, negations, and undeclared aliases do not match. Empty,
non-string, or duplicate normalized answer keys fail before provider egress.

Accepted alternatives must be declared in the answer key. The scorer never
invents synonyms, translations, abbreviations, prices, or semantic equivalence.

## Authoring and evidence provenance

The repository keeps the reviewed authoring manifest stable for historical test
compatibility. Immediately before the supported benchmark CLI starts, the
strict composition root:

1. reads the selected manifest without resolving a provider credential;
2. deep-copies it;
3. upgrades locked numeric scorer `1` to numeric scorer `2`;
4. converts locked substring expectations into explicit exact-text answer lists;
5. preserves exploratory tasks and already-strict locked tasks;
6. rejects unknown locked scorer contracts;
7. adds `scoring_policy_version = 2026-08-07.1` and a derived manifest version;
8. writes the deterministic derived manifest to an owner-only temporary
   directory; and
9. invokes the existing benchmark with that path.

The existing task-manifest SHA-256 and manifest-version fields therefore bind
artifacts to the exact derived scoring contract that produced them. The private
file is deleted after the one-shot command. No credential, model response,
price, or routing decision enters the transformation.

## Security and authority boundaries

- Importing the normal package does not import the benchmark or strict scorer.
- Activation adds only previously unowned versioned scorer identities and fails
  closed on a registry collision.
- The transformation opens no socket and reads no provider credential.
- Ambiguous manifest selectors, malformed JSON, unsupported locked scorers, and
  invalid answer keys fail before provider egress.
- The benchmark remains evidence-generating. Strict scoring does not authorize
  a production route, price, merge, or release.

## Verification

`tests/test_nim_strict_scorer_validity.py` proves:

- full-response numeric equivalence and rejection of containment, negation,
  multiple values, and non-finite values;
- NFC/case-folded exact text with explicit alternatives;
- rejection of substring false positives, malformed alternatives, and
  normalized duplicates;
- idempotent explicit activation and fail-closed scorer identity ownership;
- deterministic conversion of all locked authoring tasks while exploratory
  tasks remain legacy;
- preservation of already-strict manifests and rejection of ambiguous scorer
  contracts;
- split and equals CLI argument forms, duplicate/missing selector rejection;
- owner-only deterministic temporary manifests; and
- removal of the private derived manifest after the supported CLI call.

The permanent NIM quality workflow includes this module in 100% production
statement and branch coverage, 100% public docstrings, wheel packaging, and
installed-package import checks.

## References

Autio, C., Schwartz, R., Dunietz, J., Jain, S., Stanley, M., Tabassi, E., Hall,
P., & Roberts, K. (2024). *Artificial intelligence risk management framework:
Generative artificial intelligence profile* (NIST AI 600-1). National Institute
of Standards and Technology. https://doi.org/10.6028/NIST.AI.600-1

Liang, P., Bommasani, R., Lee, T., Tsipras, D., Soylu, D., Yasunaga, M., Zhang,
Y., Narayanan, D., Wu, Y., Kumar, A., Newman, B., Yuan, B., Yan, B., Zhang, C.,
Cosgrove, C., Manning, C. D., Ré, C., Acosta-Navas, D., Hudson, D. A., …
Koreeda, Y. (2023). Holistic evaluation of language models. *Transactions on
Machine Learning Research*. https://doi.org/10.48550/arXiv.2211.09110

Python Software Foundation. (2026). *decimal—Decimal fixed-point and
floating-point arithmetic*. Python 3 documentation. Retrieved August 7, 2026,
from https://docs.python.org/3/library/decimal.html

Unicode Consortium. (2025). *Unicode normalization forms* (Unicode Standard
Annex #15, Revision 57, Unicode 17.0.0). https://www.unicode.org/reports/tr15/
