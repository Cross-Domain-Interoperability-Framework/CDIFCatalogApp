# CDIF Catalog Design

Proposal to replace the GeoNetwork and Geoportal deployments · 16 November 2026 · Draft for discussion

Replace both Java catalogs with a small Python application in which the CDIF JSON-LD record is the stored record. Harvesting, mapping and validation reuse tooling that already exists; the new work is a store, a search API, and an editor.

## Why replace instead of upgrade

Both applications treat something other than CDIF as the canonical record, so every CDIF record takes a round trip through another model.

- **GeoNetwork fork** (`DDEconfig`, 107 commits past 4.4.9). The DDE-specific work is about 17,000 lines of XSLT, about 600 lines of harvester Java, an editor configuration and SKOS vocabularies, carried on roughly 7,900 upstream files. CDIF comes in through a 1,856-line transform to ISO 19115-3 and goes out through a 1,218-line transform back. The Java framing library drops fields, which a hand-written recovery step patches.
- **Geoportal deployment.** Unmodified Esri applications plus one 670-line connector, which converts JSON-LD to XML and strips prefixes by pattern matching before transforming to ISO.
- **Operations.** The fork's own notes record a 430-second asset compile, builds blocked by retired dependency repositories, and commands that report success while doing nothing.

The requirement is small. The platform carrying it is large and its canonical model is the wrong one.

## Architecture

1.  **Harvest:** Sitemap, CSW, OAI-PMH, WAF, CKAN, STAC, DCAT, file upload
2.  **Map:** Source format to CDIF JSON-LD
3.  **Validate:** JSON Schema and SHACL; verdict stored
4.  **Store:** PostgreSQL: source, overlay, published
5.  **Serve:** Search API, search page, record pages, editor

| Layer                   | Choice                                                                                                                                                                       | Already in hand                                                                                                                       |
|-------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| Harvest                 | Small Python connectors. Sources are registered in the database and run by a worker that reads a job table; Dagster if sources pass about 50.                               | Sitemap crawling and conformance dispatch, to port from the fork's Simple URL harvester.                                              |
| Mapping                 | XML through XSLT 3 run from Python (`saxonche`). JSON and RDF through SSSOM-table converters. All map straight to CDIF.                                                      | `iso19115-3-to-cdif.xsl` and the DDE transforms are reusable as they are. The DCAT and Croissant converters are already table-driven. |
| Validation              | JSON Schema plus SHACL on every save and every harvest.                                                                                                                      | The building block schemas and rules, `FrameAndValidate`, `detect_conformance`.                                                       |
| Store and search        | PostgreSQL with JSONB, PostGIS and full-text search.                                                                                                                         | New.                                                                                                                                  |
| API                     | FastAPI, following the stac-fastapi and pgstac pattern. OGC API Records for search and harvest, a sitemap, and a DCAT catalog feed. CSW through a read-only pycsw front end. | New.                                                                                                                                  |
| Search and record pages | A static search page. Record pages embed their JSON-LD and are listed in a sitemap.                                                                                          | The Flask record viewer.                                                                                                              |
| Editor                  | JSON Forms with React and Material renderers.                                                                                                                                | Generated form schemas; hand-written layouts for `CoreDiscovery` and `xasDocument`.                                                   |

PostgreSQL is sufficient for tens of thousands to a million records. Move search to OpenSearch only if facet counts or relevance ranking become a bottleneck, because it adds a second service to run and keep in sync.

## Record model

There are two kinds of record. **Authored** records are created in the catalog and owned by it. **Harvested** records come from a registered source and are refreshed on each harvest.

### Editing harvested records

Data managers can edit harvested records. Their edits are stored as an overlay so that a re-harvest does not erase them. Each harvested record keeps three things:

- **Source:** The record as last harvested. Never edited.
- **Overlay:** The data manager's changes, stored per top-level property.
- **Published:** Source with the overlay applied, validated and indexed.

| On re-harvest                            | Result                                                                                                                                                                                         |
|------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Source unchanged                         | Nothing happens.                                                                                                                                                                               |
| Source changed elsewhere                 | The new source is taken and the overlay is reapplied automatically.                                                                                                                            |
| Source changed in an overridden property | The record is flagged as a conflict and the published version stays as it was. The data manager sees a side-by-side comparison and keeps their edit, takes the upstream value, or edits again. |

