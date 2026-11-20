"""The converters from the CDIF `converters` repository, a git submodule at server/converters.

These tests need the submodule checked out and fail, not skip, without it. They run the real
converters on their own example files, so they also catch a submodule update that changes how a
converter is called.
"""
import json
from pathlib import Path

import pytest

from app import validate
from app.harvest import HarvestError, convert, converters
from app.harvest.detect import FORMATS, Detected, detect

ROOT = Path(__file__).parents[1] / "converters"


def example(folder: str, pattern: str) -> str:
    found = sorted((ROOT / folder).rglob(pattern))
    assert found, f"no {pattern} under server/converters/{folder}: run `git submodule update --init --recursive`"
    return found[0].read_text(encoding="utf-8")


def of_format(folder: str, pattern: str, fmt: str) -> str:
    for path in sorted((ROOT / folder).rglob(pattern)):
        text = path.read_text(encoding="utf-8", errors="replace")
        if detect(text).format == fmt:
            return text
    raise AssertionError(f"no {fmt} example under server/converters/{folder}")


def test_the_submodule_is_where_the_server_looks_for_it():
    assert converters.ROOT == ROOT and (ROOT / "ISO19115" / "iso_to_cdif.py").is_file()


def test_every_connected_format_is_one_the_detector_knows_and_names_a_converter_for():
    for fmt in converters.CONNECTED:
        assert FORMATS[fmt][1], fmt


@pytest.mark.parametrize("fmt", ["iso19139", "iso19115-2", "iso19115-3"])
def test_each_iso_flavour_converts_to_a_record_that_passes_the_profile(fmt):
    text = of_format("ISO19115/examples", "*.xml", fmt)
    record = validate.declare("CoreDiscovery", convert.to_cdif(detect(text), text))
    report = validate.check_record("CoreDiscovery", record)
    assert [f for f in report["findings"] if f["severity"] == "violation"] == []
    assert record["schema:name"] and record["@id"]


def test_a_ddi_cdi_xml_record_converts_to_a_record_that_passes_the_profile():
    text = of_format("DDI-CDI/Examples", "*.xml", "ddicdi-xml")
    record = validate.declare("CoreDiscovery", convert.to_cdif(detect(text), text))
    assert validate.check_record("CoreDiscovery", record)["valid"] is True


@pytest.mark.parametrize("folder, pattern, fmt", [
    ("soso", "*.json", "schemaorg-jsonld"),
    ("croissant", "*.jsonld", "croissant"),
    ("ROCrate", "*.json", "rocrate"),
    ("UMM/examples", "*.json", "umm-c"),
    ("DDI-CDI/Examples", "*.json", "ddicdi-jsonld"),
])
def test_the_other_connected_converters_run_and_return_one_record(folder, pattern, fmt):
    # These produce records that do not all pass the pinned CoreDiscovery profile yet; that is
    # recorded in docs/design.md. What is checked here is that each can be called and answers.
    text = of_format(folder, pattern, fmt)
    record = convert.to_cdif(detect(text), text)
    assert isinstance(record, dict) and "@graph" not in record and record.get("schema:name")
    validate.check_record("CoreDiscovery", validate.declare("CoreDiscovery", record))  # must not raise


def test_a_converter_that_fails_is_reported_in_words_not_as_a_crash(monkeypatch):
    def broken(content):
        raise KeyError("fileIdentifier")

    monkeypatch.setitem(convert.CONVERTERS, "iso19139", broken)
    with pytest.raises(HarvestError, match="ISO 19139 XML, but it could not be converted to CDIF: KeyError"):
        convert.to_cdif(Detected("iso19139", "xml"), "<x/>")


def test_a_converter_that_returns_a_graph_of_nodes_is_reported(monkeypatch):
    # the DDI converters do this: the dataset plus its code lists as separate nodes
    monkeypatch.setitem(convert.CONVERTERS, "ddi-1.2.2", lambda content: {"@context": {}, "@graph": [{}, {}, {}]})
    with pytest.raises(HarvestError, match="graph of 3 nodes"):
        convert.to_cdif(Detected("ddi-1.2.2", "xml"), "<codeBook/>")


def test_a_file_holding_several_iso_records_is_refused():
    one = of_format("ISO19115/examples", "*.xml", "iso19139").split("?>", 1)[-1]
    wrapped = f'<csw:GetRecordsResponse xmlns:csw="http://www.opengis.net/cat/csw/2.0.2">{one}{one}</csw:GetRecordsResponse>'
    assert detect(wrapped).format == "csw-response"
    with pytest.raises(HarvestError, match="holds 2 ISO metadata records"):
        convert.to_cdif(detect(wrapped), wrapped)


