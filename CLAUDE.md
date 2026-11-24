# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Read first

- `README.md` lists every file and the API. `docs/design.md` is the authoritative design,
  including the prototype's build plan (the table of days 1 to 10) and its pass and fail criteria.
- `docs/form-inventory.md` records what is wrong with the stock generated form.

This file covers only the commands and the traps.

## Where the project is

An early prototype. Built: the `CoreDiscovery` submission form (draft saving, ORCID/ROR pickers,
DOI pre-fill, server validation with a report, submit, plain-language wording); harvesting from
web folders, sitemaps and CSW catalogues with a worker; the DCAT catalog feed; record addresses with content negotiation; and
label-based access; and sign-in with ORCID, with an admin-only harvest API; and drafts owned by
the signed-in user; a landing page, a list of records with a plain word search, and a harvest
page for admins (`web/src/pages.jsx`). The dry run (plan day 9) was done by script; its findings are in
`docs/form-inventory.md`. Not built: the scientist sessions (plan day 10),
the other harvesters (OAI-PMH, CKAN, STAC, DCAT, file upload), mappings into CDIF, publishing
of submitted records, search, serving CSW, OGC API Records and a sitemap of the catalog's own records. Do not start those without being asked.

## Commands

Everything runs in Docker. There is no local Python or Node setup to rely on.

```bash
git submodule update --init --recursive   # once after cloning: fetches server/converters and the validation repository inside it
docker compose up --build            # db, api (8000), worker, web (5173); open http://127.0.0.1:5173
docker compose exec api pytest       # server tests; they need the database, so run them here
docker compose up -d --build api worker   # after changing server/requirements*.txt
docker compose up -d --build web     # after changing web/vite.config.js or package.json
cd web && npm run build              # the only front-end check there is
```

`server/app`, `server/tests`, `web/src` and `web/public` are mounted into the containers, so edits
show without a rebuild. A new Python dependency needs the image rebuilt.

## Conventions

- **Work on a branch and open a pull request.** `main` only moves by merge. CI builds the web app
  and runs the server tests.
- **Stage explicit paths.** Never commit `.env`.
- **The browser calls only this server.** Calls to ROR, ORCID, DataCite and Crossref, and the
  mapping of their answers to CDIF, live in `server/app/lookup.py`.
- **Only the server decides validity.** The form's own checks are not shown and not trusted.
- **Code taken from CKAN is reimplemented, never copied.** CKAN and its extensions are AGPL; this
  project is Apache-2.0. `docs/design.md` lists the practices adopted.
- **Every read of `records` for an outside reader goes through `store.visible_records` or
  `store.visible_record`**, which apply the label filter. Change a record's status with
  `store.set_status`, which recomputes its labels.
- **Text a user reads is plain language**: no schema terms, no jargon. British spelling in the
  interface ("organisation", "licence").
- **Tests that need something fail without it; they do not skip.** A skipped test reads the same
  as a passing one.

## Traps

- **`server/converters` is a git submodule and is not edited here.** A converter's defect is an
  issue for the `converters` repository. To move to a newer commit: `git -C server/converters
  fetch && git -C server/converters checkout <commit>`, run the tests, then commit the submodule
  pointer, and change `CONVERTERS_COMMIT` in `deploy/Dockerfile` to the same commit (Render does
  not fetch submodules, so that image fetches the converters itself; CI fails if the two differ). `test_converters.py` runs the real converters on their own examples and fails if the
  submodule is missing or a converter's call signature has changed.
- **A converted record's conformance claim comes from `detect_conformance.py`**, in the
  converters' nested `validation` submodule, which must be fetched (`--recursive`). The
  catalog calls it once after converting (`convert.claim`); the converters are still called
  with `detect=False`. Which profiles it looks for is set in
  `server/app/profile-sources.yaml`: groups by building block repository, CDIF on, DDE and
  geochem off. Each group's folder under `server/app/conformance/` holds a `conformance.json`
  per profile and the rule files those name, so nothing is fetched from GitHub; a test fails
  if a named rule file is missing. The list is read once: restart `api` and `worker` after
  changing it. Several of those files are drafts not yet in their home repositories, and the
  geochem group declares nothing until its files require the 2.0 levels
  (`server/app/conformance/PINNED.md`). A CDIF record that was harvested as CDIF keeps exactly
  what it declared.
