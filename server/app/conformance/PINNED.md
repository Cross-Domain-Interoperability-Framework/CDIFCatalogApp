# Where these files come from

Each folder here is one group in `app/profile-sources.yaml`. It mirrors part of a building block
repository's `_sources` tree: every `conformance.json` (one per profile: its address, how to
recognise its content, what it requires) and the rule files those name. `detect_conformance.py`,
in the converters' `validation` submodule, reads them. Do not edit them here; a defect is an issue
for the repository the file came from.

| Folder | Repository | Commit | Files |
|---|---|---|---|
| `cdif/` | Cross-Domain-Interoperability-Framework/metadataBuildingBlocks | `75973888dc` | 7 `conformance.json` and 3 `cdifDataType/<block>/rules.shacl`, copied unchanged. The same commit as `app/profiles`. |
| `cdif/` | the same | **not committed there yet** | 4 drafts: `cdifAccess`, `cdifCodelist`, `cdifConceptScheme`, `xasProperties/xasCore`. |
| `dde/` | usgin/ddeBuildingBlocks | **not committed there yet** (drafted against `9c05794`) | 11 drafts, one per profile in `profiles/DDEProfiles`. |
| `geochem/` | amds-ldeo/geochemBuildingBlocks | `c4c5312551` | 66, copied unchanged. Generated there by `tools/build_conformance_sidecars.py`. |

The drafts were written on 20 November 2026 and say "DRAFT" in their own description. They have
not been reviewed in their home repositories. When they are committed there, copy the committed
files over these and replace "not committed there yet" with the commit.

## Known state

- **The geochem group declares nothing today.** Its files require `https://w3id.org/cdif/core/1.1`
  and `.../provenance/1.1`; detection declares 2.0 and compares addresses exactly. It is switched
  off in `profile-sources.yaml` until the generator in geochemBuildingBlocks moves to 2.0.
- **The DDE profiles are independent of each other.** A record claims every DDE profile its
  resource types fit, and `DDEDiscovery` as well.
- **A claim to a profile outside `app/profiles` is not checked further.** The catalog holds a
  schema and rules only for `cdifCore` and `CoreDiscovery`; any other claim rests on the
  recognition test alone.

## To refresh a group

Copy every `conformance.json` under the repository's `_sources`, keeping its path, and every file
a `validityShapes` names. Convert line endings to LF. Update the commit above and run the tests:
one fails if a named rule file is missing or an unnamed one is left behind.
