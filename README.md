# CDIFCatalogApp

A metadata catalog application in which the [CDIF](https://github.com/Cross-Domain-Interoperability-Framework)
JSON-LD record is the stored record.

It is meant to replace two long-lived Java catalog applications (GeoNetwork and Esri Geoportal
Server) for the jobs they do in CDIF-related projects: harvest metadata in many formats, map it to
CDIF, let people edit and submit records, make the records searchable, and offer them to other
catalogs. The reasoning and the full design are in [docs/design.md](docs/design.md).

## Status

**Early prototype.** The record submission form came first, to answer one question: can a domain
scientist submit a valid CDIF record without help? A first slice of harvesting and of the outbound
interfaces now exists beside it.

What works today:

- A web form for the CDIF `CoreDiscovery` profile, generated from the CDIF building blocks.
- **Start from a DOI:** fills the form from what DataCite or Crossref has registered.
- **People and organisations:** authors and contributors are found in ORCID, organisations in ROR.
- **Draft saving:** the record saves to the database as you type and is there when you come back.
  A record saved while signed in belongs to that person: nobody else can open it, and they can
  open it from any browser.
- **Check and submit:** the server validates the record with the profile's JSON Schema and SHACL
  rules, lists what it found in plain words with a link to each field, and accepts a submission
  only when nothing is left that must be fixed. Every field has a plain-language label and a line
  of help, and the rules' messages are rewritten in plain words.
- **Harvesting from web folders:** register a folder of metadata files, run it by hand or on a
  schedule, and read what each run added, updated, skipped, withdrew or could not import. Each
  file's format is recognised from its content. CDIF JSON-LD is taken in and checked against the
  profiles it declares. ISO 19139, ISO 19115-2, ISO 19115-3 and DDI-CDI XML are converted to CDIF
  by the CDIF converters and published when the result passes. Other formats are kept as
  received and reported. The harvester obeys each site's `robots.txt`.
- **DCAT catalog feed:** published records as DCAT-AP 3 or GeoDCAT-AP 3, in Turtle, JSON-LD or
  RDF/XML, paged the way CKAN's DCAT harvester expects.
- **Record addresses:** each published record answers as a web page, CDIF JSON-LD, DCAT JSON-LD or
  DCAT Turtle, chosen by the request's `Accept` header.

- **Sign-in with ORCID:** the catalog stores no passwords. Admins are named by ORCID iD in a
  setting, and only admins can use the harvest API.

What does not exist yet: harvesters for anything but web
folders, sitemaps, CSW catalogues, OAI-PMH repositories, STAC catalogues and DCAT catalogues, converters for SDMX and the formats with none (see `docs/design.md`), search, CSW, OGC API Records, a sitemap of the catalog's own records, and any
review step after submission. A submitted record is not published: only harvested records appear
in the feed. See [Intended scope](#intended-scope).

## Run it

Requires Docker. The converters are a git submodule with a submodule of their own, so fetch both first:

```bash
git submodule update --init --recursive
docker compose up --build
```

Then open http://127.0.0.1:5173 (not `localhost`, which ORCID sign-in cannot return to). Stop it with `docker compose down`.

Run the server tests in the running container, because they need the database:

```bash
docker compose exec api pytest
```

No accounts are needed to run the form, the feed or the record pages. Signing in, and so
harvesting, needs an ORCID test client: see [docs/setup-sandboxes.md](docs/setup-sandboxes.md).

## How it fits together

```
browser ── web (React + JSON Forms, port 5173) ── /api ──> api (FastAPI, port 8000) ──> db (PostgreSQL 17)
                                                             │                            ▲
                                                             └──> ROR, ORCID, DataCite,   │
                                                                  Crossref                │
harvesters ── /catalog.ttl, /records/{id}, /sitemap.xml ─────> api        worker ──────────┘
                                                                           └──> harvest sources
```

- The browser only ever talks to this application. The server makes the calls to the outside
  registries and holds the mapping from their answers to CDIF.
- The form's own checks are not trusted. Only the server decides whether a record is valid.
- The form does not hold a complete record. On checking and submitting, the server removes empty
  fields and adds what the author never sees: the prefixes, an identifier, and the catalog record
  entry with its conformance declaration, which it reads from the pinned files.
- A record claims only the level its content reaches. With none of the fields the discovery level
  adds (variables, measurement technique, place, time, quality measurements) it claims the core
  level and is checked against that; filling any one of them adds the discovery claim and its
  checks. The fields are found by comparing the two pinned schemas, not listed in code.
- Harvest jobs wait in a database table. The `worker` service takes them one at a time; there is
  no message broker.
- A record is seen only by those who share a label with it. A published record carries `public`.
- DCAT is a derived view that loses detail. `server/app/mappings/cdif-to-dcat.tsv` says what.
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
| `docker-compose.yml` | The four services (`db`, `api`, `worker`, `web`) for local development. Reads an optional `.env`. |
| `render.yaml` | What Render creates to put the catalog online for colleagues: one web service and one database. See `docs/deploy-render.md`. |
| `deploy/Dockerfile` | The image for that service: the built web app and the server in one container, with the harvest worker beside it. |
| `.dockerignore` | What is left out when that image is built. |
| `.github/workflows/ci.yml` | On every pull request: builds the web app and runs the server tests against PostgreSQL. |
| `.gitignore` | Keeps `.env`, `node_modules/`, build output and caches out of the repository. |

### `docs/`

| File | What it is |
|---|---|
| `design.md` | The design: why replace the Java applications, the architecture, how records are stored, user groups, outbound formats, and the prototype's build plan with its pass and fail criteria. |
| `user-guide.md` | A guide for someone new to the catalog: what it is for, how CDIF profiles stack, and how to read records, fill in the form and harvest. |
| `form-inventory.md` | What is wrong with the stock generated form, found by using it, and the five issues raised with metadataBuildingBlocks. |
| `scientist-sessions.md` | How to run the three scientist sessions that end the prototype: what to prepare, the task sheet, what counts as help, the observation sheet and the result page. |
| `setup-sandboxes.md` | How to register an ORCID sandbox client, and when a DataCite test account is needed. |
| `deploy-render.md` | How to put the catalog on Render, what its free plans mean, and what has not been checked. |

### `server/` — the API (Python, FastAPI)

| File | What it is |
|---|---|
| `app/main.py` | The application: health check, and creating, reading, updating and submitting drafts. Creates the tables at start-up. |
| `app/store.py` | The `records` table and the harvest tables, the database connection, and the queries more than one module uses. |
| `app/access.py` | Who may see or edit a record, decided by labels on records and on users; and what each group of users may do. |
| `app/auth.py` | `/api/auth/…`: sign-in with ORCID, sessions, who the current user is, and the check that guards the harvest API. |
| `app/harvest/__init__.py` | What every harvester provides: gather and fetch. |
| `app/harvest/detect.py` | Recognises what a harvested document is from its content: CDIF and other JSON-LD, plain JSON, the XML metadata formats, Turtle. Lists every format and the converter for it. |
| `app/harvest/convert.py` | Turns a recognised document into CDIF, through the connected converter for its format. |
| `app/harvest/converters.py` | Loads the converter scripts from `server/converters` and calls each the way its own command line does. |
| `converters/` | A git submodule: the CDIF [`converters`](https://github.com/Cross-Domain-Interoperability-Framework/converters) repository, pinned to a commit. Not edited here. |
| `app/harvest/robots.py` | Obeys a site's `robots.txt`: what may be fetched, and the delay between requests. |
| `app/harvest/csw.py` | The CSW harvester: asks a catalogue for the list of its records a page at a time, then for each record in full by its identifier, and takes the record out of the response's wrapper. |
| `app/harvest/dcat.py` | The DCAT harvester: reads a catalogue (Turtle, RDF/XML, JSON-LD or a `data.json`) as a graph, follows its pages, and cuts each dataset out as a document of its own. |
| `app/harvest/oai.py` | The OAI-PMH harvester: asks a repository for its record identifiers a batch at a time, then for each record by its identifier, and takes the record out of the response's wrapper. |
| `app/harvest/sitemap.py` | The sitemap harvester: reads a sitemap (or an index of them, compressed or not) for each page's address and date, and takes the JSON-LD embedded in a page as its metadata. |
| `app/harvest/stac.py` | The STAC harvester: takes each collection of a STAC service, of a list of collections, or of a catalogue file followed through its child links. Items are not harvested. |
| `app/harvest/upload.py` | Uploaded files: kept in the `uploads` table and read from there by a run, so they are converted, checked and stored like harvested ones. |
| `app/harvest/waf.py` | The web folder harvester. It reads a listing page for its links and asks each file for its own modified date. |
| `app/harvest/run.py` | Runs one job: compares the source with what is stored, records each record's outcome, and writes errors as rows. Also scheduling and time-outs. |
| `app/harvest/worker.py` | The worker loop: `python -m app.harvest.worker`. |
| `app/harvest/api.py` | `/api/harvest/…`: register sources, start, stop and read runs. |
| `app/dcat.py` | CDIF records as DCAT-AP 3 and GeoDCAT-AP 3. |
| `app/mappings/cdif-to-dcat.tsv` | Which CDIF property becomes which DCAT property, and which are lost. |
| `app/outbound.py` | `/catalog.{ttl,jsonld,xml}`, `/records/{id}` and `/sitemap.xml`: the catalog feed, the record address, and the sitemap of our own records. |
| `app/messages/CoreDiscovery.json` | Each rule message from the profile's SHACL rules, rewritten in plain words. |
| `app/lookup.py` | `/api/lookup/…`: searches ROR and ORCID, reads a DOI from DataCite or Crossref, and maps each answer to the shapes the form uses. |
| `app/validate.py` | `/api/validate`: completes a form document into a record, checks it against the schema and the rules, and turns the results into findings that each name a field. |
| `app/profiles/<profile>/schema.json` | A profile's JSON Schema, copied from metadataBuildingBlocks. Two are held: `CoreDiscovery` and the core level alone, `cdifCore`. |
| `app/profiles/<profile>/rules.shacl` | The profile's SHACL rules, generated in metadataBuildingBlocks. |
| `app/profiles/cdifCore/conformance.json` | The core level's conformance address, copied from metadataBuildingBlocks. Its schema does not name it. |
| `app/profile-sources.yaml` | The profiles looked for in a converted record, in groups that can be switched on and off: CDIF (on), DDE and geochemistry (off). |
| `app/conformance/<group>/` | What describes each profile in a group: a `conformance.json` per profile, copied from its building block repository, and the rule files those name. `PINNED.md` there says where each came from. |
| `app/profiles/PINNED.md` | Which commit those files come from and how to refresh them. |
| `tests/test_*.py` | The tests, one file per module. Those that need a real database fail, not skip, without one. None uses the network. |
| `tests/fixtures/shapes/` | The SHACL shapes SEMIC publishes for DCAT-AP 3.0.0 and GeoDCAT-AP 3.0.0. The DCAT output must pass them. `PINNED.md` says where they came from. |
| `tests/fixtures/CoreDiscovery/` | The profile's own example records and failing cases from metadataBuildingBlocks. The validator must pass the first and fail the second for the named reason. |
| `tests/fixtures/form-defaults.json` | A copy of the blank form document, for testing what the form really sends. |
| `requirements.txt`, `requirements-dev.txt` | Python dependencies; the second adds the test tools. |
| `Dockerfile`, `pytest.ini` | Development image and test settings. |

### `web/` — the form (React, Vite, JSON Forms)

| File | What it is |
|---|---|
| `src/main.jsx` | Entry point. |
| `src/main.jsx` | Chooses the page from the part of the address after `#`: the landing page, the form (`#/new`), the list of records (`#/records`, `#/search`) or the harvest page (`#/harvest`). |
| `src/pages.jsx` | The landing page with its four choices, the list of records with its search box, and the harvest page for administrators. |
| `src/App.jsx` | The form page: loads the form files, saves the draft as you type, and connects the parts below. |
| `src/corrections.js` | Corrections laid over the copied form files when the form loads: one for each known defect in them, and two choices made here (no "kind of resource" field; language starts as English). |
| `src/Completeness.jsx` | The count of fields filled in, overall and tab by tab, shown above the form. |
| `src/theme.js` | The form's sizes: 14px text in 36px boxes, following the compact profile the CEDAR Embeddable Editor documents. |
| `src/Section.jsx` | A group of fields with a heading that folds it shut and opens it again, and the button that closes or opens them all. |
| `src/RowList.jsx` | A list of groups (grants, licences, variables, downloads) as compact rows, with each entry's less-used fields behind a "More" button. |
| `src/lists.jsx` | Compact controls for fields that take several values, each value a small tag: any list of text, "Specific information type" with its examples, and keywords as text or a term from a vocabulary. |
| `src/Language.jsx` | The language field: a box that offers ten common languages and still takes any text. |
| `src/Drafts.jsx` | The signed-in person's list of their own records, each with a button to open it. |
| `src/DoiPrefill.jsx` | The "Start from a DOI" box. Fills only fields that are still empty. |
| `src/fit.js` | Reshapes a catalog record into the document the form edits, so a copy of a published record can be opened in the form. Follows the form's own schema; simplifies what the form cannot show. |
| `src/renderers.jsx` | Custom form controls: the author and contributor lists, and organisation names for publisher and funder. |
| `src/lookup.jsx` | The search boxes those controls use, backed by `/api/lookup/…`. |
| `src/Report.jsx` | "Check and submit": shows the server's findings and links each one to its field. |
| `src/Account.jsx` | The "Sign in with ORCID" link, and who is signed in. Hidden when the server has no ORCID client. |
| `src/MapFilter.jsx` | The search page's map: a box drawn on it (Leaflet) filters records by the area they cover. |
| `src/wording.js`, `src/wording/CoreDiscovery.json` | The plain-language label and help line for every field, laid over the copied layout without editing it. |
| `public/forms/CoreDiscovery/schema.json`, `uischema.json`, `defaults.json` | The form's data shape, its layout, and the blank record. Copied from metadataBuildingBlocks. |
| `public/forms/PINNED.md` | Which commit those files come from. |
| `index.html`, `vite.config.js`, `package.json`, `package-lock.json`, `Dockerfile`, `.dockerignore` | Build and development setup. `vite.config.js` forwards `/api`, `/catalog` and `/records` to the server. |

## The API

| Request | What it does |
|---|---|
| `GET /api/health` | Whether the server and the database are up. |
| `GET /api/drafts` | The signed-in person's own drafts, newest first: `id`, `name`, `status`, `updated_at`. Empty when nobody is signed in. |
| `POST /api/drafts` | Start a draft. Body: `{profile, document}`. It belongs to whoever is signed in; with nobody signed in it has no owner. |
| `GET /api/drafts/{id}` | Read a draft. A draft with an owner answers 404 to anyone else, here and in the two rows below. |
| `PUT /api/drafts/{id}` | Replace a draft's document. A submitted record becomes a draft again. A draft with no owner becomes the signed-in person's. |
| `POST /api/drafts/{id}/submit` | Validate the stored draft and mark it submitted if nothing must be fixed. Returns the report either way. |
| `GET /api/records?q=&page=&sort=&source=&publisher=&profile=&keyword=&kind=&start=&end=&bbox=` | Published records the requester may see, 20 to a page, for the list and search pages. `q` keeps those whose title, keywords, creators, variable names or description hold those words (ranked, stemmed, `websearch` syntax). `sort` is `relevance` (the default with words), `modified` (the default without, newest first) or `title`. `source`, `publisher`, `profile`, `keyword` and `kind` each keep the records with that facet value (keyword and kind are multi-valued); `start` and `end` (ISO dates) keep the records whose own time span overlaps that window; `bbox` (`west,south,east,north`) keeps those whose own area overlaps that box. The answer carries `facets` (each value's count for the current query), the active `filters`, the `covers` window and the `bbox`. |
| `POST /api/validate` | Validate a document without saving it. Body: `{profile, document, id?}`. Returns `valid`, `counts`, `findings` and the completed `record`. |
| `GET /api/lookup/organisations?q=` | Organisations from ROR. |
| `GET /api/lookup/people?q=` | People from ORCID, by name or iD. |
| `GET /api/lookup/doi?doi=` | What DataCite, then Crossref, has for a DOI, as CDIF. |
| `GET /api/auth/orcid/login` | Send the browser to ORCID to sign in. ORCID returns it to `/api/auth/orcid/callback`. |
| `GET /api/auth/me` | Who is signed in, their groups and permissions, and whether sign-in is set up. |
| `POST /api/auth/logout` | Sign out. |
| `POST /api/harvest/sources` | Everything under `/api/harvest` needs a signed-in admin. Register a harvest source. Body: `{title, url, type, config?, organisation?, frequency?}`. `type` is `waf`; `config` may set `extensions`, `depth`, `profile` and `ignore_robots`; `frequency` is `MANUAL`, `DAILY`, `WEEKLY`, `BIWEEKLY` or `MONTHLY`. |
| `GET /api/harvest/sources`, `GET /api/harvest/sources/{id}` | The sources; one source with its last runs and its record counts. |
| `POST /api/harvest/uploads` | Take a batch of metadata files, as text, and queue a run over them. Body: `{files: [{name, content}], title?, source?, organisation?}`. `title` names a new batch; `source` adds the files to an earlier one, replacing by name. |
| `POST /api/harvest/sources/{id}/jobs` | Queue a run. Refused while one is in progress. |
| `POST /api/harvest/sources/{id}/clear` | Remove a source's records and runs, keeping the source. |
| `GET /api/harvest/jobs/{id}` | A run: its state, counts by outcome, and its errors by stage. |
| `POST /api/harvest/jobs/{id}/abort` | Stop a run. |
| `POST /api/harvest/jobs/{id}/retry` | Queue a run that looks again at only the records that failed in this one. |
| `GET /catalog.{ttl,jsonld,xml}` | The DCAT catalog feed. Parameters: `page`, `modified_since`, `profiles` (`dcat_ap` or `geodcat_ap`). |
| `GET /records/{id}` | A published record, in the format the `Accept` header asks for, or `?format=` one of `html`, `cdif`, `dcat-jsonld`, `dcat-ttl`. |
| `GET /sitemap.xml`, `GET /sitemap/{page}.xml` | The sitemap of our own records: an index pointing to child sitemaps (50,000 records each), which list every published record's address and its last-modified date, so a harvester fetches only what changed. |

Settings read from the environment: `ORCID_BASE`, `ORCID_CLIENT_ID`, `ORCID_CLIENT_SECRET` and
`ADMIN_ORCIDS` for sign-in (see `docs/setup-sandboxes.md`), `PUBLIC_URL` (the address written into the feed
and the one ORCID returns people to),
`CATALOG_TITLE`, `CATALOG_DESCRIPTION`, `CATALOG_PUBLISHER`, `HARVEST_TIMEOUT_MINUTES` (default
1440) and `HARVEST_POLL_SECONDS` (default 5).

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
