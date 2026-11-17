"""Lookups against public registries: ORCID (people), ROR (organisations), DataCite and Crossref (DOIs).

The browser never calls these services itself. It asks this server, which keeps the mapping to
CDIF in one tested place and sends the registries nothing about the user beyond the search text.

The functions named *_to_* are pure: registry JSON in, CDIF-shaped dicts out.
"""
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/lookup")

USER_AGENT = "CDIFCatalogApp/0.1 (prototype)"
TIMEOUT = httpx.Timeout(10.0)

# Overridable so a deployment can point at the ORCID sandbox (https://pub.sandbox.orcid.org).
ORCID_API = os.environ.get("ORCID_API_BASE", "https://pub.orcid.org")
ROR_API = "https://api.ror.org/v2/organizations"
# Overridable to read DataCite's test system (https://api.test.datacite.org).
DATACITE_API = os.environ.get("DATACITE_API_BASE", "https://api.datacite.org") + "/dois"
CROSSREF_API = "https://api.crossref.org/works"

ORCID_ID = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")
DOI = re.compile(r"10\.\d{4,9}/\S+")
FULL_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def fetch(url: str, params: dict | None = None) -> dict | None:
    """GET JSON. None for 404; HTTP 502 to our caller for anything else that goes wrong."""
    try:
        res = httpx.get(
            url,
            params=params,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            follow_redirects=True,
        )
    except httpx.HTTPError:
        raise HTTPException(502, "The lookup service could not be reached.")
    if res.status_code == 404:
        return None
    if res.status_code != 200:
        raise HTTPException(502, f"The lookup service answered with status {res.status_code}.")
    return res.json()


# --- organisations (ROR) ---------------------------------------------------------------------


def ror_to_organisations(payload: dict) -> list[dict]:
    out = []
    for item in payload.get("items", []):
        names = item.get("names", [])
        display = next((n["value"] for n in names if "ror_display" in n.get("types", [])), None)
        if not display:
            continue
        acronym = next((n["value"] for n in names if "acronym" in n.get("types", [])), None)
        country = next(
            (
                loc.get("geonames_details", {}).get("country_name")
                for loc in item.get("locations", [])
            ),
            None,
        )
        out.append({"name": display, "identifier": item["id"], "acronym": acronym, "country": country})
    return out


@router.get("/organisations")
def organisations(q: str = Query(min_length=2, max_length=200)) -> list[dict]:
    return ror_to_organisations(fetch(ROR_API, {"query": q}) or {})[:10]


# --- people (ORCID) --------------------------------------------------------------------------


def orcid_to_people(payload: dict) -> list[dict]:
    out = []
    for hit in payload.get("expanded-result") or []:
        name = hit.get("credit-name") or " ".join(
            part for part in (hit.get("given-names"), hit.get("family-names")) if part
        )
        if not name:
            continue  # a record with no public name is no use in an author list
        out.append(
            {
                "name": name,
                "identifier": f"https://orcid.org/{hit['orcid-id']}",
                "affiliations": hit.get("institution-name") or [],
            }
        )
    return out


def orcid_query(text: str) -> str:
    """Search by iD when the text contains one; otherwise require every word in the name fields."""
    found = ORCID_ID.search(text)
    if found:
        return f"orcid:{found.group(0)}"
    words = re.findall(r"[^\W\d_]+", text)
    if not words:
        raise HTTPException(422, "Enter a name or an ORCID iD.")
    # ORCID's search field is `family-name`, singular, although its results say `family-names`.
    # An unknown field name makes ORCID answer 500, so check a change here against the live API.
    return " AND ".join(
        f"(given-names:{w}* OR family-name:{w}* OR other-names:{w}*)" for w in words
    )


@router.get("/people")
def people(q: str = Query(min_length=2, max_length=200)) -> list[dict]:
    payload = fetch(f"{ORCID_API}/v3.0/expanded-search/", {"q": orcid_query(q), "rows": 10})
    return orcid_to_people(payload or {})


# --- DOIs (DataCite, then Crossref) ----------------------------------------------------------


def normalise_doi(text: str) -> str:
    found = DOI.search(text.strip())
    if not found:
        raise HTTPException(422, "That does not look like a DOI. A DOI starts with 10. and has a slash.")
    return found.group(0).rstrip(".,;)").lower()


def _full_date(value) -> str | None:
    found = FULL_DATE.match(str(value or ""))
    return found.group(0) if found else None


def _without_empty(record: dict) -> dict:
    return {k: v for k, v in record.items() if v not in (None, "", [], {})}


