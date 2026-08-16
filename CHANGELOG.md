# Changelog

## Unreleased

### Changed

- `auto` worker selection now applies a lexicographic quality-first, known-cost-second objective: maximum task capability wins first, and quality-equivalent candidates are ordered by trustworthy configured price. Missing or malformed price metadata is unpriced rather than free.
- Runtime policy snapshots now disclose the routing objective and unpriced-model rule.
