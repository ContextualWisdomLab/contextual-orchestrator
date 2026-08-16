# Quality-first, known-cost-second auto routing

## Changed

- `auto` worker selection now applies a lexicographic quality-first, known-cost-second objective: maximum task capability wins first, and quality-equivalent candidates are ordered by trustworthy configured price.
- Missing, boolean, nonnumeric, negative, NaN, and infinite price metadata is classified as unpriced rather than free; explicit zero remains valid known-price evidence.
- Runtime policy snapshots disclose the routing objective and unpriced-model rule.

This fragment remains independently mergeable while the repository's first root `CHANGELOG.md` is being introduced by an earlier open pull request. Release integration must copy this entry into the root changelog before publishing a version that contains the behavior change.
