# Complete dual-license instrument set

The exact aho-corasick 1.1.5 and memchr 2.8.3 archives contain the same complete
MIT grant, Unlicense grant and a separate selection notice. The notice says:

> This project is dual-licensed under the Unlicense and MIT licenses.
> You may use this code under the terms of either license.

The notice grants no independent permission. The previous matcher rejected it
because it is not itself a full instrument. The repair requires all three
complete whitespace-normalized text hashes for the exact declaration
`Unlicense OR MIT`. Missing, duplicate, altered or additional texts fail closed.
Package names and filenames do not participate in the decision. The full texts
are retained as test fixtures; each grant was read in full, including warranty
and attribution clauses.

Verified archive sources and SHA-256:

- https://static.crates.io/crates/aho-corasick/aho-corasick-1.1.5.crate
  `c982642fa9e8606056828ee9a8505737230110bb1099153c79efe865c59d12ba`
- https://static.crates.io/crates/memchr/memchr-2.8.3.crate
  `cf8baf1c55e62ffcace7a9f06f4bd9cd3f0c4beb022d3b367256b91b87513d98`

This deliberately supports only complete reviewed text sets. Other copyright
variants need separate complete evidence; no general notice parser is added.

The new positive control fails before the repair. Notice-only, missing each
instrument, changed notice and additional GPL controls remain rejected. The
three affected test files pass 193 tests (exit 0). Reclassifying the retained
full inventory yields 356 permitted, zero copyleft and 157 held entries. Only
these two Cargo holds change. This is artifact license evidence, not protected
main delivery, a released SBOM, full toolchain/container scope or downstream
runtime acceptance.

## Apache/BSD sets

The same three-instrument check now recognizes the complete reviewed
Apache-2.0/BSD-3-Clause set and Apache-2.0/BSD-2-Clause set. All clauses were
read, including patent termination, attribution, redistribution, contribution
and warranty terms. Exact selection notices and both complete grants are
required. No generic notice parser or file exemption is introduced.

The matching source wheel and raw text digests are recorded in
`evidence/release/1083/apache_bsd_instrument_sources.json`; complete texts are
fixtures. The declaration is still checked separately and missing, changed or
additional instruments remain blocked. Packaging 26.2 and 26.3 have identical
instrument sets but distinct wheel digests.

The prior-head matcher rejects both positive sets; the repaired matcher accepts
them. All 203 affected tests pass. Reclassification changes exactly cryptography
50.0.1 and packaging 26.2/26.3: holds 157 to 154, with no other change. This is
license-text adjudication, not an audit of embedded native library provenance.
