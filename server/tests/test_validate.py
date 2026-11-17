"""The validation endpoint, against the profile's own examples and failing cases (copied from
metadataBuildingBlocks into fixtures/) and against records shaped the way the form produces them."""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import validate
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures" / "CoreDiscovery"
FORM_DEFAULTS = Path(__file__).parent / "fixtures" / "form-defaults.json"
SPEC = validate.load("CoreDiscovery")


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def violations(findings, prop=None):
    return [f for f in findings if f["severity"] == "violation" and (prop is None or f["path"][:1] == [prop])]


@pytest.mark.parametrize(
    "name", ["exampleCDIFDiscovery.json", "exampleCDIFDiscoveryComplete.json", "exampleCDIFDiscoveryMinimal.json"]
)
def test_the_profiles_own_examples_pass_unaltered(name):
    record = fixture(name)
    assert validate.schema_findings(SPEC, record) == []
    assert violations(validate.shacl_findings(SPEC, record)) == []


@pytest.mark.parametrize("name, prop", [("name-fail.json", "schema:name"), ("description-fail.json", "schema:description")])
def test_failing_cases_fail_for_their_named_reason(name, prop):
    found = validate.schema_findings(SPEC, fixture(name))
    assert [f["path"] for f in found] == [[prop]]
    assert found[0]["message"] == "should be text"


def blank():
    return json.loads(FORM_DEFAULTS.read_text(encoding="utf-8"))


def filled():
    doc = blank()
    doc.update({
        "schema:name": "Zircon ages",
        "schema:identifier": "https://doi.org/10.5555/x",
        "schema:dateModified": "2024-03-30",
        "schema:url": "https://repository.example/1",
        "schema:description": "Ages of 40 zircons.",
        "schema:keywords": ["zircon"],
        # shapes the pickers and the DOI pre-fill write: a type as one word, not a list
        "schema:creator": {"@list": [
            {"@type": "schema:Person", "schema:name": "María Ortiz",
             "schema:identifier": "https://orcid.org/0000-0002-1825-0097",
             "schema:affiliation": {"@type": "schema:Organization", "schema:name": "Example University"}},
            {"@type": "schema:Person"},  # a row added by hand and left empty
        ]},
        "schema:publisher": {"@type": "schema:Organization", "schema:name": "Repo", "schema:identifier": "https://ror.org/035a68863"},
        "schema:license": [{"@type": "schema:CreativeWork", "schema:name": "CC BY 4.0",
                            "schema:url": "https://creativecommons.org/licenses/by/4.0/"}],
        "schema:contributor": [{"@type": "schema:Person", "schema:name": "K Lee", "schema:roleName": "editor"}],
        "schema:funding": [{"schema:funder": {"@type": "schema:Organization", "schema:name": "NSF"}}],
    })
    return doc


def test_a_blank_form_is_invalid_and_every_violation_points_at_a_field():
    report = validate.check("CoreDiscovery", blank())
    assert report["valid"] is False
    bad = violations(report["findings"])
    assert all(f["property"] for f in bad)
    assert {f["property"] for f in bad} >= {"schema:name", "schema:identifier", "schema:dateModified", "schema:license"}
    # one finding per problem: the schema and the rules both notice a missing name
    assert len(violations(report["findings"], "schema:name")) == 1
    # nothing the author cannot see or fix is reported
    assert not [f for f in report["findings"] if f["property"] in ("@id", "@context", "schema:subjectOf")]


def test_a_record_filled_in_through_the_form_is_valid():
    report = validate.check("CoreDiscovery", filled())
    assert violations(report["findings"]) == []
    assert report["valid"] is True
    authors = report["record"]["schema:creator"]["@list"]
    assert len(authors) == 1 and authors[0]["@type"] == ["schema:Person"]  # empty row dropped, type made a list


def test_either_a_landing_page_or_a_distribution_is_reported_once():
    doc = filled()
    del doc["schema:url"]
    found = violations(validate.check("CoreDiscovery", doc)["findings"])
    assert len(found) == 1 and "schema:distribution" in found[0]["message"] and found[0]["property"] == "schema:url"


def test_a_nested_problem_says_where():
    doc = filled()
    doc["schema:license"][0]["schema:url"] = "not an address"
    doc["schema:dateModified"] = "last spring"
    found = violations(validate.check("CoreDiscovery", doc)["findings"])
    assert any("date" in f["message"].lower() for f in found if f["property"] == "schema:dateModified")
    # the schema and the rules both object to the address; it is reported once, with its place
    assert [f["where"] for f in found if f["path"][-1] == "schema:url"] == ["entry 1, url"]


def test_the_server_writes_the_catalog_record_and_reads_conformance_from_the_schema():
    doc = filled()
    doc["@context"]["schema"] = "https://schema.org/"  # the wrong form; it makes a record read as empty
    doc["schema:subjectOf"] = {"dcterms:conformsTo": [{"@id": "https://example.org/made-up"}],
                               "schema:maintainer": {"@type": "schema:Person", "schema:name": "A Curator"}}
    report = validate.check("CoreDiscovery", doc, "11111111-1111-1111-1111-111111111111")
    record = report["record"]
    assert report["valid"] is True
    assert record["@context"]["schema"] == "http://schema.org/"
    assert record["@id"] == "urn:uuid:11111111-1111-1111-1111-111111111111"
    about = record["schema:subjectOf"]
    assert about["schema:about"] == {"@id": record["@id"]}
    assert about["schema:maintainer"]["schema:name"] == "A Curator"  # the author's entry survives
    declared = [c["@id"] for c in about["dcterms:conformsTo"]]
    assert declared == SPEC["conformance"] and len(declared) == 2
    # no version number is written in the code: it comes from the pinned schema
    assert "/2.0" not in Path(validate.__file__).read_text(encoding="utf-8")


def test_strip_empty():
    assert validate.strip_empty({"a": "", "b": [], "c": {"@type": "x"}, "d": {"@list": []}}) is None
    assert validate.strip_empty({"a": " x ", "b": [{"@type": "T", "n": 0}]}) == {"a": " x ", "b": [{"@type": ["T"], "n": 0}]}


def test_endpoint():
    client = TestClient(app)
    ok = client.post("/api/validate", json={"profile": "CoreDiscovery", "document": filled()})
    assert ok.status_code == 200 and ok.json()["valid"] is True
    assert client.post("/api/validate", json={"profile": "../etc", "document": {}}).status_code == 422
    assert client.post("/api/validate", json={"profile": "Nope", "document": {}}).status_code == 422
