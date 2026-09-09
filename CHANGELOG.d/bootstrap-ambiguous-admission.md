# Fail closed on ambiguous bootstrap admission

- Reject provider/model-group bootstrap capacity cutoffs when selected and
  excluded candidates have equal or incomplete price evidence, and reject any
  diversity pass that would change the price-evidenced candidate sequence
  without an explicit decision model.
- Preserve raw availability evidence without adding weights, quotas, fuzzy
  identity, or lexical provider/model admission.
- Document the provider-diversity migration boundary and keep ADR 0032 Proposed
  until protected delivery and exact-head verification.
