# CDIFCatalogApp

A metadata catalog application in which the [CDIF](https://github.com/Cross-Domain-Interoperability-Framework) JSON-LD record is the stored record.

**Status: early prototype.** The design is in [docs/design.md](docs/design.md).

So far: a web app that renders the CDIF `CoreDiscovery` submission form, fills it from a DOI, finds people in ORCID and organisations in ROR, and saves the record as a draft while you type. There is no sign-in and no validation yet, so a draft is tied to the browser it was started in.

Setting up ORCID and DOI test accounts is described in [docs/setup-sandboxes.md](docs/setup-sandboxes.md). The first findings about the form are in [docs/form-inventory.md](docs/form-inventory.md).

## Run it

Requires Docker.

```bash
docker compose up --build
```

Then open http://localhost:5173. Stop it with `docker compose down`.

| Folder | Contents |
|---|---|
| `web/` | React app using JSON Forms. Form files are in `web/public/forms/`, pinned to a commit of metadataBuildingBlocks. |
| `server/` | FastAPI server. Its tests need the database, so run them in the running container: `docker compose exec api pytest`. |
| `docs/` | Design and findings. |

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
