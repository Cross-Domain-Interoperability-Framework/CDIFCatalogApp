"""The catalog feed and the record address. Needs a real PostgreSQL (DATABASE_URL); fails, not
skips, without one. Records are written straight into the table and removed afterwards."""
import datetime
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from rdflib import Graph, URIRef
from rdflib.namespace import DCAT, RDF

from app import access, dcat, outbound
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures" / "CoreDiscovery"
MINIMAL = json.loads((FIXTURES / "exampleCDIFDiscoveryMinimal.json").read_text(encoding="utf-8"))
COMPLETE = json.loads((FIXTURES / "exampleCDIFDiscoveryComplete.json").read_text(encoding="utf-8"))
BASE = "https://catalog.example"


@pytest.fixture
def catalog(monkeypatch):
    assert os.environ.get("DATABASE_URL"), "DATABASE_URL must be set to run the outbound tests"
    monkeypatch.setenv("PUBLIC_URL", BASE)
    ids = []

    def add(document, status="published", organisation=None, **change):
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            record_id = conn.execute(
                "INSERT INTO records (profile, published, status, organisation, labels) "
                "VALUES ('CoreDiscovery', %s, %s, %s, %s) RETURNING id",
                (Jsonb({**document, **change}), status, organisation, access.record_labels(status, organisation)),
            ).fetchone()[0]
        ids.append(str(record_id))
        return str(record_id)

    with TestClient(app) as client:
        client.add = add
        client.started = datetime.datetime.now(datetime.timezone.utc).isoformat()
        yield client
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("DELETE FROM records WHERE id = ANY(%s::uuid[])", (ids,))


def feed(client, fmt="ttl", **params):
    res = client.get(f"/catalog.{fmt}", params={"modified_since": client.started, **params})
    assert res.status_code == 200, res.text
    return res, Graph().parse(data=res.text, format=dcat.FORMATS[fmt])


def records_in(graph):
    return {str(s) for s in graph.subjects(RDF.type, DCAT.CatalogRecord)}


def test_the_feed_lists_published_records_and_nothing_else(catalog):
    shown = catalog.add(MINIMAL)
    hidden = [catalog.add(MINIMAL, status="invalid"), catalog.add(MINIMAL, status="withdrawn", organisation="org-a")]
    res, graph = feed(catalog)
    assert res.headers["content-type"].startswith("text/turtle")
    assert f"{BASE}/records/{shown}" in records_in(graph)
    assert not {f"{BASE}/records/{h}" for h in hidden} & records_in(graph)
    assert (URIRef(f"{BASE}/catalog"), RDF.type, DCAT.Catalog) in graph


@pytest.mark.parametrize("fmt, media", [("ttl", "text/turtle"), ("jsonld", "application/ld+json"), ("xml", "application/rdf+xml")])
def test_the_feed_is_offered_in_three_formats(catalog, fmt, media):
    record = catalog.add(COMPLETE)
    res, graph = feed(catalog, fmt)
    assert res.headers["content-type"].startswith(media)
    assert f"{BASE}/records/{record}" in records_in(graph)


def test_paging_is_described_with_hydra_and_can_be_walked(catalog, monkeypatch):
    monkeypatch.setattr(outbound, "PER_PAGE", 2)
    added = {f"{BASE}/records/{catalog.add(MINIMAL, **{'@id': f'https://example.org/d/{i}'})}" for i in range(5)}
    seen, address, pages = set(), f"/catalog.ttl?modified_since={catalog.started.replace('+', '%2B')}", 0
    while address:
        graph = Graph().parse(data=catalog.get(address).text, format="turtle")
        page = next(graph.subjects(RDF.type, dcat.HYDRA.PagedCollection))
        assert int(graph.value(page, dcat.HYDRA.totalItems)) == 5
        assert str(graph.value(page, dcat.HYDRA.last)).startswith(f"{BASE}/catalog.ttl?page=3&")
        seen |= records_in(graph)
        nxt = graph.value(page, dcat.HYDRA.next)
        assert nxt == graph.value(page, dcat.HYDRA.nextPage)  # both the current and the older term
        address, pages = (str(nxt)[len(BASE):] if nxt else None), pages + 1
    assert pages == 3 and seen == added


