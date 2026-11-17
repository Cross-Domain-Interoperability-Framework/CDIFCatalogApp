# Validation files

One folder per profile the server can validate. Each holds two files taken from
[metadataBuildingBlocks](https://github.com/Cross-Domain-Interoperability-Framework/metadataBuildingBlocks):

| File | Source |
|---|---|
| `schema.json` | `_sources/profiles/cdifCompositeProfile/<profile>/resolvedSchema.json`, copied unchanged |
| `rules.shacl` | generated there with `python tools/validate_shacl.py <profile> --emit-shapes rules.shacl` |

- **Pinned commit:** `75973888dc` (2026-11-17). The form files in `web/public/forms/` name an earlier
  commit, `dcc0e9961f`; the three form files are identical at both commits apart from line endings.
- The profile's examples and failing test cases, from the same commit, are in
  `server/tests/fixtures/<profile>/` and are what the tests check the validator against.

Do not edit these files here. To refresh: copy `schema.json`, regenerate `rules.shacl`, copy the
examples and `tests/*-fail.json` into the fixtures folder, update the commit above, and run the
tests. Refresh the form files at the same time so the form and the validator agree.

The conformance addresses the server writes into each record are read from `schema.json`, so they
change with it.
