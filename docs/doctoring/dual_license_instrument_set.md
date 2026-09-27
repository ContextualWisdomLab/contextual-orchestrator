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

This deliberately supports one complete reviewed text set. Other copyright
variants need separate complete evidence; no general notice parser is added.

The new positive control fails before the repair. Notice-only, missing each
instrument, changed notice and additional GPL controls remain rejected. The
three affected test files pass 193 tests (exit 0). Reclassifying the retained
full inventory yields 356 permitted, zero copyleft and 157 held entries. Only
these two Cargo holds change. This is artifact license evidence, not protected
main delivery, a released SBOM, full toolchain/container scope or downstream
runtime acceptance.
