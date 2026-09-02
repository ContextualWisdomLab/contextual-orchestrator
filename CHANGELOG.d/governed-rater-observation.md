### Added

- Added a domain-neutral `Rater Observation` bounded context with immutable
  rater-configuration, criterion-observation, and rater-invocation domain
  types.
- Added an Anti-Corruption Layer that rejects unknown provider fields and
  structurally prohibits scores, latent traits, levels, placement, pass/fail,
  certification, and employment decisions at the observation boundary.
- Retained the existing CEFR gateway as a compatibility profile while new
  consumers migrate to the generic published language owned by `fast-mlsirm`.