def datacite_to_cdif(payload: dict) -> dict:
    a = payload["data"]["attributes"]

    def party(c: dict) -> dict:
        personal = c.get("nameType") != "Organizational"
        given, family = c.get("givenName"), c.get("familyName")
        name = f"{given} {family}" if personal and given and family else c.get("name")
        orcid = next(
            (
                ORCID_ID.search(i.get("nameIdentifier", ""))
                for i in c.get("nameIdentifiers", [])
                if i.get("nameIdentifierScheme", "").upper() == "ORCID"
            ),
            None,
        )
        # Affiliations are plain strings by default and objects when the API is asked for detail.
        affiliation = next(
            (x if isinstance(x, str) else x.get("name") for x in c.get("affiliation", [])), None
        )
        return _without_empty(
            {
                "@type": "schema:Person" if personal else "schema:Organization",
                "schema:name": name,
                "schema:identifier": f"https://orcid.org/{orcid.group(0)}" if orcid else None,
                "schema:affiliation": {"schema:name": affiliation} if affiliation else None,
            }
        )

    dates = {d.get("dateType"): _full_date(d.get("date")) for d in a.get("dates") or []}
    publisher = a.get("publisher")
    if isinstance(publisher, dict):  # an object from DataCite schema 4.5 on, a string before
        publisher = publisher.get("name")
    abstract = next(
        (d["description"] for d in a.get("descriptions") or [] if d.get("descriptionType") == "Abstract"),
        None,
    )
    creators = [p for p in map(party, a.get("creators") or []) if p.get("schema:name")]
    return _without_empty(
        {
            "schema:name": next((t["title"] for t in a.get("titles") or [] if not t.get("titleType")), None),
            "schema:description": abstract,
            "schema:identifier": f"https://doi.org/{a['doi']}",
            "schema:url": a.get("url"),
            "schema:datePublished": dates.get("Issued"),
            "schema:dateModified": dates.get("Updated"),
            "schema:version": a.get("version"),
            "schema:inLanguage": a.get("language"),
            "schema:keywords": [s["subject"] for s in a.get("subjects") or [] if s.get("subject")],
            "schema:license": [
                _without_empty(
                    {
                        "@type": "schema:CreativeWork",
                        "schema:name": r.get("rights"),
                        "schema:url": r.get("rightsUri"),
                    }
                )
                for r in a.get("rightsList") or []
                if r.get("rights") or r.get("rightsUri")
            ],
            "schema:publisher": {"@type": "schema:Organization", "schema:name": publisher} if publisher else None,
            "schema:creator": {"@list": creators} if creators else None,
        }
    )


def crossref_to_cdif(payload: dict) -> dict:
    m = payload["message"]

    def person(a: dict) -> dict:
        orcid = ORCID_ID.search(a.get("ORCID", ""))
        affiliation = next((x.get("name") for x in a.get("affiliation", [])), None)
        is_person = bool(a.get("family"))
        name = " ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name")
        return _without_empty(
            {
                "@type": "schema:Person" if is_person else "schema:Organization",
                "schema:name": name,
                "schema:identifier": f"https://orcid.org/{orcid.group(0)}" if orcid else None,
                "schema:affiliation": {"schema:name": affiliation} if affiliation else None,
            }
        )

    parts = ((m.get("issued") or {}).get("date-parts") or [[]])[0]
    issued = "-".join(f"{p:02d}" for p in parts) if len(parts) == 3 else None
    creators = [p for p in map(person, m.get("author") or []) if p.get("schema:name")]
    publisher = m.get("publisher")
    return _without_empty(
        {
            "schema:name": next(iter(m.get("title") or []), None),
            "schema:identifier": f"https://doi.org/{m['DOI'].lower()}",
            "schema:url": m.get("URL"),
            "schema:datePublished": issued,
            "schema:inLanguage": m.get("language"),
            "schema:license": [
                {"@type": "schema:CreativeWork", "schema:url": lic["URL"]}
                for lic in m.get("license") or []
                if lic.get("URL")
            ],
            "schema:publisher": {"@type": "schema:Organization", "schema:name": publisher} if publisher else None,
            "schema:creator": {"@list": creators} if creators else None,
        }
    )


@router.get("/doi")
def doi(doi: str = Query(min_length=6, max_length=300)) -> dict:
    name = normalise_doi(doi)
    payload = fetch(f"{DATACITE_API}/{name}")
    if payload:
        return {"source": "DataCite", "record": datacite_to_cdif(payload)}
    payload = fetch(f"{CROSSREF_API}/{name}")
    if payload:
        return {"source": "Crossref", "record": crossref_to_cdif(payload)}
    raise HTTPException(404, "Neither DataCite nor Crossref knows that DOI.")