- **The validation repository has tests of its own**, which need files the catalog does not
  hold. `server/pytest.ini` limits collection to `tests`; it is baked into the image, so a
  change to it needs the image rebuilt.
- **The converters are scripts, not a package.** `converters.py` loads each from its file and
  puts its folder on the import path. New Python dependencies of a converter go in
  `server/requirements.txt` (today: `lxml`, `pyld`, `requests`).
- **Some converters are slow or return shapes the catalog cannot take.** A converter that returns
  an `@graph` of nodes is reported, not stored. It is decided that framing is the converter's
  job: do not add a framing step to the catalog. The DDI converters frame when asked
  (`framed=True` in `converters.py`). A large FAIR2 record took over a minute to convert and
  check, and a large DDI record about as long to check.
- **Files copied from elsewhere are not edited here.** From metadataBuildingBlocks:
  `web/public/forms/CoreDiscovery/*`, `server/app/profiles/{CoreDiscovery,cdifCore}/*` and
  `server/tests/fixtures/{CoreDiscovery,cdifCore}/*`. From SEMIC: `server/tests/fixtures/shapes/*`. Each has a `PINNED.md` naming the commit and the refresh
  steps. Refresh the form files and the validation files together, or the form and the validator
  disagree. A defect in them is an issue for metadataBuildingBlocks, not a local patch. Where a
  defect in the form files stops a person entering something, a correction is laid over them
  when the form loads (`web/src/corrections.js`); delete each one when a refresh brings the fix.
- **Do not write a conformance address or its version in code.** `validate.load` reads them from
  the pinned schema (or, for a single level such as `cdifCore`, the `conformance.json` beside
  it), and a test fails if `/2.0` appears in `validate.py`. They moved from 1.1 to 2.0 once already.
- **A form record claims the level its content reaches** (`validate.level_for`): the installed
  profile with the fewest claims that has every field the record fills. Do not list the fields
  that raise the level in code; they are the difference between the pinned schemas. Each
  installed profile needs its own `server/app/messages/<profile>.json`. Converted records are
  levelled by `detect_conformance.py` instead; the two agree on core and discovery today.
- **The `schema` prefix is `http://schema.org/`, not `https`.** With the `https` form a record
  reads as empty to the SHACL rules and reports nothing. `prepare` overwrites the prefixes with
  the ones the schema pins.
- **The form's document is not a record.** The form holds `@type` as one word where the schema
  wants a list, leaves `""` and `[]` in untouched fields, and has no field for the record's `@id`
  or its catalog record. `validate.prepare` bridges all of that. Test validation with documents
  shaped like the form's (`server/tests/fixtures/form-defaults.json`), not only with clean records.
- **The form schema drops `contains` constraints**, so a form reporting no problems proves nothing.
- **A unit test that asserts your own string proves nothing about the live service.** The ORCID
  search field is `family-name`; `family-names` (a result field) makes ORCID answer 500, and a
  test asserting the wrong one passed. After changing a registry query, call the live endpoint.
- **The schema and the SHACL rules report the same problem twice, and SHACL results carry no list
  positions.** `validate._merge` keeps one finding per problem; `_field_named_in` guesses a field
  from a rule's wording when the rule names none. Both are heuristics: when the pinned files are
  refreshed, print the report for a blank and a filled form and read it.
- **Three files must follow the pinned files.** `server/app/messages/CoreDiscovery.json` needs an
  entry for every rule message, and `server/app/mappings/cdif-to-dcat.tsv` a row for every profile
  property; a test fails for each when they fall behind. `web/src/wording/CoreDiscovery.json`
  needs an entry for every control in the layout, which nothing tests, so compare the two by hand
  after a refresh.
- **The SEMIC shapes do no inference.** A value's class must be stated outright
  (`dcat:Resource`, `foaf:Agent`, `rdfs:Resource` on an access address) or the shape rejects it.
- **rdflib's `DCAT` namespace predates DCAT 3** and warns on `dcat:version`. Build such terms as
  a `URIRef`.
- **Turtle output is not stable text.** Blank nodes come out in a different order each time;
  compare graphs, not strings.
- **The web folder harvester does not parse listing layouts.** It takes the links from the page
  and asks each file for its `Last-Modified` date with a HEAD request, the way Esri's Geoportal
  harvester does. Do not bring back per-server listing parsers. A server that sends no
  `Last-Modified` leaves its files undated; they are then fetched each run and recognised by
  content hash.