- **Overlays replace whole properties**, such as the full creator list. CDIF records are list-heavy, and a change addressed to "the third creator" breaks when the source reorders its list.
- **Revert** drops the overlay for one property or all of them and returns the record to the source version.
- **Provenance.** The catalog record entry states that the record was modified locally, by whom and when, so curator edits are not presented as the source repository's own metadata.

> **Decided:** edits to harvested records publish immediately. They do not go through curator review. Validation still runs on save.

### How records are stored

Records are stored in PostgreSQL as JSON documents (the `jsonb` column type). Each harvested record is one row holding its documents side by side.

| Column | Type | Contents |
|---|---|---|
| Source, as received | text | The record exactly as the source sent it: ISO XML, DCAT Turtle, JSON-LD or another format. Never changed. |
| Source format | text | What the as-received text is, so the right mapping can be chosen again. |
| Source, as CDIF | jsonb | The as-received record after mapping to CDIF. Never edited by hand. |
| Overlay | jsonb | A data manager's edits, keyed by top-level property. Empty for most records. |
| Published | jsonb | Source-as-CDIF with the overlay applied. Search and the harvest interfaces serve this. |
| Validation result | jsonb | Violations, advisories, and the CDIF profiles the record meets. |
| Harvest source | reference | Which registered source the record came from. |
| Identifier at source | text | The record's own identifier in the source system. With the harvest source, it finds the same record again on re-harvest. |
| Content hash | text | A hash of the as-received text. If it is unchanged on re-harvest, nothing else is recomputed. |
| Status and timestamps | | Published, conflict or withdrawn; first harvested, last harvested, last changed. |

- **Why keep the record as received.** When a mapping is corrected or extended, every affected record is re-mapped from the stored text. Without it, a mapping fix would need a full re-harvest, and records whose source has gone offline could never be improved.
- **Authored records** use the same table without the source columns: the document written in the editor is the published document. Drafts are held separately until they are submitted.
- **Search does not read the JSON directly.** A flat search row is derived from each published record on save: title, description, keywords, a geometry for the bounding box, date ranges and a full-text index. The JSON is the record; the search row is an index that can be rebuilt from it at any time.
- **ISO and DCAT output** are stored the same way: derived from the published record on publish, never edited.

Built so far: the drafts table, and the `records` table with the layout above. Harvested records fill it; publishing a submitted draft into it is not built.

### How harvests are stored

The model is the one ckanext-harvest uses, reimplemented.

| Table | One row is | Holds |
|---|---|---|
| `harvest_sources` | A registered source | Address, type, settings, owning organisation, how often it runs and when it runs next. |
| `harvest_jobs` | One run of a source | Its state (new, running, finished, aborted) and when each stage started and ended. |
| `harvest_objects` | One source record seen in one run | The record's identifier at the source, the source's modified date, and how it ended: added, updated, not modified, deleted or errored. |
| `harvest_errors` | One failure | The run, the record if there was one, the stage (gather, fetch, import or job) and the message. |

- **Three stages.** Every kind of source provides gather (list what it holds), fetch (get one record as sent) and a mapping to CDIF. The runner does everything else.
- **Changed since, only after a clean run.** A source is asked for changes since the last run that finished with no errors. After a run with errors the next asks for everything, so a failure cannot hide a record for good.
- **Deletion needs a complete listing.** A record missing from a full listing is withdrawn. A "changed since" listing says nothing about what it leaves out.
- **Invalid records are stored, not published.** The text as received is kept, the problem is an error row, and the record is not served.
- **The queue is the job table.** A worker claims a waiting job with a row lock that other workers skip. There is no message broker.
- **Not built:** email to an organisation's admins when a run fails, because there are no users to send it to until sign-in exists.

## Who submits, and how

### Domain scientists: a guided form

- **Start from an identifier.** Pre-fill from a DOI; choose people by ORCID and organisations by ROR. Authors search and select, and the form writes the identifier.
- **Minimum first.** Open with the fields `CoreDiscovery` requires, then offer optional sections with a completeness indicator. Violations block; advisories are shown as suggestions.
- **Plain-language labels and help** taken from the building block descriptions, with autosaved drafts.
- **Review before publishing.** Submissions move from draft to submitted to published, with a curator approving.

### Data repository managers: bulk submission

