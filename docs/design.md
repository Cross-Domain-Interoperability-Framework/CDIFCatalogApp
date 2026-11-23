# CDIF Catalog Design

Proposal to replace the GeoNetwork and Geoportal deployments · 16 November 2026 · Draft for discussion · What is built was last reviewed on 23 November 2026; see [Where the build stands](#where-the-build-stands)

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

**The mapping layer was built differently from the table.** No XSLT is run. Every connected format, XML included, is converted by a Python script from the CDIF `converters` repository (see [How harvests are stored](#how-harvests-are-stored)); the ISO converter reads the XML with `lxml`. `saxonche` is not installed. The XSLT route remains the plan for ISO output, which is not built.

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

Built so far: the drafts table, and the `records` table with the layout above. Harvested records fill it; publishing a submitted draft into it is not built. The overlay column is always empty, the status "conflict" is never set, and no search row or ISO output is derived. A draft has no owner: anyone holding its id can read and change it, signed in or not.

> **Decided:** a submitted draft is not published. It stays out of the catalog feed and has no record address until the review step exists and a curator approves it.

### How harvests are stored

The model is the one ckanext-harvest uses, reimplemented.

| Table | One row is | Holds |
|---|---|---|
| `harvest_sources` | A registered source | Address, type, settings, owning organisation, how often it runs and when it runs next. |
| `harvest_jobs` | One run of a source | Its state (new, running, finished, aborted) and when each stage started and ended. |
| `harvest_objects` | One source record seen in one run | The record's identifier at the source, the source's modified date, and how it ended: added, updated, not modified, deleted or errored. |
| `harvest_errors` | One failure | The run, the record if there was one, the stage (gather, fetch, import or job) and the message. |

- **Three stages.** Gather (list what the source holds), fetch (get one record as sent) and import. Each kind of source provides the first two. Import is shared: recognise the format from the content, convert it to CDIF, validate, store.
- **Format is recognised from content.** File names and media types are not trusted. A CDIF JSON-LD record is recognised by the conformance addresses in its catalog record (`schema:subjectOf`, `dcterms:conformsTo`), and those addresses choose the profile it is validated against. An RO-Crate is asked for first, because a crate made from a CDIF record keeps that record's conformance addresses. Also recognised: schema.org, DCAT, Croissant, FAIR2, RO-Crate and DDI-CDI JSON-LD; UMM, STAC, DataCite, CKAN, DCAT-US and NIAID JSON; ISO 19139, 19115-2 and 19115-3, CSW responses, FGDC, ArcGIS, EML, DataCite, Dublin Core, DDI 1.2.2, DDI Codebook 2.5, DDI Lifecycle, DDI-CDI, SDMX-ML, OGC capabilities and DCAT RDF/XML; DCAT and schema.org Turtle.
- **Recognising is not converting.** A record in a format with no connected converter is stored as received, and the run reports the format and any converter that exists for it. Once a converter is connected, a retry of the failed records converts them.
- **Converters come from the CDIF `converters` repository**, a git submodule pinned to a commit. A converted record is given a conformance declaration by the catalog, worked out from its content by `detect_conformance.py` (in the converters' own `validation` submodule), then checked; it is published only if it passes. The table below is what each connected converter did on up to three of its own example files on 23 November 2026, with the converters at `8c02b14`, each record checked against the profile it reaches (core or discovery).

| Format | Converter | On its examples, against the pinned profile the record reaches |
|---|---|---|
| ISO 19139, ISO 19115-2, ISO 19115-3, and a CSW response holding one record | `ISO19115/iso_to_cdif.py` | Valid (3 of 3 each; no example of a CSW response was among the files tried). |
| DDI-CDI XML | `DDI-CDI/ddicdi_to_cdif.py` | Valid (2 of 2): one reaches discovery, one core only. |
| schema.org JSON-LD | `soso/ConvertFromSOSO.py` | Converts; not valid (3 of 3): downloads with no address, a citation address that is not a web address, and a place with no type. One other example, not among the three, was harvested and published. |
| Croissant | `croissant/ConvertFromCroissant.py` | Converts; not valid (3 of 3): a creator's `@type` written as one word where the profile wants a list. |
| RO-Crate | `ROCrate/ROCrateToCDIF.py` | Valid (1 of 3). The other two: file size written as a number where the profile wants text, a licence address that is not a web address, and no identifier. The XAS example crate, not among the three, is valid since the converter's list handling was corrected (converters pull request 48). |
| NASA UMM-C | `UMM/umm_to_cdif.py` | Converts; not valid (3 of 3): distributions with neither a download address nor parts. The rule messages for these have no plain wording yet. |
| DDI-CDI JSON-LD | `DDI-CDI/ddicdi_jsonld_to_cdif.py` | Converts; not valid (3 of 3): a distribution name that is not text. |
| FAIR2 | `FAIR2/fair2_to_cdif.py` | Converts; not valid (1 of 1): alternate names of variables not written as a list, checksums with no algorithm, a funder given as text. Took 91 seconds. |
| DDI 1.2.2, DDI Codebook 2.5 | `DDI/ddi_sssom_to_cdif.py` | Valid (6 of 6): one nested record each, asked for with `framed=True`. Converting takes about a second; checking a large record (hundreds of variables and code lists) takes from 20 seconds to several minutes. The six took 8 minutes in all. |
| DCAT (JSON-LD, RDF/XML, Turtle), SDMX-ML | exist | Not connected: each takes one dataset or dataflow picked out of a larger document. |
| DataCite XML (kernel 3 and 4), one record per file | `DataCite/datacite_to_cdif.py` | Valid (50 of 50) against the profile each reaches: 12 reach discovery, 38 core only. A record inside an OAI-PMH response is not connected. |
| EML, FGDC, Dublin Core, OGC service capabilities, STAC | exist since the converters moved to `8c02b14` | Not connected, and not tried here. The detector still reports them as having no converter. |
| ArcGIS, DataCite JSON, DDI Lifecycle, CKAN, DCAT-US, NIAID | none connected | Recognised and kept as received. NIAID has a harvester script, not a converter function. |

The "not valid" rows are for the `converters` and `metadataBuildingBlocks` repositories to settle: either the converter's output or the profile the catalog pins is behind the other. They are not patched here.
- **`robots.txt` is obeyed**, including its crawl delay, unless a source's settings say to ignore it. A closed subfolder or file is skipped; a closed starting point fails the run.
- **Failed records can be retried alone.** A retry run fetches and imports again only the records that ended in an error in an earlier run.
- **Changed since, only after a clean run.** A source is asked for changes since the last run that finished with no errors. After a run with errors the next asks for everything, so a failure cannot hide a record for good.
- **Deletion needs a complete listing and a trouble-free run.** A record missing from a full listing is withdrawn, at the end of the run and only if every listed record could be fetched. A "changed since" listing says nothing about what it leaves out, and a source that is failing requests cannot be trusted about what it lists.
- **Invalid records are stored, not published.** The text as received is kept, the problem is an error row, and the record is not served.
- **The queue is the job table.** A worker claims a waiting job with a row lock that other workers skip. There is no message broker.
- **A corrected converter does not reach records already harvested.** A file whose content has not changed is skipped, so a record converted wrongly stays as it was. A retry run converts again the records that failed, which is how a record that was invalid under the old converter gets through (done by hand for one record on 23 November 2026). A record that passed but was converted poorly is not looked at again. Converting every affected record again from its stored text, the reason that text is kept, is not built.
- **Not built:** email to an organisation's admins when a run fails. Users can now sign in, but ORCID sign-in gives the catalog a name and an iD, not an email address, and no user belongs to an organisation yet.
- **Not built:** any page for harvesting. Sources are registered and runs started through the API, by a signed-in admin.

> **Decided:** if a source changes a published record into an invalid one, the record stops being served until it is fixed. The earlier valid version is not kept on show.

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

> **Decided:** DCAT output targets DCAT-AP 3.0.0 and GeoDCAT-AP 3.0.0 for now. GeoDCAT-AP 3.1.0 exists, but how widely it is adopted is not known.

## Groups and permissions

A fixed set of named permissions assigned to groups. A user can belong to more than one group. Sign-in is through an external identity provider; the catalog stores no passwords.

| Group         | Permissions                                                                                                                     |
|---------------|---------------------------------------------------------------------------------------------------------------------------------|
| Submitters    | Create and edit their own records; submit them for review.                                                                      |
| Data managers | Everything submitters can do, plus: register and run harvest sources, **edit harvested records**, resolve re-harvest conflicts. |
| Curators      | Review and publish submissions.                                                                                                 |
| Admins        | Manage groups, membership and all sources.                                                                                      |

Harvest-edit is its own named permission, so it can be granted to another group later without a code change.

> **Decided:** a web folder source picks up files ending in `.json`, `.jsonld`, `.xml`, `.ttl` and `.rdf` unless its settings list others. What each file is comes from its content, not its ending.

> **Decided:** framing happens in the converter. A converter hands the catalog one nested record per dataset, not a graph of separate nodes. The catalog does not frame; a converter that returns a graph is reported and its record is not stored as CDIF. The DDI 1.2.2 and DDI Codebook 2.5 converters used to; they now return one nested record when called with `framed=True` ([converters issue 38](https://github.com/Cross-Domain-Interoperability-Framework/converters/issues/38)).

> **Decided:** the converters are brought in as a git submodule for now. For production they should become an installed package; `server/app/harvest/converters.py` is the only module that would change.

> **Decided:** to start, only admins can harvest. Registering sources and running them is one named permission, `harvest`, held by the admins group alone. Data managers get it when harvest sources are scoped to organisations.

Built so far: sign-in with ORCID, a users table holding each user's groups and organisations, and the admins group. The first admins are named by ORCID iD in a server setting, so no admin is needed to appoint them. The other three groups, and any screen for managing membership, are not built.

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
- **The declaration follows the content.** A record claims the core level until it fills a field that a fuller level adds. Variables, measurement technique, place, time and quality measurements add the discovery claim. For a form record this is built for core and discovery only. A converted record's claim is worked out by `detect_conformance.py` from the CDIF validation repository, which covers all six levels and holds a claim to that level's content rules; the catalog holds profiles to check only core and discovery against, so a deeper claim rests on that script alone. Which profiles are looked for is a list in `server/app/profile-sources.yaml`, grouped by the building block repository that defines them: the CDIF profiles by default, with the DDE and geochemistry profiles as groups that can be switched on. The profiles in a group are whatever `conformance.json` files its folder holds. Still to do: choosing the groups per harvest source or per user, not once for the whole catalog. Still to do: details of variables (physical mapping, the structure of a distribution's data) adding the data description or data structure claim, and the same for provenance and manifest properties. Those need their levels pinned and form fields that do not exist yet.
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

### Where the build stands

As of 23 November 2026. The work did not follow the order above: the spike was built as far as day 8, then parts of steps 2, 3, 5 and 6 were built ahead of the scientist sessions. Everything below runs on a developer's machine and, as a prototype, on a free Render service.

| Step | Stands at | Built | Not built |
|---|---|---|---|
| 1. Spike | Days 1 to 8 built, with two gaps. Day 10 not started, so the spike's question is unanswered. | See the day-by-day table. | The scientist sessions, and the go or no-go. |
| 2. Pipeline and store | Partly built. | The `records` and harvest tables; a worker; web folder harvesting; recognising a format from content; 14 formats connected to converters; conformance worked out from content; validation, with invalid records stored but not served. | The other connectors (sitemap, CSW, OAI-PMH, CKAN, STAC, DCAT, file upload). The 121 ADA records have not been reproduced. Re-converting stored records after a converter is corrected. |
| 3. Search and record pages | A small part. | A record address that answers by `Accept` header or `format` parameter, with a plain summary page. | Search of any kind, the search row, the search page, the designed record page, the sitemap, OGC API Records. |
| 4. ISO output and CSW | Not started. | | All of it. |
| 5. DCAT mapping and feed | Built as a first version. | The CDIF-to-DCAT mapping table; the feed in Turtle, JSON-LD and RDF/XML with paging and `modified_since`; output tested against the SEMIC shapes. | A run by a real DCAT harvester. Submitted records in the feed. |
| 6. Harvest registration, overlays, conflicts | A small part. | Registering a source and starting, retrying and reading a run through the API, for admins only; sign-in with ORCID; labels on records and users. | Any harvest page; a test harvest that publishes nothing; file upload and API tokens; overlay editing; conflict handling; the submitter, data manager and curator groups; organisations for users. |
| 7. DDE layout and controls | Wording only. | Plain-language labels, help and rule messages for `CoreDiscovery`. | The DDE layout, the vocabulary picker, the map control, the geologic age fields. |
| 8. Retire GeoNetwork | Not started. | | |

Not in the order of work, and built: looking for profiles by groups listed in `server/app/profile-sources.yaml`, with DDE and geochemistry groups that can be switched on; a user guide (`docs/user-guide.md`).

Nothing built stands between here and the scientist sessions: drafts are tied to the signed-in user, the prototype runs at a web address with HTTPS (`docs/deploy-render.md`), and the dry run of day 9 is done. The dry run was by script, so a pass through the form by a person who knows it is still worth making first; its findings are in `docs/form-inventory.md`.

## To do: practices taken from CKAN

CKAN is not the base for this catalog (see Alternatives considered), but a review of `ckan`, `ckanext-dcat`, `ckanext-spatial`, `ckanext-harvest` and `ckanext-scheming` on 18 and 19 November 2026 found practices worth adopting. All but `ckanext-scheming` are AGPL, so each item below is reimplemented here, not copied.

All six were built on 19 November 2026, each as a first version. What each still lacks is in the last column.

Esri's Geoportal harvester (Apache-2.0) was reviewed the same day. Its web folder approach replaced CKAN's here. Four more of its practices were then built: obeying a site's `robots.txt` and crawl delay, a retry of only the records that failed in a run, no withdrawal of missing records in a run that had fetch failures, and recognising a metadata format from its content instead of its file extension.

| To do | Detail | Belongs to step | Built, and what is missing |
|---|---|---|---|
| **Test DCAT output against the official shapes** | Serialise records as DCAT-AP and GeoDCAT-AP, then run pyshacl against the SHACL shapes published by SEMIC. Fetch the shapes from SEMIC and pin them, as the CDIF schema and rules are pinned. | 5 | Built for DCAT-AP 3.0.0 and GeoDCAT-AP 3.0.0, on the three example records. |
| **DCAT catalog feed with the interface CKAN uses** | `/catalog.{ttl,jsonld,xml}` with `page`, `modified_since` and `profiles=` parameters, and Hydra paging triples (`hydra:PagedCollection` with first, next, last and total). Existing DCAT harvesters, CKAN's included, already walk this. | 5 | Built. Not yet walked by a real CKAN harvester. Lists harvested records only. |
| **Record address answers by `Accept` header** | The record address serves HTML, CDIF JSON-LD, DCAT JSON-LD or DCAT Turtle according to the request's `Accept` header, and the HTML page advertises the others with `<link rel="alternate">`. | 3 and 5 | Built. The web page is a plain summary, not the designed record page. |
| **Web folder harvesting** | CKAN parses Apache, nginx and IIS listings separately, chosen by the `Server` header, and reads dates from the listing. | 2 | Built that way first, then replaced on the same day with the approach of Esri's Geoportal harvester: read only the links from the listing, and ask each file for its own `Last-Modified` date. It needs no per-server code and works where a listing shows no dates. Checked live against nginx and Apache, for folders of CDIF JSON-LD. |
| **Organisation-scoped access by labels** | Each record carries labels (`public`, `member-<organisation>`, `creator-<user>`), each user carries labels, and search and edit checks filter on the overlap. This is how the data managers' organisation-scoped harvest-edit permission is built. | 3 and 6 | Labels and the checks are built and the feed uses them. Users can sign in, but none is yet given an organisation, so only `public` records are seen. |
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

Where each day stands on 23 November 2026:

| Day | Stands at |
|---|---|
| 1 | Done. |
| 2 | Done: `docs/form-inventory.md`. |
| 3 | Done, but for one part. A draft saved while signed in belongs to that person, who is listed their drafts in any browser; nobody else can open it. A draft started signed out has no owner until a signed-in save. There is no table of saved versions. |
| 4–5 | Done. |
| 6 | Done. |
| 7 | Done. |
| 8 | Report done. The completeness indicator is not built. |
| 9 | Done on 23 November 2026, by script and not by hand: all five example records submit valid. What could not be entered, and what a person would trip on, is in `docs/form-inventory.md`. |
| 10 | Not held. How to run the sessions, with the task sheet, the observation sheet and the result page, is in `docs/scientist-sessions.md`. |

### Early stop

If the day 2 inventory shows the stock form is unusable in ways the planned custom controls do not address, or the person and organisation picker is not working by the end of day 5, stop and decide on the hand-built form then. Do not wait for day 10.

### Needed before day 1

- Done: an ORCID sandbox API client registered, for sign-in and author search. Sign-in worked against the sandbox on 19 November 2026.
- Three scientists booked for day 10, none of whom has seen CDIF. Not recorded as done. Each also needs a sandbox ORCID account made for them beforehand (`docs/scientist-sessions.md`).
- Done: a web address with HTTPS for the test sessions, which ORCID sign-in requires outside a developer's own machine. The prototype is deployed on a free Render service (`docs/deploy-render.md`), where sign-in with the ORCID sandbox worked on 23 November 2026.
- Done: this repository, public, in the Cross-Domain-Interoperability-Framework organisation.

### Known traps

- **The form schema drops `contains` constraints.** The form passing proves nothing; only the day 7 endpoint decides validity.
- **Conformance addresses are moving from version 1.1 to 2.0.** Read them from the schema; do not write them into the spike's code. (They have since moved; the pinned files and the converters declare 2.0, and a test fails if the version is written into `validate.py`.)
- **`defaults.json` is the only source of a new record's conformance declaration and nothing checks it.** The server stamps the declaration instead of trusting it.
- **The `schema` prefix must be `http://schema.org/`.** A lookup that writes the `https` form produces a record that validates as empty.

### What comes out

- A running demonstration.
- The day 2 inventory of form problems, reusable for every later profile.
- Session notes and a one-page go or no-go.
- The validation endpoint and report, which carry over unchanged to the full build.

## Open questions

- Which identity provider: ORCID alone, or ORCID plus an institutional login for staff? ORCID sign-in is built; the institutional login is still undecided.
- Where do the SKOS vocabularies live once GeoNetwork is retired?

## Basis and limits

Findings about the two deployments come from reading `usgin/geonetwork-DDE` (branch `DDEconfig`) and the local Geoportal deployment on 16 November 2026. Facts about upstream projects come from their public repositories on the same date. Not verified: Geoportal's user interface framework, whether Geoportal supports OGC API Records, and the internals of the Geoportal application archive.
