# CDIFCatalogApp

A metadata catalog application in which the [CDIF](https://github.com/Cross-Domain-Interoperability-Framework) JSON-LD record is the stored record.

**Status: planning. No code yet.**

## Intended scope

- **Harvest** metadata from sitemaps, CSW, OAI-PMH, web-accessible folders, CKAN, STAC and DCAT sources, and from file upload.
- **Map** each source format directly to CDIF JSON-LD.
- **Validate** every record with the CDIF JSON Schema and SHACL rules from
  [metadataBuildingBlocks](https://github.com/Cross-Domain-Interoperability-Framework/metadataBuildingBlocks).
- **Store** records in PostgreSQL. Edits to harvested records are kept as an overlay so a re-harvest does not erase them.
- **Search** by text, facets, area, date, geologic age and measured variables.
- **Edit** records in a form generated from the CDIF building blocks, for domain scientists and data repository managers.
- **Offer records for harvest** through a sitemap, OGC API Records, a DCAT catalog feed and CSW, in CDIF, DCAT-AP, GeoDCAT-AP, ISO 19115-3 and ISO 19139.

## First step

A short prototype of the submission form for the CDIF `CoreDiscovery` profile, to test whether a domain scientist can submit a valid record without help.