- **Self-service harvest registration.** Enter a sitemap, CSW, OAI-PMH or WAF address, run a test harvest, and read a per-record validation report before anything is published.
- **File upload and an API token** for one-off batches in JSON-LD or ISO XML, with the same report.
- **The form editor** for correcting individual records, including harvested ones.

The validation report is seen by both groups, so it names the field and the fix in plain words instead of echoing raw schema errors.

## Search

Search runs over published records. One search service backs both the search page and the public API, so anything a person can find, a program can find the same way.

| Capability         | How                                                                                                     |
|--------------------|---------------------------------------------------------------------------------------------------------|
| Full text          | Title, description, keywords, creators and variable names, ranked, with title matches weighted highest. |
| Facets             | Resource type, keyword vocabulary terms, publisher, source repository, and CDIF profile conformance.    |
| Spatial            | Bounding box drawn on a map, matched against the record's spatial extent.                               |
| Temporal           | Calendar date range, and geologic age range in Ma for DDE records.                                      |
| Variables          | For records with data description content: search by measured property, unit, or variable name.         |
| Sorting and paging | By relevance, date modified, or title.                                                                  |

- **API form.** OGC API Records: `q`, `bbox`, `datetime`, and CQL2 filters for everything else.
- **Signed-in views.** Submitters see their own drafts; data managers can filter to records with overlays or unresolved conflicts in their organisation's sources.
- **Indexing.** A flat search row is derived from each published record on save, so search fields can change without touching the stored CDIF.

## Harvest interfaces

Other catalogs harvest this one through four interfaces in the first release. All serve the same published records.

> **Decided:** CSW is in the first release, offering both ISO 19139 and ISO 19115-3, selected per request.

| Interface         | Audience                                                                                                                       | Release   |
|-------------------|--------------------------------------------------------------------------------------------------------------------------------|-----------|
| Sitemap           | schema.org and CDIF harvesters. Lists every record address with its last-modified date, so harvesters fetch only what changed. | First     |
| OGC API Records   | Harvesters that want to filter: by date, area, profile or source. Each item links to every format the record is available in.  | First     |
| DCAT catalog feed | DCAT-AP harvesters such as CKAN and European data portals. A paged RDF catalog in Turtle, JSON-LD or RDF/XML.                  | First     |
| CSW               | Older ISO-based catalogs. Served by pycsw reading ISO XML derived from each published record.                                  | First     |
| OAI-PMH           | Repository aggregators. Small to add once the formats exist.                                                                   | On demand |

### How CSW is served

- **ISO XML is derived, not stored as the record.** On publish, the CDIF record is transformed to ISO 19115-3 and written to a table that pycsw reads. CDIF stays the only record anyone edits.
- **The transform exists.** `fromJsonCdif.xsl` in the GeoNetwork fork already maps CDIF to ISO 19115-3 and was round-trip tested on the ADA records. It moves to run under XSLT 3 in Python.
- **Both ISO 19115-3 and ISO 19139 are served.** The harvester chooses with the `outputSchema` parameter of its CSW request. Both documents are produced on publish and stored: 19115-3 from CDIF, then 19139 from that through a standard transform.
- **To verify during the build:** that pycsw returns the stored document for each requested schema instead of regenerating one from its own summary fields, which would lose detail. If it cannot for 19115-3, the catalog answers those CSW requests itself.
- **pycsw runs as a read-only front end** on its stable release, sharing the same PostgreSQL database. It does not accept transactions; all writes go through the catalog.
- **ISO output is lossy too.** Data structure and variable-level detail have only partial homes in ISO, and the mapping notes what is dropped.

### Formats offered per record

A record is offered only in formats its content can honestly fill. The catalog records which CDIF profiles each record meets when it is validated, and advertises formats from that.

| Format                                                              | Offered when                                                               |
|---------------------------------------------------------------------|----------------------------------------------------------------------------|
| CDIF Discovery                                                      | Every published record.                                                    |
| CDIF Data Description, Data Structure, Manifest, Provenance, Access | The record's content meets that profile.                                   |
| DCAT-AP                                                             | Every published record, mapped from CDIF.                                  |
| ISO 19115-3 and ISO 19139                                           | Every published record, through CSW and as a format on the record address. |
| GeoDCAT-AP                                                          | The record has spatial or other geographic content.                        |

