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
  could receive credit despite prompts requiring an answer only; and
- one global case-folding rule would either reject harmless capitalization in
  names or incorrectly accept a case-sensitive symbol such as `au` for `Au`.

The Korean word `사과` also has a fruit sense and an apology-related sense. A
locked translation prompt that omitted the fruit context could reward or punish
a model for resolving an ambiguity rather than for translation quality. The
authoring prompt now names the fruit context explicitly.

These are construct-irrelevant score effects. They can change policy means,
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
explicit non-empty list of accepted answers. Both sides use Unicode NFC plus
whitespace trimming and collapse. Each task declares whether comparison is
case-sensitive. Case-insensitive tasks additionally use Unicode case folding;
case-sensitive tasks retain case after NFC and whitespace normalization.

This treats canonically equivalent text consistently while avoiding Unicode
compatibility normalization that could erase meaningful distinctions. It also
lets capital-city and ordinary-name tasks accept harmless capitalization while
requiring exact case for a chemical symbol. Substrings, explanations, negations,
and undeclared aliases do not match. Empty, non-string, or duplicate normalized
answer keys and non-Boolean case policies fail before provider egress.

Accepted alternatives must be declared in the answer key. For example, the
largest-ocean task explicitly accepts `Pacific` and `Pacific Ocean`; the scorer
does not invent synonyms, translations, abbreviations, prices, or semantic
equivalence.

### Strict-scoring resource boundary

Every expected alias, expected numeric literal, and model answer is limited to
4,096 Unicode code points before normalization or decimal parsing. The limit is
a conservative implementation guard for answer-only tasks, not a statistical or
linguistic sufficiency claim.

- An oversized expected value is an invalid manifest and fails before provider
  egress.
- An oversized model answer scores zero rather than allocating unbounded
  normalization or decimal resources.
- A syntactically matched decimal exponent that Python cannot represent is
  classified as an unusable model answer and scores zero instead of aborting the
  benchmark.
- Expected numeric conversion errors remain manifest errors, preserving the
  distinction between invalid scoring keys and failed model responses.

The provider-response 8 MiB boundary remains independent and authoritative for
network body consumption. The smaller scoring cap prevents a bounded but still
large response from becoming a CPU or memory amplification input at the scoring
layer.

## Authoring and evidence provenance

The repository keeps legacy scorer fields in the reviewed authoring manifest
for historical compatibility, while adding scoring-side strict metadata where
material:

- `strict_texts` declares accepted complete-answer aliases;
- `strict_case_sensitive` declares case-sensitive matching; and
- disambiguating prompt context is author-visible but no expected answer is
  injected into the model request.

Immediately before the supported benchmark CLI starts, the strict composition
root:

1. reads the selected manifest without resolving a provider credential;
2. deep-copies it;
3. validates and upgrades locked numeric scorer `1` to numeric scorer `2`;
4. converts locked substring expectations into explicit exact-text answer lists
   and case policies;
5. validates already-strict numeric and text answer keys;
6. preserves exploratory tasks and already-strict locked tasks;
7. rejects unknown locked scorer contracts;
8. adds `scoring_policy_version = 2026-08-07.3` and a derived manifest version;
9. writes the deterministic derived manifest to an owner-only temporary
   directory; and
10. invokes the existing benchmark with that path.

The existing task-manifest SHA-256 and manifest-version fields therefore bind
artifacts to the exact derived scoring contract that produced them. The private
file is deleted after the one-shot command. No credential, model response,
price, or routing decision enters the transformation.

## Security and authority boundaries

- Importing the normal package does not import the benchmark or strict scorer.
- Activation adds only previously unowned versioned scorer identities and fails
  closed on a registry collision.
- The transformation opens no socket and reads no provider credential.
- Ambiguous manifest selectors, malformed JSON, unsupported locked scorers,
  invalid aliases, invalid case policies, oversized expected values, and invalid
  numeric keys fail before provider egress.
- Oversized or unrepresentable model answers cannot abort the benchmark or
  consume the full provider-response allowance inside the scorer.
- The benchmark remains evidence-generating. Strict scoring does not authorize
  a production route, price, merge, or release.

## Verification

`tests/test_nim_strict_scorer_validity.py` proves:

- full-response numeric equivalence and rejection of containment, negation,
  multiple values, and non-finite values;
- NFC-normalized exact text with task-declared case semantics and explicit
  alternatives;
- case-sensitive chemical-symbol scoring and case-insensitive ordinary names;
- declared `Pacific`/`Pacific Ocean` aliases and Korean fruit-context authoring;
- rejection of substring false positives, malformed alternatives, invalid case
  policies, and normalized duplicates;
- idempotent explicit activation and fail-closed scorer identity ownership;
- deterministic conversion of all locked authoring tasks while exploratory
  tasks remain legacy;
- preservation and validation of already-strict manifests and rejection of
  ambiguous scorer contracts;
- split and equals CLI argument forms, duplicate/missing selector rejection;
- owner-only deterministic temporary manifests; and
- removal of the private derived manifest after the supported CLI call.

`tests/test_nim_strict_scoring_bounds.py` proves the 4,096-character contract,
zero-score handling for oversized and unrepresentable model answers, and
fail-before-egress rejection of oversized expected values.

`tests/test_nim_strict_scoring_integration.py` proves ordinary package-import
isolation and runs the supported transactional publication path end to end,
requiring every locked evaluation cell to carry only the strict scorer versions
and leaving `routing_recommendation` null.

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
