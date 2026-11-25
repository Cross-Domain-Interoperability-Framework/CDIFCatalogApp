"""What other catalogs and programs read: the DCAT catalog feed and each record's own address.

The feed has the interface ckanext-dcat made common, so harvesters that walk a CKAN catalog can
walk this one: /catalog.{ttl,jsonld,xml} with `page`, `modified_since` and `profiles`, and Hydra
paging. A record's address answers in the format the request's Accept header asks for.

Only published records the requester may see are served; see access.py.
"""
import datetime
import html
import json
import os
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app import access, auth, dcat, store

router = APIRouter()
PER_PAGE = 100

# The formats a record is offered in: key -> (media type, what a person would call it).
RECORD_FORMATS = {
    "html": ("text/html", "Web page"),
    "cdif": ("application/ld+json", "CDIF (JSON-LD)"),
    "dcat-jsonld": ('application/ld+json; profile="http://www.w3.org/ns/dcat#"', "DCAT (JSON-LD)"),
    "dcat-ttl": ("text/turtle", "DCAT (Turtle)"),
}
DCAT_PROFILE_PARAMETER = "http://www.w3.org/ns/dcat#"


def public_url(request: Request) -> str:
    """The address the catalog is reached at. Set PUBLIC_URL when it sits behind a proxy, since
    the addresses written into the feed must be ones a harvester can follow."""
    return (os.environ.get("PUBLIC_URL") or str(request.base_url)).rstrip("/")


def about_catalog(base: str) -> dict:
    return {
        "url": f"{base}/catalog",
        "title": os.environ.get("CATALOG_TITLE", "CDIF Catalog"),
        "description": os.environ.get("CATALOG_DESCRIPTION", "Metadata records held as CDIF."),
        "publisher": os.environ.get("CATALOG_PUBLISHER", "CDIF Catalog"),
    }


def _profile(profiles: str | None) -> str:
    """The first profile asked for. Unknown names are an error, not a silent default."""
    names = [p.strip() for p in (profiles or "dcat_ap").split(",") if p.strip()]
    unknown = [p for p in names if p not in dcat.PROFILES]
    if unknown or not names:
        raise HTTPException(422, f"Unknown profile: {', '.join(unknown)}. Known: {', '.join(dcat.PROFILES)}.")
    return names[0]


def _since(text: str | None):
    if text is None:
        return None
    try:
        when = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "modified_since must be a date or date and time, such as 2026-01-31.")
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


# ---- the catalog feed -------------------------------------------------------------------------


