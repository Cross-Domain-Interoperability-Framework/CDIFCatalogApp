"""The DCAT harvester: a catalogue read as a graph, in any of its three forms, and each dataset
cut out of it as a document of its own that the DCAT converter takes."""
import json

import httpx
import pytest

from app.harvest import HarvestError, convert, harvesters
from app.harvest.dcat import DcatHarvester, address, cut, datasets, read
from app.harvest.detect import detect

SITE = "https://portal.example/"
PREFIXES = (
    "@prefix dcat: <http://www.w3.org/ns/dcat#> .\n@prefix dct: <http://purl.org/dc/terms/> .\n"
    "@prefix foaf: <http://xmlns.com/foaf/0.1/> .\n@prefix hydra: <http://www.w3.org/ns/hydra/core#> .\n"
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
)


def dataset(name, modified="2024-03-30"):
    return (
        f'<{SITE}dataset/{name}> a dcat:Dataset ; dct:title "The {name} dataset" ; dct:description "About {name}." ;\n'
        f'  dct:identifier "{SITE}dataset/{name}" ; dct:modified "{modified}"^^xsd:date ;\n'
        f'  dct:publisher <{SITE}org/survey> ;\n'
        f'  dcat:distribution [ a dcat:Distribution ; dcat:downloadURL <{SITE}files/{name}.csv> ; dct:format "CSV" ] .\n'
    )


PUBLISHER = f'<{SITE}org/survey> a foaf:Organization ; foaf:name "Geological Survey" .\n'


def page(names, following=None, catalog=True):
    text = PREFIXES + "".join(dataset(n) for n in names) + PUBLISHER
    if catalog:
        text += f"<{SITE}catalog> a dcat:Catalog ; dct:title \"Portal\" ; " + " ; ".join(f"dcat:dataset <{SITE}dataset/{n}>" for n in names) + " .\n"
    if following:
        text += f'<{SITE}catalog.ttl?page=1> a hydra:PagedCollection ; hydra:next "{following}" .\n'
    return text


POD = {
    "@context": "https://project-open-data.cio.gov/v1.1/schema/catalog.jsonld",
    "conformsTo": "https://project-open-data.cio.gov/v1.1/schema",
    "dataset": [
        {"@type": "dcat:Dataset", "identifier": "AGENCY-001", "title": "Census pages", "description": "Scanned pages.", "modified": "2023-03-10",
         "publisher": {"@type": "org:Organization", "name": "The Agency"},
         "distribution": [{"@type": "dcat:Distribution", "downloadURL": "https://agency.example/a.zip", "mediaType": "application/zip"}]},
        {"@type": "dcat:Dataset", "identifier": "https://agency.example/id/2", "title": "Second", "description": "Another."},
    ],
}
POD_CONTEXT = {"@context": {
    "dcat": "http://www.w3.org/ns/dcat#", "dct": "http://purl.org/dc/terms/", "foaf": "http://xmlns.com/foaf/0.1/",
    "org": "http://www.w3.org/ns/org#", "xsd": "http://www.w3.org/2001/XMLSchema#",
    "dataset": {"@id": "dcat:dataset", "@container": "@set"}, "identifier": "dct:identifier", "title": "dct:title",
    "description": "dct:description", "modified": "dct:modified", "publisher": "dct:publisher", "name": "foaf:name",
    "distribution": {"@id": "dcat:distribution", "@container": "@set"}, "downloadURL": {"@id": "dcat:downloadURL", "@type": "@id"},
    "mediaType": "dcat:mediaType", "conformsTo": {"@id": "dct:conformsTo", "@type": "@id"},
}}


def site(answers):
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if url not in answers:
            return httpx.Response(404)
        body, media = answers[url]
        return httpx.Response(200, content=(body if isinstance(body, str) else json.dumps(body)).encode("utf-8"), headers={"content-type": media})

    return httpx.Client(transport=httpx.MockTransport(handler)), asked


def gather(harvester, http, url, **config):
    return harvester.gather({"url": url, "config": harvester.validate_config(config)}, None, http)


def test_the_catalog_offers_dcat_as_a_kind_of_source():
    assert harvesters()["dcat"].title == "DCAT catalogue"


def test_a_catalogue_is_followed_page_by_page_and_each_dataset_is_listed_with_its_date():
    http, asked = site({
        SITE + "catalog.ttl": (page(["a", "b"], following=SITE + "catalog.ttl?page=2"), "text/turtle"),
        SITE + "catalog.ttl?page=2": (page(["c"]), "text/turtle"),
    })
    harvester = DcatHarvester()
    found = gather(harvester, http, SITE + "catalog.ttl")
    assert {i.identifier: (i.url, i.modified) for i in found.items} == {
        SITE + "dataset/a": (SITE + "catalog.ttl", "2024-03-30T00:00:00"),
        SITE + "dataset/b": (SITE + "catalog.ttl", "2024-03-30T00:00:00"),
        SITE + "dataset/c": (SITE + "catalog.ttl?page=2", "2024-03-30T00:00:00"),
    }
    assert found.complete is True
    # fetching a dataset reads the page already held; the site is not asked again
    fetched = harvester.fetch({}, found.items[0], http)
    assert asked == [SITE + "catalog.ttl", SITE + "catalog.ttl?page=2"]
    assert detect(fetched.content).format == "dcat-jsonld"


