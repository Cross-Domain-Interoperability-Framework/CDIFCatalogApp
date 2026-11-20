# Validation files

One folder per profile the server can validate. Each holds two files taken from
[metadataBuildingBlocks](https://github.com/Cross-Domain-Interoperability-Framework/metadataBuildingBlocks):

| File | Source |
|---|---|
| `schema.json` | `_sources/profiles/cdifCompositeProfile/<profile>/resolvedSchema.json`, copied unchanged. For a single level (`cdifCore`): `_sources/profiles/cdifProfile/<profile>/resolvedSchema.json` |
| `rules.shacl` | generated there with `python tools/validate_shacl.py <profile> --emit-shapes rules.shacl` |
| `conformance.json` | single levels only: `_sources/profiles/cdifProfile/<profile>/conformance.json`, copied unchanged. It holds the level's conformance address, which a single level's schema does not name |

- **Pinned commit:** `75973888dc` (2026-11-17). The form files in `web/public/forms/` name an earlier
  commit, `dcc0e9961f`; the three form files are identical at both commits apart from line endings.
- The profile's examples and failing test cases, from the same commit, are in
  `server/tests/fixtures/<profile>/` and are what the tests check the validator against.

`cdifCore` was added on 20 November 2026 from the same commit. Its rules were generated from files
taken out of that commit with Unix line endings; the `CoreDiscovery` rules were generated from a
Windows checkout and hold `\r\n` inside their query text. Regenerated the same way, the two
`CoreDiscovery` files have the same statements, so the difference is only in that white space.

The server compares the profiles to decide what a record claims: a record claims the profile with
the fewest conformance addresses that has every field the record fills. Pin all profiles from one
commit, or that comparison is between two different versions.

## Content rules for working out a converted record's claim

`server/app/conformance/cdifDataType/<block>/rules.shacl`, for `cdifInstanceVariable`,
`cdifDataStructureComponent` and `cdifProvActivity`: copied unchanged from
`_sources/cdifDataType/<block>/rules.shacl` at the same commit. They are the files
`detect_conformance.py` (in the converters' `validation` submodule) names for the data
description, data structure and provenance levels. When that script names another, copy it here
too; a test fails until then.

Do not edit these files here. To refresh: copy `schema.json`, regenerate `rules.shacl`, copy the
examples and `tests/*-fail.json` into the fixtures folder, update the commit above, and run the
tests. Refresh the form files at the same time so the form and the validator agree.

The conformance addresses the server writes into each record are read from `schema.json`, so they
change with it.
