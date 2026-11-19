# SHACL shapes for DCAT-AP and GeoDCAT-AP

Copied unchanged from SEMIC, who publish them under CC BY 4.0. Do not edit them here.

| File | Source | Commit |
|---|---|---|
| `dcat-ap-3.0.0-SHACL.ttl` | `SEMICeu/DCAT-AP`, `releases/3.0.0/shacl/dcat-ap-SHACL.ttl` | `4470b8ea90` (branch `master`, 16 June 2026) |
| `geodcat-ap-3.0.0-SHACL.ttl` | `SEMICeu/GeoDCAT-AP`, `releases/3.0.0/shacl/geodcat-ap-SHACL.ttl` | `7e7d6a82f4` (branch `gh-pages`, 28 April 2026) |

`tests/test_dcat.py` validates the catalog's DCAT output against them.

To move to a newer release: download the new files from the same paths, rename them with their
version, update `SHAPES` in `tests/test_dcat.py` and this table, and run the tests. A newer
release may reject output the older one accepted.
