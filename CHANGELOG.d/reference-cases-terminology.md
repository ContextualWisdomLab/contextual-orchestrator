Renamed the operator Evaluation surface's dataset-class terminology from
"Golden prompts" to the governed **Reference cases** (Korean **참조 평가
사례**) in `contextual_orchestrator/admin.py`'s locale bundles, per #1015.
"Golden" conflated the generated/provisional/adjudicated/validated dataset
states introduced by #1014 and fast-mlsirm#1727 into a single false
authority claim. The translation key itself moves from `golden_prompts` to
`reference_cases` in both the `en` and `ko` bundles (locale-key parity
preserved) and in the mock dataset row rendered by the Datasets view; no
external API, transport, or database field used the old name, so no
compatibility alias was needed. Presentation-only change: no provider
routing, generation, scoring, adjudication, or anchor-promotion behavior is
affected.