- **A harvested file's format comes from `detect.py`, never from its name or media type.** When
  adding a format, add it to `FORMATS`, add a snippet to `test_detect.py`, and run the detector
  over the real examples in the `converters` repository (a checkout beside this one), which is
  how its rules were tuned. Recognising a format and converting it are separate:
  `converters.CONNECTED` holds what is connected.
- **A CDIF record is validated against the profile its own catalog record declares**
  (`validate.profile_for`), not against a setting. The source's `profile` setting is only the
  fallback for a record that declares nothing we hold a profile for.
- **The sitemap harvester takes a page's metadata from its embedded JSON-LD** (`sitemap.embedded_metadata`):
  the block typed as a dataset, where a page holds several. It does not read a page's other markup.
  A sitemap is the whole list, so a page no longer listed is withdrawn, as with a folder.
- **The CSW harvester asks with GET and plain parameters, never a POST body** (`robots.Polite`
  offers only `get` and `head`). It lists with `GetRecords` in the summary form, for each
  identifier and `dct:modified`, then asks for each record with `GetRecordById` and hands on the
  record without its wrapper. It always asks for the whole list; it sends no date filter.
- **A list cut short by a source's `limit` is not complete** (`Gathered.complete` is false), so
  nothing is withdrawn on its word. This holds for the sitemap and CSW harvesters.
- **`robots.txt` is obeyed by wrapping the HTTP client (`robots.Polite`), so a harvester must use
  the client it is given** and not open its own. A closed address raises `Disallowed`; a
  harvester walking a source catches it and skips that address. Only a closed starting point
  should fail the run.
- **Records missing from a source are withdrawn at the end of a run, and only if no fetch
  failed in it.** A retry run never withdraws and never counts as the last clean run.
- **Git Bash rewrites `/srv/...` arguments into Windows paths.** Prefix a `docker compose exec`
  that passes a container path with `MSYS_NO_PATHCONV=1`.
- **`web/vite.config.js` is baked into the web image**, not mounted. A proxy change needs the
  image rebuilt.
- **JSON Forms gives no way to switch tabs from outside.** `Report.jsx` clicks the tab element.
  The stock date field is segmented and ignores text typed by browser automation; set dates
  through the API when testing in a browser.
- **A nested-button warning in the browser console comes from the JSON Forms library**, not from
  this code. It is recorded in `docs/form-inventory.md`.
- **Windows.** Vite in Docker needs polling to see edits (`WATCH_POLL` in `docker-compose.yml`).
  Read and write files as UTF-8 explicitly; the platform default is cp1252. Shell heredocs
  containing apostrophes fail to parse here: write the file with a tool or a script.
- **Switching git branches changes the code under the running containers**, because of the mounts.
- **The sign-in tests stand in for ORCID.** They replace `auth.exchange_code`, so they prove the
  catalog's half of the round trip only. The real exchange worked against the ORCID sandbox on
  19 November 2026 (scope `/authenticate`; `orcid` and `name` read from the answer). After
  changing `auth.py`, sign in once for real.
- **A route that changes anything needs `Depends(auth.require(<permission>))`.** The harvest
  router applies it to every route at once. A test that needs a signed-in user overrides
  `auth.current_user` (see `as_admin` in `test_harvest.py`).
- **`ADMIN_ORCIDS` only ever adds the admins group, at sign-in.** Removing an iD from the setting
  does not demote anyone; that is an edit to `users.groups` in the database.
- **ORCID refuses a return address containing `localhost`.** `PUBLIC_URL` therefore defaults to
  `http://127.0.0.1:5173`, and the page's sign-in link always points there (`sign_in_url` from
  `/api/auth/me`). Do not compare the request's `Host` header with `PUBLIC_URL` on the server:
  the Vite proxy rewrites it to `api:8000`, and a redirect built on that comparison loops. A draft started under one name is not found under the other, because the browser keeps
  each name's storage apart.
- **A draft belongs to whoever was signed in when it was saved** (`drafts.owner`, the user's id).
  Every draft query carries the `MINE` condition in `main.py`, which answers 404 to anyone else;
  a new draft route must carry it too. A draft started signed out has no owner, is open to anyone
  with its id, and is claimed by the first signed-in save.