- **One CDIF document per record.** The CDIF profiles are layers of one record, so the catalog serves the full record, declaring every profile it meets. A harvester asking for Discovery receives a record that also carries the richer layers. A profile parameter filters which records are returned; it does not cut records down.
- **Asking for a format.** A format and profile parameter on the record address, plus standard content negotiation. Profiles are named by their published CDIF conformance addresses.
- **A record with no description still goes out as DCAT.** DCAT-AP requires a description and CDIF does not, so the DCAT description is then the title followed by "description missing".
- **DCAT output loses detail, and says so.** DCAT-AP has no place for variable-level description or data structure. The mapping table states what is dropped, as the existing converters do.
- **New work.** A CDIF-to-DCAT mapping. The existing DCAT-to-CDIF table is the starting point but runs the other way.

## Groups and permissions

A fixed set of named permissions assigned to groups. A user can belong to more than one group. Sign-in is through an external identity provider; the catalog stores no passwords.

| Group         | Permissions                                                                                                                     |
|---------------|---------------------------------------------------------------------------------------------------------------------------------|
| Submitters    | Create and edit their own records; submit them for review.                                                                      |
| Data managers | Everything submitters can do, plus: register and run harvest sources, **edit harvested records**, resolve re-harvest conflicts. |
| Curators      | Review and publish submissions.                                                                                                 |
| Admins        | Manage groups, membership and all sources.                                                                                      |

Harvest-edit is its own named permission, so it can be granted to another group later without a code change.

> **Decided:** harvest-edit is scoped by organisation. A data manager can edit harvested records only from sources their own organisation owns. Admins can grant a catalog-wide version to central staff.

## The editor

The form schema for each profile is already generated from the building blocks. A DDE layout would be a third hand-written layout, carrying the eight tabs of the current GeoNetwork `ddeview` editor across.

### Custom controls to build

- **Vocabulary picker:** autocomplete over the existing SKOS thesauri.
- **Spatial extent:** draw a bounding box on a map.
- **Geologic age:** the Ma fields from the current editor.
- **Reference or inline:** choose an existing person or organisation, or create one in place. ORCID and ROR lookup cover most cases.

### What the form cannot be trusted with

- **The generated form schema drops `contains` constraints.** A record can pass the form and fail its profile, so the server validates against the full schema and SHACL on save.
- **Neither existing layout exposes the conformance declaration.** Authors are not asked for it; the server stamps it from `detect_conformance`.
- **The default record files are not checked by anything today.** They join the validation gate before they seed real records.

## Alternatives considered

| Option                          | Why not                                                                                                                                 |
|---------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| GeoNetwork 5                    | No release, no harvesting module, and it still runs beside a GeoNetwork 4 instance.                                                     |
| CKAN, piveau, Magda, InvenioRDM | Each imposes its own canonical model and a heavier stack than the one being retired.                                                    |
| pycsw as the store              | No JSON-LD or DCAT input and a fixed flat record model. Usable as a standards front end over a derived record.                          |
| Gleaner                         | Dormant since 2024. Its successor at Internet of Water is the closest existing pattern but is unreleased and shaped around one project. |
| Stay on Geoportal 4             | The fallback. Actively maintained, but it keeps the ISO round trip and Java-hosted mapping scripts.                                     |

## Risks

- **Editor usability for scientists.** CDIF's nested and either-or structures render poorly in a default JSON Forms layout. This is the main risk and the reason for the spike below.
- **You own the search page and facet queries.** Nothing off the shelf supplies them for a JSON-LD store.
- **Overlay conflicts.** A source that rewrites records often will generate conflicts for every overridden property. Conflict volume needs watching once real sources are connected.
- **Features left behind.** GeoNetwork's per-record privilege matrix, batch editing, and transactional CSW are not rebuilt.

## Order of work

1.  **Spike, about two weeks.** The scientist path for `CoreDiscovery`: sign-in, DOI pre-fill, ORCID and ROR pickers, save, server validation, report. Test with three scientists.
2.  **Pipeline and store.** Port the connectors and transforms, and reproduce the 121 ADA records already used for round-trip testing.
3.  **Search API, search page and record pages**, with the sitemap and OGC API Records harvest interfaces.
4.  **ISO output and the CSW front end.**
5.  **CDIF-to-DCAT mapping and the DCAT catalog feed.**
6.  **Harvest registration, overlay editing and conflict handling** for data managers.
7.  **DDE editor layout and the remaining custom controls.**
8.  **Retire GeoNetwork.** Until then it stays up and is harvested over CSW.

