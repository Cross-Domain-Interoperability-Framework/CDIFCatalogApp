# CDIF Catalog: a guide for new users

This guide is for someone who has not used the catalog before. It explains what the catalog is
for, the one idea you need to understand it (profiles that stack), and how to do each thing it
can do today.

The catalog is an early prototype. The last section lists what is not built yet, so you know
what not to look for.

## What the catalog is for

Research data is described in many metadata formats: ISO 19115, DataCite, schema.org, DDI,
RO-Crate and others. Each community has its own, and each catalog tends to speak one.

This catalog is an **aggregator**. It gathers metadata from many kinds of source, turns each
record into one common form, and offers all of it through a single set of addresses. The common
form is CDIF, the Cross-Domain Interoperability Framework: a way of writing metadata as JSON-LD
using schema.org and a few other shared vocabularies.

So whatever format a record arrived in, you read it from the catalog as CDIF, and you can also
ask for it as DCAT, the format other catalogs harvest.

## The one idea: profiles stack

CDIF does not ask every record to say everything. It defines **profiles**, each a set of rules
for one kind of content. A record states which profiles it meets, and it can meet several at
once. Each profile adds to the ones below it.

Everything starts from **core**. A richer record adds more profiles on top:

| Profile | What a record must hold to meet it | Its address |
|---|---|---|
| **Core** | The minimum for any resource: a name, an identifier, the date it was last changed, a licence or access conditions, somewhere to get it, and a description of the metadata record itself. | `https://w3id.org/cdif/core/2.0` |
| **Discovery** | What helps someone find it: what was measured and how, the area and the time span it covers, quality measures. | `https://w3id.org/cdif/discovery/2.0` |
| **Data description** | What is inside the files: each variable and its data type, and the character set and size of each file. | `https://w3id.org/cdif/data_description/2.0` |
| **Data structure** | How the data is organised: its dimensions, measures and attributes, described with reusable components. | `https://w3id.org/cdif/data_structure/2.0` |
| **Provenance** | How the data came to be: the activities that produced it, with their instruments, people and dates. This profile is still changing. | `https://w3id.org/cdif/provenance/2.0` |
| **Access** | The terms of access and use, written so that software can act on them. | `https://w3id.org/cdif/access/2.0` |
| **Manifest** | For a package: the parts that make up the dataset and where to fetch each. | `https://w3id.org/cdif/manifest/2.0` |

A community can then stack its own profile on top, for content only it needs. Examples:

- **XAS core** (`https://w3id.org/cdif/xasCore/1.2`) for X-ray absorption spectroscopy: the
  analysis, the x-ray source, the monochromator, the sample.
- **NIAID** (`https://w3id.org/cdif/niaid/1.0`) for records from the NIAID Data Discovery Portal.
- **DDE** profiles for geoscience resources, and **geochemistry** profiles for laboratory
  techniques. These are groups the catalog can be set to look for; see "For the person who runs
  the catalog" below.

A record's claims are a plain list. A well-described spectroscopy dataset might claim core,
discovery, data description, data structure, provenance and XAS core, all at once. A record
converted from a sparse source might claim core alone. Both are in the catalog, and the claims
tell you how much to expect from each.