def test_modified_since_leaves_out_older_records(catalog):
    record = catalog.add(MINIMAL)
    later = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)).isoformat()
    assert f"{BASE}/records/{record}" in records_in(feed(catalog)[1])
    assert records_in(feed(catalog, modified_since=later)[1]) == set()


def test_bad_parameters_are_refused_not_ignored(catalog):
    assert catalog.get("/catalog.ttl?profiles=sweden_dcat_ap").status_code == 422
    assert catalog.get("/catalog.ttl?modified_since=yesterday").status_code == 422
    assert catalog.get("/catalog.ttl?page=0").status_code == 422
    assert catalog.get("/catalog.csv").status_code == 404


@pytest.mark.parametrize("accept, expected", [
    (None, "html"),
    ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "html"),
    ("application/ld+json", "cdif"),
    ("application/json", "cdif"),
    ('application/ld+json; profile="http://www.w3.org/ns/dcat#"', "dcat-jsonld"),
    ("text/turtle", "dcat-ttl"),
    ("text/turtle;q=0.5, application/ld+json", "cdif"),
    ("application/ld+json;q=0.2, text/turtle;q=0.9", "dcat-ttl"),
    ("image/png, text/turtle;q=0", None),
])
def test_the_accept_header_chooses_the_format(accept, expected):
    assert outbound.choose_format(accept) == expected


def test_a_record_address_answers_in_each_format(catalog):
    record = catalog.add(COMPLETE)
    address = f"/records/{record}"

    page = catalog.get(address, headers={"accept": "text/html"})
    assert page.headers["content-type"].startswith("text/html") and page.headers["vary"] == "Accept"
    assert "<h1>North Atlantic Deep Water Formation Observations 2015-2024</h1>" in page.text
    for key, media in (("cdif", "application/ld+json"), ("dcat-ttl", "text/turtle")):
        assert f'<link rel="alternate" type="{media}" href="{BASE}{address}?format={key}"' in page.text
    assert f'<{BASE}{address}?format=dcat-ttl>; rel="alternate"; type="text/turtle"' in page.headers["link"]

    cdif = catalog.get(address, headers={"accept": "application/ld+json"})
    assert cdif.headers["content-type"].startswith("application/ld+json") and cdif.json() == COMPLETE

    turtle = catalog.get(address, headers={"accept": "text/turtle"})
    graph = Graph().parse(data=turtle.text, format="turtle")
    assert (URIRef(f"{BASE}{address}"), RDF.type, DCAT.CatalogRecord) in graph

    as_dcat = catalog.get(address, headers={"accept": 'application/ld+json; profile="http://www.w3.org/ns/dcat#"'})
    assert len(Graph().parse(data=as_dcat.text, format="json-ld")) == len(graph)

    asked = catalog.get(address + "?format=dcat-ttl", headers={"accept": "text/html"})  # the parameter wins
    assert asked.headers["content-type"].startswith("text/turtle")
    assert len(Graph().parse(data=asked.text, format="turtle")) == len(graph)
    assert catalog.get(address, headers={"accept": "image/png"}).status_code == 406
    assert catalog.get(address + "?format=pdf").status_code == 422


def test_the_page_embeds_the_record_and_escapes_what_it_shows(catalog):
    record = catalog.add(MINIMAL, **{"schema:name": "<script>alert(1)</script>", "schema:description": "ends </script> early"})
    text = catalog.get(f"/records/{record}").text
    assert "<script>alert(1)</script>" not in text and "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    embedded = text.split('<script type="application/ld+json">')[1].split("</script>")[0]
    assert json.loads(embedded)["schema:description"] == "ends </script> early"


def test_the_page_links_to_a_copy_of_the_record_in_the_form(catalog):
    record = catalog.add(MINIMAL)
    assert f'<a href="{BASE}/?copy={record}">Open a copy of this record in the form</a>' in catalog.get(f"/records/{record}").text


def test_an_unpublished_or_unknown_record_is_not_found(catalog):
    assert catalog.get(f"/records/{catalog.add(MINIMAL, status='invalid')}").status_code == 404
    assert catalog.get(f"/records/{uuid4()}").status_code == 404