## To do: practices taken from CKAN

CKAN is not the base for this catalog (see Alternatives considered), but a review of `ckan`, `ckanext-dcat`, `ckanext-spatial`, `ckanext-harvest` and `ckanext-scheming` on 18 and 19 November 2026 found practices worth adopting. All but `ckanext-scheming` are AGPL, so each item below is reimplemented here, not copied.

All six were built on 19 November 2026, each as a first version. What each still lacks is in the last column.

| To do | Detail | Belongs to step | Built, and what is missing |
|---|---|---|---|
| **Test DCAT output against the official shapes** | Serialise records as DCAT-AP and GeoDCAT-AP, then run pyshacl against the SHACL shapes published by SEMIC. Fetch the shapes from SEMIC and pin them, as the CDIF schema and rules are pinned. | 5 | Built for DCAT-AP 3.0.0 and GeoDCAT-AP 3.0.0, on the three example records. |
| **DCAT catalog feed with the interface CKAN uses** | `/catalog.{ttl,jsonld,xml}` with `page`, `modified_since` and `profiles=` parameters, and Hydra paging triples (`hydra:PagedCollection` with first, next, last and total). Existing DCAT harvesters, CKAN's included, already walk this. | 5 | Built. Not yet walked by a real CKAN harvester. Lists harvested records only. |
| **Record address answers by `Accept` header** | The record address serves HTML, CDIF JSON-LD, DCAT JSON-LD or DCAT Turtle according to the request's `Accept` header, and the HTML page advertises the others with `<link rel="alternate">`. | 3 and 5 | Built. The web page is a plain summary, not the designed record page. |
| **Web folder listings: three parsers** | Apache, nginx and IIS directory listings differ. Parse each separately, choosing by the response's `Server` header, and take the modified date from the listing to skip unchanged files. | 2 | Built, for folders of CDIF JSON-LD. nginx and Apache checked live; IIS not. |
| **Organisation-scoped access by labels** | Each record carries labels (`public`, `member-<organisation>`, `creator-<user>`), each user carries labels, and search and edit checks filter on the overlap. This is how the data managers' organisation-scoped harvest-edit permission is built. | 3 and 6 | Labels and the checks are built and the feed uses them. With no sign-in, every reader is anonymous. |
| **Plain-language labels and help text** | Write a label and one line of help for every form field, and rewrite the SHACL rule messages shown in the validation report. CKAN's DCAT-AP form schemas are reference wording only; the text here is our own. | 7, and the report before the scientist sessions | Built for `CoreDiscovery`: 65 fields and 122 rule messages. Not yet read by a scientist. |

## Spike build plan

A spike is a short, time-limited prototype built to answer one risky question before committing to the full build. It is a test, not the first version of the product, and most of its code may be thrown away.

This spike answers one question: can a domain scientist submit a valid `CoreDiscovery` record through a JSON Forms editor without help? It is sized for one developer over ten working days. That figure is an estimate, not a measurement.

### Pass and fail

| Result of three scientist sessions                     | Decision                                                                                      |
|--------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| 3 of 3 submit a valid record unaided within 20 minutes | Proceed with JSON Forms for all editing.                                                      |
| 2 of 3                                                 | Fix what blocked the third, retest with two new people.                                       |
| 1 or 0 of 3                                            | Build the scientist form by hand for `CoreDiscovery`; keep JSON Forms for data managers only. |

"Valid" means the saved record passes the full `CoreDiscovery` schema and raises no SHACL violation.

### In and out of scope

- **In:** ORCID sign-in, DOI pre-fill, ORCID and ROR pickers, the five-tab `CoreDiscovery` form, autosaved drafts, server validation, the validation report, submit.
- **Out:** search, harvesting, overlays, groups, curator review, other profiles, the DDE layout, the map control (the spike uses four number fields for a bounding box), the vocabulary picker (keywords are free text).

### Starting materials

