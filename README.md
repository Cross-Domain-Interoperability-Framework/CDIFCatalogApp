# CDIFCatalogApp

A metadata catalog application in which the [CDIF](https://github.com/Cross-Domain-Interoperability-Framework)
JSON-LD record is the stored record.

It is meant to replace two long-lived Java catalog applications (GeoNetwork and Esri Geoportal
Server) for the jobs they do in CDIF-related projects: harvest metadata in many formats, map it to
CDIF, let people edit and submit records, make the records searchable, and offer them to other
catalogs. The reasoning and the full design are in [docs/design.md](docs/design.md).

## Status

**Early prototype.** Only the record submission form exists. Its purpose is to answer one question
before anything else is built: can a domain scientist submit a valid CDIF record without help?

What works today:

- A web form for the CDIF `CoreDiscovery` profile, generated from the CDIF building blocks.
- **Start from a DOI:** fills the form from what DataCite or Crossref has registered.
- **People and organisations:** authors and contributors are found in ORCID, organisations in ROR.
- **Draft saving:** the record saves to the database as you type and is there when you come back.
- **Check and submit:** the server validates the record with the profile's JSON Schema and SHACL
  rules, lists what it found in plain words with a link to each field, and accepts a submission
  only when nothing is left that must be fixed.

What does not exist yet: sign-in (a draft is tied to the browser it was started in, and anyone who
knows its address can read it), harvesting, search, the outbound interfaces, and any review step
after submission. See [Intended scope](#intended-scope).

## Run it

Requires Docker.

```bash
docker compose up --build
```

Then open http://localhost:5173. Stop it with `docker compose down`.

Run the server tests in the running container, because they need the database:

```bash
docker compose exec api pytest
```

No accounts are needed to run it. Setting up an ORCID test client, needed later for sign-in, is
described in [docs/setup-sandboxes.md](docs/setup-sandboxes.md).

## How it fits together

```
browser ── web (React + JSON Forms, port 5173) ── /api ──> api (FastAPI, port 8000) ──> db (PostgreSQL 17)
                                                             │
                                                             └──> ROR, ORCID, DataCite, Crossref
```

- The browser only ever talks to this application. The server makes the calls to the outside
  registries and holds the mapping from their answers to CDIF.
- The form's own checks are not trusted. Only the server decides whether a record is valid.
- The form does not hold a complete record. On checking and submitting, the server removes empty
  fields and adds what the author never sees: the prefixes, an identifier, and the catalog record
  entry with the profile's conformance declaration, which it reads from the pinned schema.
- The form files, the schema and the rules are copies from
  [metadataBuildingBlocks](https://github.com/Cross-Domain-Interoperability-Framework/metadataBuildingBlocks),
  pinned to a commit. They are not edited here.

## Files

### Top level

| File | What it is |
|---|---|
| `README.md` | This file. |
| `CLAUDE.md` | Working notes for AI coding assistants: commands, conventions and known traps. |
| `LICENSE` | Apache License 2.0. |
| `docker-compose.yml` | The three services (`db`, `api`, `web`) for local development. Reads an optional `.env`. |
| `.github/workflows/ci.yml` | On every pull request: builds the web app and runs the server tests against PostgreSQL. |
| `.gitignore` | Keeps `.env`, `node_modules/`, build output and caches out of the repository. |

### `docs/`

| File | What it is |
|---|---|
| `design.md` | The design: why replace the Java applications, the architecture, how records are stored, user groups, outbound formats, and the prototype's build plan with its pass and fail criteria. |
| `form-inventory.md` | What is wrong with the stock generated form, found by using it, and four issues to raise with metadataBuildingBlocks. |
| `setup-sandboxes.md` | How to register an ORCID sandbox client, and when a DataCite test account is needed. |

### `server/` — the API (Python, FastAPI)

| File | What it is |
|---|---|
| `app/main.py` | The application: health check, and creating, reading, updating and submitting drafts. Creates the `drafts` table at start-up. |
| `app/lookup.py` | `/api/lookup/…`: searches ROR and ORCID, reads a DOI from DataCite or Crossref, and maps each answer to the shapes the form uses. |
| `app/validate.py` | `/api/validate`: completes a form document into a record, checks it against the schema and the rules, and turns the results into findings that each name a field. |
| `app/profiles/CoreDiscovery/schema.json` | The profile's JSON Schema, copied from metadataBuildingBlocks. |
| `app/profiles/CoreDiscovery/rules.shacl` | The profile's SHACL rules, generated in metadataBuildingBlocks. |
| `app/profiles/PINNED.md` | Which commit those two files come from and how to refresh them. |
| `tests/test_health.py`, `test_drafts.py`, `test_lookup.py`, `test_validate.py` | The tests. The draft tests need a real database and fail, not skip, without one. The lookup tests use no network. |
| `tests/fixtures/CoreDiscovery/` | The profile's own example records and failing cases from metadataBuildingBlocks. The validator must pass the first and fail the second for the named reason. |
| `tests/fixtures/form-defaults.json` | A copy of the blank form document, for testing what the form really sends. |
| `requirements.txt`, `requirements-dev.txt` | Python dependencies; the second adds the test tools. |
| `Dockerfile`, `pytest.ini` | Development image and test settings. |

### `web/` — the form (React, Vite, JSON Forms)

| File | What it is |
|---|---|
| `src/main.jsx` | Entry point. |
| `src/App.jsx` | The page: loads the form files, saves the draft as you type, and connects the parts below. |
| `src/DoiPrefill.jsx` | The "Start from a DOI" box. Fills only fields that are still empty. |
| `src/renderers.jsx` | Custom form controls: the author and contributor lists, and organisation names for publisher and funder. |
| `src/lookup.jsx` | The search boxes those controls use, backed by `/api/lookup/…`. |
| `src/Report.jsx` | "Check and submit": shows the server's findings and links each one to its field. |
| `public/forms/CoreDiscovery/schema.json`, `uischema.json`, `defaults.json` | The form's data shape, its layout, and the blank record. Copied from metadataBuildingBlocks. |
| `public/forms/PINNED.md` | Which commit those files come from. |
| `index.html`, `vite.config.js`, `package.json`, `package-lock.json`, `Dockerfile`, `.dockerignore` | Build and development setup. `vite.config.js` forwards `/api` to the server. |

## The API

| Request | What it does |
|---|---|
| `GET /api/health` | Whether the server and the database are up. |
| `POST /api/drafts` | Start a draft. Body: `{profile, document}`. |
| `GET /api/drafts/{id}` | Read a draft. |
| `PUT /api/drafts/{id}` | Replace a draft's document. A submitted record becomes a draft again. |
| `POST /api/drafts/{id}/submit` | Validate the stored draft and mark it submitted if nothing must be fixed. Returns the report either way. |
| `POST /api/validate` | Validate a document without saving it. Body: `{profile, document, id?}`. Returns `valid`, `counts`, `findings` and the completed `record`. |
| `GET /api/lookup/organisations?q=` | Organisations from ROR. |
| `GET /api/lookup/people?q=` | People from ORCID, by name or iD. |
| `GET /api/lookup/doi?doi=` | What DataCite, then Crossref, has for a DOI, as CDIF. |

With the application running, FastAPI's own interactive page for these is at http://localhost:8000/docs.

## Intended scope

- **Harvest** metadata from sitemaps, CSW, OAI-PMH, web-accessible folders, CKAN, STAC and DCAT sources, and from file upload.
- **Map** each source format directly to CDIF JSON-LD.
- **Validate** every record with the CDIF JSON Schema and SHACL rules from metadataBuildingBlocks.
- **Store** records in PostgreSQL. Edits to harvested records are kept as an overlay so a re-harvest does not erase them.
- **Search** by text, facets, area, date, geologic age and measured variables.
- **Edit** records in a form generated from the CDIF building blocks, for domain scientists and data repository managers.
- **Offer records for harvest** through a sitemap, OGC API Records, a DCAT catalog feed and CSW, in CDIF, DCAT-AP, GeoDCAT-AP, ISO 19115-3 and ISO 19139.

## Licence

Apache License 2.0. See [LICENSE](LICENSE).
