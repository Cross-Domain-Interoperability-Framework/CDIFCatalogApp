"""DCAT output is checked the way ckanext-dcat checks its own: serialise, then validate against
the SHACL shapes SEMIC publishes (fixtures/shapes, see PINNED.md there)."""
import datetime
import json
from functools import lru_cache
from pathlib import Path

import pyshacl
import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCAT, DCTERMS, RDF

from app import dcat, validate

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = ["exampleCDIFDiscoveryMinimal.json", "exampleCDIFDiscovery.json", "exampleCDIFDiscoveryComplete.json"]
SHAPES = {"dcat_ap": "dcat-ap-3.0.0-SHACL.ttl", "geodcat_ap": "geodcat-ap-3.0.0-SHACL.ttl"}
CHANGED = datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.timezone.utc)
ABOUT = {"url": "https://catalog.example/catalog", "title": "Test catalog", "description": "For tests.", "publisher": "Tester"}


def example(name: str) -> dict:
    return json.loads((FIXTURES / "CoreDiscovery" / name).read_text(encoding="utf-8"))


@lru_cache
def shapes(profile: str) -> Graph:
    return Graph().parse(FIXTURES / "shapes" / SHAPES[profile], format="turtle")


def problems(graph: Graph, profile: str) -> list[str]:
    # Round-trip through Turtle first: what is validated is what a harvester would read.
    data = Graph().parse(data=dcat.serialize(graph, "ttl"), format="turtle")
    conforms, report, _ = pyshacl.validate(data, shacl_graph=shapes(profile), inference="none")
    sh = validate.SH
    return sorted(
        f"{report.value(r, sh.resultPath)} | {report.value(r, sh.resultMessage)}"
        for r in report.subjects(RDF.type, sh.ValidationResult)
        if report.value(r, sh.resultSeverity) == sh.Violation
    )


@pytest.mark.parametrize("profile", dcat.PROFILES)
@pytest.mark.parametrize("name", EXAMPLES)
def test_a_record_passes_the_official_shapes(name, profile):
    graph = dcat.record_graph(example(name), "https://catalog.example/records/1", CHANGED, profile)
    assert problems(graph, profile) == []


@pytest.mark.parametrize("profile", dcat.PROFILES)
def test_a_catalog_page_passes_the_official_shapes(profile):
    rows = [(example(n), f"https://catalog.example/records/{i}", CHANGED) for i, n in enumerate(EXAMPLES)]
    paging = {"this": ABOUT["url"] + ".ttl?page=1", "total": 3, "per_page": 100, "first": ABOUT["url"] + ".ttl?page=1",
              "last": ABOUT["url"] + ".ttl?page=1"}
    graph = dcat.catalog_graph(rows, ABOUT, profile, paging)
    assert problems(graph, profile) == []
    assert len(set(graph.subjects(RDF.type, DCAT.Dataset))) == 3


def test_the_shapes_do_reject_a_bad_graph():
    # Guards against a check that passes because it checks nothing.
    graph = dcat.record_graph(example(EXAMPLES[0]), "https://catalog.example/records/1", CHANGED)
    dataset = next(graph.subjects(RDF.type, DCAT.Dataset))
    graph.remove((dataset, DCTERMS.title, None))
    graph.add((dataset, DCTERMS.publisher, Literal("not an agent")))
    found = problems(graph, "dcat_ap")
    assert any("title" in p for p in found) and any("publisher" in p for p in found)


def test_what_is_carried_across():
    g = dcat.record_graph(example("exampleCDIFDiscoveryComplete.json"), "https://catalog.example/records/1", CHANGED, "geodcat_ap")
    dataset = URIRef("https://example.org/completeDiscoveryDataset42")
    assert (dataset, DCTERMS.title, Literal("North Atlantic Deep Water Formation Observations 2015-2024")) in g
    assert (dataset, DCAT.landingPage, URIRef("https://example.org/datasets/nadw-observations")) in g
    assert (dataset, DCTERMS.creator, URIRef("https://orcid.org/0000-0001-5555-6666")) in g
    assert (dataset, dcat.GEODCAT.distributor, URIRef("https://ror.org/007hqnf44")) in g
    assert Literal("North Atlantic Deep Water") in set(g.objects(dataset, DCAT.keyword))
    downloads = set(g.objects(None, DCAT.downloadURL))
    assert URIRef("https://example.org/data/nadw-ctd-2015-2024.csv") in downloads and len(downloads) == 2
    licence = URIRef("https://creativecommons.org/licenses/by/4.0/")
    assert len(list(g.subjects(DCTERMS.license, licence))) == 2  # on each distribution
    boxes = [str(o) for o in g.objects(None, DCAT.bbox)]
    assert boxes == ["POLYGON((-60.0 53.0, -45.0 53.0, -45.0 65.0, -60.0 65.0, -60.0 53.0))"]
    assert [str(o) for o in g.objects(None, DCAT.startDate)] == ["2015-02-01"]
    record = URIRef("https://catalog.example/records/1")
    assert (record, RDF.type, DCAT.CatalogRecord) in g
    assert URIRef("https://w3id.org/cdif/discovery/2.0") in set(g.objects(record, DCTERMS.conformsTo))


def test_a_record_without_a_description_says_so_after_its_title():
    g = dcat.record_graph(example("exampleCDIFDiscoveryMinimal.json"), "https://catalog.example/records/1", CHANGED)
    dataset = URIRef("https://example.org/dataset/minimal-discovery-001")
    assert list(g.objects(dataset, DCTERMS.description)) == [Literal("Sea water chemistry: description missing")]
    described = dcat.record_graph(example("exampleCDIFDiscoveryComplete.json"), "https://catalog.example/records/1", CHANGED)
    assert not [d for d in described.objects(None, DCTERMS.description) if "description missing" in d]


def test_plain_dcat_ap_leaves_out_the_geodcat_only_terms():
    g = dcat.record_graph(example("exampleCDIFDiscoveryComplete.json"), "https://catalog.example/records/1", CHANGED)
    assert not list(g.objects(None, dcat.GEODCAT.distributor))
    assert "schema:provider" in dcat.lost("dcat_ap") and "schema:provider" not in dcat.lost("geodcat_ap")


def test_every_property_of_the_profile_is_mapped_or_declared_lost():
    # When the pinned schema gains a property, this fails until the table says what happens to it.
    declared = {row["cdif"] for row in dcat.table()}
    assert sorted(set(validate.load("CoreDiscovery")["fields"]) - declared) == []


@pytest.mark.parametrize("fmt", ["ttl", "jsonld", "xml"])
def test_every_format_reads_back_as_the_same_graph(fmt):
    g = dcat.record_graph(example("exampleCDIFDiscoveryMinimal.json"), "https://catalog.example/records/1", CHANGED)
    back = Graph().parse(data=dcat.serialize(g, fmt), format=dcat.FORMATS[fmt])
    assert len(back) == len(g)