def test_the_list_finds_published_records_by_words_in_any_of_their_fields(catalog):
    mark = "zz" + uuid4().hex[:8]  # a word no other record has
    found = catalog.add(MINIMAL, **{"schema:name": f"Zircon {mark} ages", "schema:description": "U-Pb dates"})
    by_keyword = catalog.add(MINIMAL, **{"schema:name": "Other", "schema:keywords": ["basalt", mark]})
    by_creator = catalog.add(MINIMAL, **{"schema:name": "Third", "schema:creator": [{"@type": "schema:Person", "schema:name": f"Dr {mark}"}]})
    hidden = catalog.add(MINIMAL, status="invalid", **{"schema:name": f"Hidden {mark}"})

    listed = catalog.get("/api/records", params={"q": mark.upper()}).json()
    assert {r["id"] for r in listed["records"]} == {found, by_keyword, by_creator} and listed["total"] == 3
    assert hidden not in {r["id"] for r in listed["records"]}
    first = next(r for r in listed["records"] if r["id"] == found)
    assert first["name"] == f"Zircon {mark} ages" and first["description"] == "U-Pb dates"

    # words match by their stem, so a different ending still finds the record
    assert found in {r["id"] for r in catalog.get("/api/records", params={"q": f"{mark} age"}).json()["records"]}
    # every word must be present: {mark} and a word only one record has narrows to that record
    assert catalog.get("/api/records", params={"q": f"{mark} basalt"}).json()["total"] == 1

    everything = catalog.get("/api/records").json()
    assert everything["total"] >= 3 and len(everything["records"]) <= 20
    assert catalog.get("/api/records", params={"page": 0}).status_code == 422
    assert catalog.get("/api/records", params={"sort": "sideways"}).status_code == 422


def test_search_ranks_title_matches_first_and_sorts_on_request(catalog):
    mark = "qq" + uuid4().hex[:8]
    in_title = catalog.add(MINIMAL, **{"schema:name": f"{mark} survey"})
    in_description = catalog.add(MINIMAL, **{"schema:name": "Aardvark study", "schema:description": f"mentions {mark} in passing"})

    # relevance is the order when there are words, and a word in the title outranks one in the description
    by_relevance = catalog.get("/api/records", params={"q": mark}).json()
    assert by_relevance["sort"] == "relevance"
    ranked = [r["id"] for r in by_relevance["records"]]
    assert ranked.index(in_title) < ranked.index(in_description)

    # sort=title orders by name instead, ignoring relevance
    by_title = catalog.get("/api/records", params={"q": mark, "sort": "title"}).json()
    assert by_title["sort"] == "title"
    names = [r["name"] for r in by_title["records"]]
    assert names == sorted(names, key=str.lower)


def test_search_offers_facets_and_filters_by_them(catalog):
    mark = "ff" + uuid4().hex[:8]

    def by(name):
        return {"@type": ["schema:Organization"], "schema:name": f"{name} {mark}"}

    alpha = catalog.add(MINIMAL, **{"schema:name": f"{mark} alpha", "schema:publisher": by("Acme")})
    catalog.add(MINIMAL, **{"schema:name": f"{mark} beta", "schema:publisher": by("Beta")})
    gamma = catalog.add(MINIMAL, **{"schema:name": f"{mark} gamma", "schema:publisher": by("Acme")})

    everything = catalog.get("/api/records", params={"q": mark}).json()
    assert everything["filters"] == {}
    publishers = {f["label"]: f["count"] for f in everything["facets"]["publisher"]}
    assert publishers[f"Acme {mark}"] == 2 and publishers[f"Beta {mark}"] == 1
    assert everything["facets"]["profile"] == [{"value": "CoreDiscovery", "label": "Discovery", "count": 3}]

    # choosing a publisher keeps only its records, and echoes the choice back
    chosen = catalog.get("/api/records", params={"q": mark, "publisher": f"Acme {mark}"}).json()
    assert chosen["total"] == 2 and {r["id"] for r in chosen["records"]} == {alpha, gamma}
    assert chosen["filters"] == {"publisher": f"Acme {mark}"}
    # a facet's own filter does not hide its other values, so the other publisher is still offered
    assert f"Beta {mark}" in {f["label"] for f in chosen["facets"]["publisher"]}

    # a value nothing carries simply finds nothing
    assert catalog.get("/api/records", params={"q": mark, "publisher": "nobody at all"}).json()["total"] == 0