def test_a_csw_response_wrapping_one_iso_record_converts():
    one = of_format("ISO19115/examples", "*.xml", "iso19139").split("?>", 1)[-1]
    wrapped = f'<csw:GetRecordByIdResponse xmlns:csw="http://www.opengis.net/cat/csw/2.0.2">{one}</csw:GetRecordByIdResponse>'
    assert convert.to_cdif(detect(wrapped), wrapped)["schema:name"]


CORE, DISCOVERY = "https://w3id.org/cdif/core/2.0", "https://w3id.org/cdif/discovery/2.0"
DATASET = {
    "@context": {"schema": "http://schema.org/", "dcterms": "http://purl.org/dc/terms/", "dcat": "http://www.w3.org/ns/dcat#",
                 "prov": "http://www.w3.org/ns/prov#", "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/"},
    "@id": "https://example.org/d", "@type": ["schema:Dataset"], "schema:name": "A dataset",
    "schema:identifier": "https://example.org/d",
    "schema:subjectOf": {"@id": "https://example.org/d#metadata", "@type": ["schema:Dataset"],
                         "dcterms:conformsTo": [{"@id": "https://w3id.org/cdif/manifest/2.0"}, {"@id": "https://example.org/other"}]},
}


def test_the_levels_a_converted_record_claims_follow_its_content():
    assert converters.conformance(DATASET) == (CORE,)
    assert converters.conformance({**DATASET, "schema:temporalCoverage": ["2020/2021"]}) == (CORE, DISCOVERY)
    record, profile = convert.claim(json.loads(json.dumps(DATASET)), "CoreDiscovery")
    # the claim it arrived with is replaced; a claim that is not a CDIF level is kept
    assert [c["@id"] for c in record["schema:subjectOf"]["dcterms:conformsTo"]] == [CORE, "https://example.org/other"]
    assert profile == "cdifCore"
    record, profile = convert.claim({**json.loads(json.dumps(DATASET)), "schema:spatialCoverage": [{"schema:name": "Here"}]}, "CoreDiscovery")
    assert profile == "CoreDiscovery"


def test_a_level_whose_content_rules_are_broken_is_not_claimed():
    activity = {"@type": ["prov:Activity", "schema:Action"], "schema:actionProcess": {"@type": "schema:HowTo"}}
    with_activity = {**DATASET, "prov:wasGeneratedBy": [activity]}
    reached = converters.conformance(with_activity)
    module = converters._script("validation/detect_conformance.py")
    unchecked = tuple(module.detect_cdif_conformance(with_activity, do_shacl=False))
    assert "https://w3id.org/cdif/provenance/2.0" in unchecked  # its marks are there
    assert "https://w3id.org/cdif/provenance/2.0" not in reached  # but a method must have a name


def test_every_rule_file_the_detection_names_is_held_here_so_none_is_fetched():
    module = converters._script("validation/detect_conformance.py")
    named = sorted(c["shacl"] for c in module.CONFORMANCE_CLASSES if c["shacl"])
    assert named and [n for n in named if not (converters.SHAPES / n).is_file()] == []
    assert sorted(p.relative_to(converters.SHAPES).as_posix() for p in converters.SHAPES.rglob("*.shacl")) == named


def test_a_record_that_reaches_no_level_gets_the_fallback_claim_so_the_check_can_say_why():
    bare = {k: v for k, v in json.loads(json.dumps(DATASET)).items() if k != "schema:identifier"}
    record, profile = convert.claim(bare, "CoreDiscovery")
    assert profile == "CoreDiscovery"
    assert {CORE, DISCOVERY} <= {c["@id"] for c in record["schema:subjectOf"]["dcterms:conformsTo"]}


def test_declaring_conformance_adds_what_is_missing_and_keeps_what_is_there():
    record = {"schema:subjectOf": {"dcterms:conformsTo": [{"@id": "https://w3id.org/cdif/core/2.0"}, {"@id": "https://example.org/other"}]}}
    listed = [c["@id"] for c in validate.declare("CoreDiscovery", record)["schema:subjectOf"]["dcterms:conformsTo"]]
    assert listed == ["https://w3id.org/cdif/core/2.0", "https://example.org/other", "https://w3id.org/cdif/discovery/2.0"]
    assert validate.declare("CoreDiscovery", {"schema:name": "no catalog record"}) == {"schema:name": "no catalog record"}


def test_a_record_with_no_identifier_or_prefixes_is_reported_not_crashed_on():
    report = validate.check_record("CoreDiscovery", {"@type": ["schema:Dataset"], "schema:name": "Bare"})
    assert report["valid"] is False and any(f["property"] == "@id" for f in report["findings"])