The profiles are defined in the
[metadataBuildingBlocks](https://github.com/Cross-Domain-Interoperability-Framework/metadataBuildingBlocks)
repository, under `_sources/profiles`. That repository is the authority; this table is a summary.

### What the catalog does with profiles today

- For a record **converted from another format**, the catalog works out the claims itself, from
  what the record holds. It claims every profile the content fits.
- For a record **that arrived as CDIF**, the catalog keeps the claims the record made.
- The catalog then **checks** the record, and publishes it only if it passes. Today it holds the
  full rules for core and discovery only. A claim to any other profile means the record has the
  content that marks that profile, not that every rule of the profile has been checked.

## Getting to the catalog

Open **http://127.0.0.1:5173** in a browser when the catalog is running on your own machine. Use
that exact address, not `localhost`: sign-in does not work from `localhost`.

If someone else runs the catalog for you, use the address they give you in place of
`http://127.0.0.1:5173` throughout this guide.

To run it yourself you need Docker. The steps are in the [README](../README.md#run-it).

You do not need an account to look at records or to fill in the form. You need to sign in, and
to be an administrator, to harvest.

## Looking at what the catalog holds

There is no search page yet. You reach records through the catalog feed and through each
record's own address.

**The feed** lists every published record:

- http://127.0.0.1:5173/catalog.ttl (Turtle)
- http://127.0.0.1:5173/catalog.jsonld (JSON-LD)
- http://127.0.0.1:5173/catalog.xml (RDF/XML)

The feed is written in DCAT, so another catalog can harvest this one from it. It is paged, 100
records to a page; add `?page=2` for the next. Add `?modified_since=2026-11-01` to list only
records changed since a date.

**A record's address** looks like `http://127.0.0.1:5173/records/` followed by a long identifier.
Copy one from the feed, from a line beginning `dcat:record`. Opened in a browser it shows a plain
summary page. To get the record in another form, add one of these to the end of the address:

| Add this | You get |
|---|---|
| `?format=cdif` | The CDIF record, as JSON-LD. This is the record the catalog stores. |
| `?format=dcat-jsonld` | The same record as DCAT, in JSON-LD. |
| `?format=dcat-ttl` | The same record as DCAT, in Turtle. |
| `?format=html` | The summary page. |

Software can ask for the form it wants with an `Accept` header instead.

**To see which profiles a record claims**, open it with `?format=cdif` and find `schema:subjectOf`,
then `dcterms:conformsTo` inside it. That list is the record's claims.

### Opening a record in the form

At the foot of a record's summary page is a link, **Open a copy of this record in the form**. It
opens the form filled in from that record, as a new record of your own. Changing the copy does
not change the record in the catalog; editing a harvested record itself is not built yet.

The form shows less than a record can hold. Where a record says something in a way the form has
no field for, the copy is simplified: a keyword taken from a vocabulary becomes its label, for
example. Parts the form has no fields for at all, such as how the data were structured, are
kept in the copy unchanged but cannot be seen or edited there.

If you already have a record in progress in the same browser, you are asked first, because
opening the copy takes its place.

## Describing a dataset with the form

The page at http://127.0.0.1:5173 is a form for describing one dataset. It follows the core and
discovery profiles.

1. **Start from a DOI, if the dataset has one.** Paste it into the "Start from a DOI" box and
   choose "Fill from DOI". The catalog fills in what the DOI's registry knows: title, authors,
   publisher, dates, description, licence, keywords. It fills only fields that are still empty.
   Check each one; registries are sometimes out of date.
2. **Work through the five tabs**: Basic Info, Attribution, Access & Distribution, Coverage &
   Quality, and Metadata Record. Each field has a line of help under it.
3. **Pick people and organisations from the lists.** Typing a name in an author field searches
   ORCID; typing in a publisher or funder field searches ROR. Picking from the list stores the
   person's or organisation's identifier, not just the name.
4. **You do not need to save.** The record saves as you type, and comes back if you close the
   page and return to it in the same browser.
5. **Choose "Check my record"** under "Check and submit". The catalog lists what it found, in
   three groups:
   - **Must be fixed before you can submit**
   - **Recommended**
   - **Worth considering**

   Each finding links to the field it is about.
6. **Choose "Submit record"** when nothing must be fixed.

Two things to know:

- A submitted record is **not published yet**. It does not appear in the feed. Review and
  publishing of submitted records is not built.
- Your draft is kept under the address you opened the form at, in that browser. It is not tied
  to your sign-in, so you will not find it from another computer.

"Start a new record" clears the form for another dataset.

## Signing in

Choose "Sign in with ORCID" at the top of the page and sign in on ORCID's own page. ORCID sends
you back to the catalog, which then shows your name. The catalog never sees your ORCID password.

Signing in does not change what you can read. It matters for harvesting, which is for
administrators. The person who runs the catalog decides who is an administrator.

If there is no "Sign in with ORCID" link, sign-in has not been set up on that copy of the catalog.

## Harvesting: gathering records from a source

Harvesting is how most records get into the catalog. You point the catalog at a source, and it
fetches each metadata file, turns it into CDIF and checks it.

Today the catalog harvests one kind of source: a **web folder**, which is a web address that
lists metadata files as links. You must be signed in as an administrator.

There are no harvest pages in the web application yet. You use the catalog's interactive
address list at **http://127.0.0.1:8000/docs**, which lets you fill in and send each request
from the browser. Sign in at http://127.0.0.1:5173 first, in the same browser.

### 1. Register the source

Open `POST /api/harvest/sources`, choose "Try it out", and send:

```json
{
  "title": "Example data centre: ISO records",
  "url": "https://data.example.org/metadata/iso/",
  "type": "waf",
  "frequency": "MANUAL"
}
```

- `title` is your name for the source.
- `url` is the folder's address.
- `type` is `waf`, for a web folder.
- `frequency` is how often to harvest on its own: `MANUAL` (only when you ask), `DAILY`,
  `WEEKLY`, `BIWEEKLY` or `MONTHLY`.

The answer includes the source's `id`. Keep it.

By default the catalog picks up files ending in `.json`, `.jsonld`, `.xml`, `.ttl` and `.rdf`,
and follows sub-folders three levels down.

### 2. Start a run

Open `POST /api/harvest/sources/{source_id}/jobs`, give the source's `id`, and send it. The
answer includes the run's `id`. A worker picks the run up within a few seconds.

### 3. Read the result

Open `GET /api/harvest/jobs/{job_id}` with the run's `id`. When its `status` is `finished`, the
`stats` say what happened to each file:

| Count | Meaning |
|---|---|
| `added` | A new record was stored. |
| `updated` | The file had changed, and its record was replaced. |
| `not modified` | The file had not changed since the last run. Nothing was done. |
| `deleted` | The file is gone from the source, so its record was withdrawn. |
| `errored` | Something went wrong with this file. The `errors` list says what, for each one. |

A record that was converted but did not pass the check counts under `errored`. It is still
stored, so you can see what is wrong with it, but it is not published.

If some files failed for a passing reason, such as the source being briefly unreachable,
`POST /api/harvest/jobs/{job_id}/retry` looks again at only the ones that failed.

### What happens to each file

1. **It is recognised.** The catalog works out the format from the file's content, never from
   its name.
2. **It is converted to CDIF**, if the catalog has a converter connected for that format.
3. **It is given its claims**: every profile its content fits.
4. **It is checked** against the rules for the profile it reaches.
5. **It is published** if it passes, and then appears in the feed.

### Formats the catalog converts

| Format | Notes |
|---|---|
| CDIF JSON-LD | Stored as it is. |
| ISO 19139, ISO 19115-2, ISO 19115-3 | Also a CSW response holding one record. |
| DataCite XML | One record per file. |
| schema.org JSON-LD | |
| RO-Crate | |
| Croissant | |
| FAIR2 | A large record can take over a minute. |
| NASA UMM-C | |
| DDI 1.2.2, DDI Codebook 2.5 | Checking a large record can take up to 80 seconds. |
| DDI-CDI, as XML or JSON-LD | |

One record per file is expected. A file holding several is reported and not stored.

Many more formats are **recognised but not converted**, among them FGDC, EML, Dublin Core, DCAT,
STAC and CKAN. Such a file is kept as received and reported with its format's name, so nothing
is lost; it can be converted later, once a converter is connected.

Converting does not guarantee passing. Several converters produce records that fail the check
on a detail, and those are stored but not published. The table in
[design.md](design.md) records how each converter does on its own examples.

### Good manners

The catalog obeys each site's `robots.txt`, including any delay it asks for between requests.
If a site closes an address to robots, the catalog skips it.

A record is withdrawn only when its file is missing from a run in which every fetch worked. A
run with failures never withdraws anything.

## Reading a problem report

Problems are written in plain language where the catalog has wording for them, for example:

> Give an identifier for the dataset, such as its DOI.

Each problem names the part of the record it is about, as a path such as `schema:distribution`,
`0`, `schema:contentUrl`: the first distribution's download address.

Some messages are still the raw text of a rule, such as "Less than 1 values on …". They mean the
same kind of thing, a required value is missing, but have not been given plain wording yet.

## For the person who runs the catalog

**Which profiles the catalog looks for** is set in `server/app/profile-sources.yaml`. It lists
groups of profiles by the repository that defines them: `cdif` (on), `dde` (off) and `geochem`
(off). Change `enabled` to switch a group on or off, then restart the `api` and `worker`
services. The geochemistry group claims nothing yet; its files are waiting on a change in their
home repository.

**Who is an administrator** is set with the `ADMIN_ORCIDS` setting: a list of ORCID iDs. A
person on the list becomes an administrator the next time they sign in.

Setting up sign-in is described in [setup-sandboxes.md](setup-sandboxes.md).

## What is not built yet

- **Search and browsing.** Records are reached through the feed and their own addresses.
- **Harvest pages in the web application.** Harvesting is done through the address list.
- **Other kinds of source**: CSW, OAI-PMH, sitemaps, CKAN, STAC.
- **Publishing a submitted record**, and any review step before it.
- **Drafts tied to your sign-in.** Anyone who has a draft's address can read and change it. Do
  not put anything private in a draft.
- **Full checking of the profiles beyond core and discovery.**
- **Forms for the richer profiles.** The form covers core and discovery.

## Words used in this guide

| Word | Meaning |
|---|---|
| **CDIF** | The Cross-Domain Interoperability Framework: an agreed way to write metadata so that it can be understood across subject areas. |
| **Profile** | A set of rules for one kind of content in a record. |
| **Claim** | A record's statement that it meets a profile. |
| **Catalog record** | The part of a record that describes the metadata itself: who made it, when, and what it claims. |
| **Harvest** | To fetch metadata records from another site, on request or on a schedule. |
| **Source** | A place the catalog harvests from. |
| **Run** | One harvest of one source. |
| **Feed** | The catalog's list of its published records, for other catalogs to read. |
| **DCAT** | A widely used vocabulary for describing catalogs and datasets. |
| **JSON-LD** | A way of writing linked data as JSON. CDIF records are JSON-LD. |
| **ORCID** | A registry of identifiers for researchers. |
| **ROR** | A registry of identifiers for research organisations. |
| **DOI** | A permanent identifier for a dataset or publication. |
