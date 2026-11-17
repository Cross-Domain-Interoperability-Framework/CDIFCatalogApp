# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Read first

- `README.md` lists every file and the API. `docs/design.md` is the authoritative design,
  including the prototype's build plan (the table of days 1 to 10) and its pass and fail criteria.
- `docs/form-inventory.md` records what is wrong with the stock generated form.

This file covers only the commands and the traps.

## Where the project is

An early prototype of the record submission form for the CDIF `CoreDiscovery` profile. Built: the
form, draft saving, ORCID/ROR pickers, DOI pre-fill, server validation with a report, and submit.
Not built: sign-in, the dry run and scientist sessions (plan days 9 and 10), and everything in the
wider design (harvest, search, outbound interfaces). Do not start those without being asked.

## Commands

Everything runs in Docker. There is no local Python or Node setup to rely on.

```bash
docker compose up --build            # db, api (8000), web (5173); open http://localhost:5173
docker compose exec api pytest       # server tests; they need the database, so run them here
docker compose up -d --build api     # after changing server/requirements*.txt
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
- **Text a user reads is plain language**: no schema terms, no jargon. British spelling in the
  interface ("organisation", "licence").
- **Tests that need something fail without it; they do not skip.** A skipped test reads the same
  as a passing one.

## Traps

- **Files copied from metadataBuildingBlocks are not edited here.** That is
  `web/public/forms/CoreDiscovery/*`, `server/app/profiles/CoreDiscovery/*` and
  `server/tests/fixtures/CoreDiscovery/*`. Each has a `PINNED.md` naming the commit and the refresh
  steps. Refresh the form files and the validation files together, or the form and the validator
  disagree. A defect in them is an issue for metadataBuildingBlocks, not a local patch.
- **Do not write a conformance address or its version in code.** `validate.load` reads them from
  the pinned schema, and a test fails if `/2.0` appears in `validate.py`. They moved from 1.1 to
  2.0 once already.
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
- **JSON Forms gives no way to switch tabs from outside.** `Report.jsx` clicks the tab element.
  The stock date field is segmented and ignores text typed by browser automation; set dates
  through the API when testing in a browser.
- **A nested-button warning in the browser console comes from the JSON Forms library**, not from
  this code. It is recorded in `docs/form-inventory.md`.
- **Windows.** Vite in Docker needs polling to see edits (`WATCH_POLL` in `docker-compose.yml`).
  Read and write files as UTF-8 explicitly; the platform default is cp1252. Shell heredocs
  containing apostrophes fail to parse here: write the file with a tool or a script.
- **Switching git branches changes the code under the running containers**, because of the mounts.
- **Drafts have no owner yet.** Anyone with a draft's id can read and change it. Acceptable only
  on a developer machine; sign-in is the next server step and needs the ORCID sandbox client from
  `docs/setup-sandboxes.md`.