- **Form assets:** `build/jsonforms/profiles/CoreDiscovery/` in the building blocks repository: `schema.json` (110 KB), `uischema.json` with five tabs (Basic Info, Attribution, Access & Distribution, Coverage & Quality, Metadata Record), and `defaults.json`. Copied in at a pinned commit, because automation regenerates them.
- **Validation:** the `CoreDiscovery` resolved schema, and the SHACL bundle emitted by `validate_shacl.py CoreDiscovery --emit-shapes`.
- **Error wording:** `explain_error` in `FrameAndValidate`, which already turns either-or schema failures into the specific property at fault.

### Stack

- **Web:** React with Vite, `@jsonforms/react` and the Material renderers.
- **Server:** FastAPI, `jsonschema`, `pyshacl`.
- **Database:** PostgreSQL, two tables: drafts (owner, profile, document, status, last validation result) and saved versions.
- **Run:** one Docker Compose file for all three.

### Day by day

| Day | Work                                                                                                                                                                       | Done when                                                                                               |
|-----|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|
| 1   | New repository, Compose file, form assets copied in, empty pipeline in CI.                                                                                                 | All three services start with one command.                                                              |
| 2   | Render the form with stock renderers. List every field that renders badly.                                                                                                 | A written inventory. The form schema has 45 either-or choices; this shows how many matter.              |
| 3   | Save and load drafts, autosave, ORCID sign-in against the ORCID sandbox.                                                                                                   | A signed-in user reloads the page and their draft is there.                                             |
| 4–5 | Custom controls: person and organisation picker with ORCID and ROR lookup; identifier field; hide fields the author should never see (type markers, context, conformance). | Adding an author takes a search and a click, and writes a valid node.                                   |
| 6   | DOI pre-fill from DataCite, with Crossref as fallback: title, creators, publisher, dates, description, licence, keywords.                                                  | Pasting a DOI fills the first two tabs.                                                                 |
| 7   | Validation endpoint: full schema plus SHACL. The server adds the catalog record entry and conformance declaration itself.                                                  | The repository's own `CoreDiscovery` examples pass; its failing test cases fail for their named reason. |
| 8   | Report in the form: violations block submit, advisories suggest, each links to its field. Completeness indicator.                                                          | Every finding points at a field on a tab, in plain words.                                               |
| 9   | Dry run: re-enter five existing example records by hand. Fix what breaks.                                                                                                  | All five submit valid.                                                                                  |
| 10  | Three scientist sessions of 30 minutes, thinking aloud. Write up.                                                                                                          | A one-page result against the pass and fail table.                                                      |

### Early stop

If the day 2 inventory shows the stock form is unusable in ways the planned custom controls do not address, or the person and organisation picker is not working by the end of day 5, stop and decide on the hand-built form then. Do not wait for day 10.

### Needed before day 1

- An ORCID sandbox API client registered, for sign-in and author search.
- Three scientists booked for day 10, none of whom has seen CDIF.
- A web address with HTTPS for the test sessions, which ORCID sign-in requires outside a developer's own machine.
- Done: this repository, public, in the Cross-Domain-Interoperability-Framework organisation.

### Known traps

- **The form schema drops `contains` constraints.** The form passing proves nothing; only the day 7 endpoint decides validity.
- **Conformance addresses are moving from version 1.1 to 2.0.** Read them from the schema; do not write them into the spike's code.
- **`defaults.json` is the only source of a new record's conformance declaration and nothing checks it.** The server stamps the declaration instead of trusting it.
- **The `schema` prefix must be `http://schema.org/`.** A lookup that writes the `https` form produces a record that validates as empty.

### What comes out

- A running demonstration.
- The day 2 inventory of form problems, reusable for every later profile.
- Session notes and a one-page go or no-go.
- The validation endpoint and report, which carry over unchanged to the full build.

## Open questions

- Which DCAT-AP and GeoDCAT-AP versions should the feed target? Built against 3.0.0 of both; GeoDCAT-AP 3.1.0 also exists.
- Which identity provider: ORCID alone, or ORCID plus an institutional login for staff?
- Where do the SKOS vocabularies live once GeoNetwork is retired?

## Basis and limits

Findings about the two deployments come from reading `usgin/geonetwork-DDE` (branch `DDEconfig`) and the local Geoportal deployment on 16 November 2026. Facts about upstream projects come from their public repositories on the same date. Not verified: Geoportal's user interface framework, whether Geoportal supports OGC API Records, and the internals of the Geoportal application archive.