def test_a_dataset_is_cut_out_with_what_hangs_from_it_and_nothing_of_its_neighbours():
    graph = read(page(["a", "b"]), "text/turtle", SITE + "catalog.ttl", None)
    text = cut(graph, datasets(graph)[SITE + "dataset/a"])
    assert "The a dataset" in text and "files/a.csv" in text and "Geological Survey" in text
    assert "The b dataset" not in text and "Portal" not in text
    record = convert.to_cdif(detect(text), text)
    assert record["@id"] == SITE + "dataset/a" and record["schema:name"] == "The a dataset"
    assert record["schema:distribution"][0]["schema:contentUrl"] == SITE + "files/a.csv"


def test_the_same_dataset_gives_the_same_text_each_time_it_is_read():
    texts = set()
    for _ in range(3):
        graph = read(page(["a", "b"]), "text/turtle", SITE + "catalog.ttl", None)
        texts.add(cut(graph, datasets(graph)[SITE + "dataset/a"]))
    assert len(texts) == 1  # the download has no address of its own, and still gets the same label


def test_rdf_xml_and_json_ld_catalogues_are_read_the_same_way():
    from rdflib import Graph

    turtle = Graph().parse(data=page(["a", "b"]), format="turtle")
    for form, media in (("xml", "application/rdf+xml"), ("json-ld", "application/ld+json")):
        graph = read(turtle.serialize(format=form), media, SITE + "catalog", None)
        assert sorted(datasets(graph)) == [SITE + "dataset/a", SITE + "dataset/b"]


def test_a_data_json_has_its_context_fetched_politely_and_its_datasets_given_addresses():
    http, asked = site({
        "https://agency.example/data.json": (POD, "application/json"),
        "https://project-open-data.cio.gov/v1.1/schema/catalog.jsonld": (POD_CONTEXT, "application/ld+json"),
    })
    harvester = DcatHarvester()
    found = gather(harvester, http, "https://agency.example/data.json")
    assert asked == ["https://agency.example/data.json", "https://project-open-data.cio.gov/v1.1/schema/catalog.jsonld"]
    assert {i.identifier: i.modified for i in found.items} == {"AGENCY-001": "2023-03-10T00:00:00", "https://agency.example/id/2": None}
    item = next(i for i in found.items if i.identifier == "AGENCY-001")
    record = convert.to_cdif(detect(harvester.fetch({}, item, http).content), harvester.fetch({}, item, http).content)
    # a dataset with only a short identifier is addressed as a part of its catalogue
    assert record["@id"] == "https://agency.example/data.json#AGENCY-001" and record["schema:name"] == "Census pages"
    # a data.json that leaves its context out is read with the standard one
    bare, _ = site({
        "https://agency.example/data.json": ({k: v for k, v in POD.items() if k != "@context"}, "application/json"),
        "https://project-open-data.cio.gov/v1.1/schema/catalog.jsonld": (POD_CONTEXT, "application/ld+json"),
    })
    assert len(gather(DcatHarvester(), bare, "https://agency.example/data.json").items) == 2


def test_an_address_a_dataset_already_has_is_kept_and_one_is_made_only_where_needed():
    assert address("https://x.example/d/1", SITE + "data.json") == "https://x.example/d/1"
    assert address("ABC 1/2", SITE + "data.json#top") == SITE + "data.json#ABC%201%2F2"


def test_a_list_cut_short_by_the_limit_is_not_called_complete():
    http, _ = site({SITE + "catalog.ttl": (page(["a", "b", "c"]), "text/turtle")})
    found = gather(DcatHarvester(), http, SITE + "catalog.ttl", limit=2)
    assert len(found.items) == 2 and found.complete is False
    assert gather(DcatHarvester(), http, SITE + "catalog.ttl", limit=3).complete is True


def test_an_address_that_is_no_dcat_catalogue_is_said_so_in_words():
    http, _ = site({
        SITE + "page": ("Welcome to the portal", "text/plain"),
        SITE + "empty.ttl": (PREFIXES + PUBLISHER, "text/turtle"),
        SITE + "broken.ttl": (PREFIXES + '<a> a dcat:Dataset ; dct:title "never closed .', "text/turtle"),
    })
    with pytest.raises(HarvestError, match="neither JSON-LD, RDF/XML nor Turtle"):
        gather(DcatHarvester(), http, SITE + "page")
    with pytest.raises(HarvestError, match="holds no DCAT dataset"):
        gather(DcatHarvester(), http, SITE + "empty.ttl")
    with pytest.raises(HarvestError, match="could not be read as a DCAT catalogue"):
        gather(DcatHarvester(), http, SITE + "broken.ttl")


def test_a_file_of_one_dcat_dataset_converts_in_each_form_and_a_file_of_many_is_refused():
    from rdflib import Graph

    one = Graph().parse(data=page(["a"], catalog=False), format="turtle")
    for form in ("turtle", "xml", "json-ld"):
        text = one.serialize(format=form)
        assert convert.to_cdif(detect(text), text)["schema:name"] == "The a dataset", form
    many = page(["a", "b"])
    with pytest.raises(HarvestError, match="holds 2 DCAT datasets.*DCAT catalogue kind"):
        convert.to_cdif(detect(many), many)
    remote = json.dumps({"@context": "https://elsewhere.example/context.jsonld", "@type": "dcat:Dataset", "@id": SITE + "d"})
    with pytest.raises(HarvestError, match="names its JSON-LD context by address"):
        convert.to_cdif(detect(remote), remote)


def test_settings_that_make_no_sense_are_refused():
    with pytest.raises(HarvestError, match="limit"):
        DcatHarvester().validate_config({"limit": 0})
