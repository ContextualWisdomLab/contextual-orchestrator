# Unknown license declaration refusal (2026-09-27)

## Cause and repair

The #1303 classifier treated any nonempty declaration without a GPL-family
substring as permitted. CustomCompanyTerms passed SBOM classification;
Vendor-MIT-Restricted could also borrow a real MIT text in inventory
classification. Unknown operands remained invisible in both AND and OR terms.

A closed vocabulary now recognizes the existing standard identifiers and
explicit legacy metadata spellings. Every non-GPL expression operand must be
recognized before the existing conservative conjunction/choice logic runs.
Unknown operands, vendor suffixes and unregistered exceptions are held.
No name, publisher or optional-scope exemption is added. This is declaration
recognition, not a complete SPDX expression parser or instrument adjudication.

Primary identifier reference: [SPDX License List](https://spdx.org/licenses/).
The existing policy still permits its recognized MPL/PSF/Unicode/attribution
terms; this change neither creates a new permissive-license policy nor authorizes
GPL-family conjunctive licensing. License texts and scopes must still pass.

## Evidence and remaining gap

Nine RED controls failed against predecessor source. They exercise three unknown
names as standalone, MIT OR unknown and MIT AND unknown declarations, with both
SBOM and actual-text inventory classifications. Five additional controls retain
explicit metadata aliases and hold the ambiguous Dual License marker.

The release-gate file passes 89 tests (exit 0). The final five affected
evidence/installation test files pass 188 tests (exit 0).

The same full archive set now has Python 111 entries: 91 permitted, zero GPL-family
and 20 held. Cargo remains 40 permitted/3 held; npm remains 223 permitted/136 held.
python-dateutil's generic Dual License declaration is the additional hold.
Its separate BSD/Apache text evidence must be reconciled with that ambiguous
metadata; absence of GPL is not authorization. The previous 158 holds are not
waived. Final release gates, provenance and immutable publication remain pending.

```sh
uv run --locked --extra test python -m pytest -q tests/test_release_license_gate.py
```