@router.get("/catalog.{fmt}")
def catalog(
    fmt: str,
    request: Request,
    page: int = 1,
    modified_since: str | None = None,
    profiles: str | None = None,
    user: access.User = Depends(auth.current_user),
) -> Response:
    if fmt not in dcat.FORMATS:
        raise HTTPException(404, f"The catalog is offered as: {', '.join(dcat.FORMATS)}.")
    if page < 1:
        raise HTTPException(422, "page starts at 1.")
    profile, since, base = _profile(profiles), _since(modified_since), public_url(request)

    with store.connect() as conn:
        total, rows = store.visible_records(conn, user, since, PER_PAGE, (page - 1) * PER_PAGE)

    def address(n: int) -> str:
        query = {"page": n}
        if modified_since:
            query["modified_since"] = modified_since
        if profiles:
            query["profiles"] = profiles
        return f"{base}/catalog.{fmt}?{urlencode(query)}"

    last = max(1, -(-total // PER_PAGE))
    paging = {
        "this": address(page), "total": total, "per_page": PER_PAGE, "first": address(1), "last": address(last),
        "next": address(page + 1) if page < last else None,
        "previous": address(page - 1) if 1 < page <= last + 1 else None,
    }
    graph = dcat.catalog_graph(
        [(r["published"], f"{base}/records/{r['id']}", r["changed_at"]) for r in rows],
        about_catalog(base), profile, paging,
    )
    return Response(dcat.serialize(graph, fmt), media_type=dcat.MEDIA[fmt])


# ---- the list the web pages show ---------------------------------------------------------------

LISTED_PER_PAGE = 20


def _words(value) -> str:
    """A title or description as plain text, whichever of the shapes CDIF allows it came in."""
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("@value") or value.get("schema:name") or ""
    return str(value or "")


def _date(value: str | None, which: str):
    if not value or not value.strip():
        return None
    try:
        return datetime.date.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(422, f"{which} must be a date like 2020-01-31.")


def _bbox(value: str | None):
    """A `west,south,east,north` box as four floats, or None. Longitudes in -180..180, latitudes
    in -90..90, west on or before east and south on or before north."""
    if not value or not value.strip():
        return None
    parts = value.split(",")
    if len(parts) != 4:
        raise HTTPException(422, "bbox must be four numbers: west,south,east,north.")
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError:
        raise HTTPException(422, "bbox must be four numbers: west,south,east,north.")
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90):
        raise HTTPException(422, "bbox longitudes must be in -180..180 and latitudes in -90..90.")
    if west > east or south > north:
        raise HTTPException(422, "bbox must be west,south,east,north, with west on or before east and south before north.")
    return (west, south, east, north)


@router.get("/api/records")
def list_records(
    q: str | None = None, page: int = 1, sort: str | None = None,
    source: str | None = None, publisher: str | None = None, profile: str | None = None,
    keyword: str | None = None, kind: str | None = None,
    start: str | None = None, end: str | None = None, bbox: str | None = None,
    user: access.User = Depends(auth.current_user),
) -> dict:
    """Published records the requester may see, for the browse and search pages. `q` keeps those
    holding those words. `sort` is `relevance` (the usual order when there are words), `modified`
    (most recently changed first, the usual order when there are none) or `title`. `source`,
    `publisher`, `profile`, `keyword` and `kind` each keep the records with that facet value.
    `start` and `end` (ISO dates) keep the records whose own time span overlaps that window; `bbox`
    (`west,south,east,north`) keeps those whose own area overlaps that box. The answer carries the
    facet counts and the active `filters` for the current query so the page can offer them."""
    if page < 1:
        raise HTTPException(422, "page starts at 1.")
    q = (q or "").strip()
    sort = sort or ("relevance" if q else "modified")
    if sort not in store.ORDERS:
        raise HTTPException(422, "sort must be one of: " + ", ".join(store.ORDERS))
    wanted = {"source": source, "publisher": publisher, "profile": profile, "keyword": keyword, "kind": kind}
    filters = {k: v.strip() for k, v in wanted.items() if v and v.strip()}
    after, before = _date(start, "start"), _date(end, "end")
    if after and before and after > before:
        raise HTTPException(422, "start must be on or before end.")
    covers = (after, before) if (after or before) else None
    within = _bbox(bbox)
    with store.connect() as conn:
        total, rows = store.visible_records(
            conn, user, limit=LISTED_PER_PAGE, offset=(page - 1) * LISTED_PER_PAGE,
            containing=q or None, order=sort, filters=filters, covers=covers, within=within,
        )
        facets = store.facet_counts(conn, user, containing=q or None, filters=filters, covers=covers, within=within)
    return {
        "total": total,
        "page": page,
        "sort": sort,
        "filters": filters,
        "covers": {"start": after.isoformat() if after else None, "end": before.isoformat() if before else None} if covers else None,
        "bbox": list(within) if within else None,
        "facets": facets,
        "pages": max(1, -(-total // LISTED_PER_PAGE)),
        "records": [
            {
                "id": str(r["id"]),
                "name": _words(r["published"].get("schema:name")) or "Untitled record",
                "description": _words(r["published"].get("schema:description"))[:300],
                "changed": r["changed_at"],
            }
            for r in rows
        ],
    }


# ---- one record -------------------------------------------------------------------------------


def _accepted(header: str | None) -> list[tuple[str, dict]]:
    """The Accept header as (media type, parameters), most wanted first."""
    ranges = []
    for position, part in enumerate((header or "*/*").split(",")):
        pieces = [p.strip() for p in part.split(";")]
        if not pieces[0]:
            continue
        params = dict(p.split("=", 1) for p in pieces[1:] if "=" in p)
        params = {k.strip().lower(): v.strip().strip('"') for k, v in params.items()}
        try:
            q = float(params.pop("q", "1"))
        except ValueError:
            q = 0.0
        if q > 0:
            ranges.append((-q, position, pieces[0].lower(), params))
    return [(media, params) for _, _, media, params in sorted(ranges)]


def choose_format(accept: str | None) -> str | None:
    """Which of the record's formats best answers an Accept header, or None for none of them."""
    for media, params in _accepted(accept):
        if media in ("text/html", "application/xhtml+xml", "*/*", "text/*"):
            return "html"
        if media in ("application/ld+json", "application/json", "application/*"):
            return "dcat-jsonld" if params.get("profile") == DCAT_PROFILE_PARAMETER else "cdif"
        if media == "text/turtle":
            return "dcat-ttl"
    return None


def _alternates(address: str) -> list[tuple[str, str, str]]:
    return [(f"{address}?format={key}", media, label) for key, (media, label) in RECORD_FORMATS.items()]


@router.get("/records/{record_id}")
def record(
    record_id: UUID,
    request: Request,
    format: str | None = None,
    profiles: str | None = None,
    user: access.User = Depends(auth.current_user),
) -> Response:
    if format is not None and format not in RECORD_FORMATS:
        raise HTTPException(422, f"Unknown format: {format}. Known: {', '.join(RECORD_FORMATS)}.")
    chosen = format or choose_format(request.headers.get("accept"))
    if chosen is None:
        offered = ", ".join(media for media, _ in RECORD_FORMATS.values())
        raise HTTPException(406, f"This record is offered as: {offered}.")
    profile = _profile(profiles)

    with store.connect() as conn:
        row = store.visible_record(conn, user, record_id)
    if row is None:  # the same answer whether it does not exist or may not be seen
        raise HTTPException(404, "No published record with that id.")

    address = f"{public_url(request)}/records/{record_id}"
    cdif = row["published"]
    if profile == "geodcat_ap" and not dcat.has_geography(cdif):
        profile = "dcat_ap"  # nothing geographic to add, so the plain profile is the honest one
    alternates = _alternates(address)
    headers = {
        "Vary": "Accept",
        "Link": ", ".join(f'<{href}>; rel="alternate"; type="{media.split(";")[0]}"' for href, media, _ in alternates),
    }
    if chosen == "html":
        copy = f"{public_url(request)}/?copy={record_id}"
        return Response(_page(cdif, alternates, copy), media_type="text/html", headers=headers)
    if chosen == "cdif":
        body = json.dumps(cdif, ensure_ascii=False, indent=2)
        return Response(body, media_type="application/ld+json", headers=headers)
    fmt = "jsonld" if chosen == "dcat-jsonld" else "ttl"
    graph = dcat.record_graph(cdif, address, row["changed_at"], profile)
    return Response(dcat.serialize(graph, fmt), media_type=RECORD_FORMATS[chosen][0], headers=headers)


# ---- the record as a web page -----------------------------------------------------------------

_e = html.escape


def _names(value) -> list[str]:
    """Display text for a property that may hold strings, named things, or a list of either."""
    out = []
    for v in dcat._many(value):
        if isinstance(v, dict) and "schema:Role" in dcat._many(v.get("@type")):
            v = v.get("schema:contributor")
        text = dcat._text(v) or (v.get("@id") if isinstance(v, dict) else None)
        if isinstance(text, str) and text.strip():
            out.append(text.strip())
    return out


def _linked(text: str) -> str:
    return f'<a href="{_e(text, quote=True)}">{_e(text)}</a>' if text.startswith(("http://", "https://")) else _e(text)


def _page(cdif: dict, alternates, copy: str) -> str:
    title = dcat._text(cdif.get("schema:name")) or "Untitled record"
    description = cdif.get("schema:description") if isinstance(cdif.get("schema:description"), str) else ""
    identifier = cdif.get("schema:identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("schema:url") or identifier.get("schema:value")
    downloads = [
        d.get("schema:contentUrl") or d.get("schema:url")
        for d in dcat._many(cdif.get("schema:distribution")) if isinstance(d, dict)
    ]
    rows = [
        ("Authors", _names(cdif.get("schema:creator"))),
        ("Contributors", _names(cdif.get("schema:contributor"))),
        ("Publisher", _names(cdif.get("schema:publisher"))),
        ("Identifier", [identifier] if isinstance(identifier, str) else []),
        ("Published", _names(cdif.get("schema:datePublished"))),
        ("Last updated", _names(cdif.get("schema:dateModified"))),
        ("Keywords", _names(cdif.get("schema:keywords"))),
        ("Licence", _names(cdif.get("schema:license"))),
        ("Landing page", _names(cdif.get("schema:url"))),
        ("Data", [d for d in downloads if isinstance(d, str)]),
    ]
    facts = "".join(
        f"<dt>{_e(label)}</dt><dd>{'<br>'.join(_linked(v) for v in values)}</dd>" for label, values in rows if values
    )
    links = "".join(
        f'<link rel="alternate" type="{_e(media, quote=True)}" href="{_e(href, quote=True)}" title="{_e(label, quote=True)}">'
        for href, media, label in alternates if not href.endswith("=html")
    )
    formats = " · ".join(
        f'<a href="{_e(href, quote=True)}">{_e(label)}</a>' for href, _, label in alternates if not href.endswith("=html")
    )
    # "</" must not appear inside a script element, or the page could be closed early
    embedded = json.dumps(cdif, ensure_ascii=False).replace("</", "<\\/")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title>{links}"
        f'<script type="application/ld+json">{embedded}</script>'
        "<style>body{font:16px/1.5 system-ui,sans-serif;max-width:50rem;margin:2rem auto;padding:0 1rem}"
        "dt{font-weight:600;margin-top:.75rem}dd{margin:0;overflow-wrap:anywhere}"
        "footer{margin-top:2rem;border-top:1px solid #ccc;padding-top:.75rem;font-size:.9rem}</style></head>"
        f"<body><main><h1>{_e(title)}</h1><p>{_e(description)}</p><dl>{facts}</dl></main>"
        f"<footer>This record in other formats: {formats}"
        f'<br><a href="{_e(copy, quote=True)}">Open a copy of this record in the form</a></footer></body></html>'
    )
