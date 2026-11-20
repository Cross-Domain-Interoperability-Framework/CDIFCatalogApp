"""Recognising a harvested document from its content.

The snippets here are cut-down documents of each kind. The detector was also run over the
example files in the CDIF `converters` repository on 19 November 2026 (ISO 19139, 19115-2 and
19115-3, DataCite, Dublin Core, EML, FGDC, DDI, DDI-CDI, SDMX, OGC capabilities, DCAT in three
serialisations, Croissant, FAIR2, RO-Crate, UMM, NIAID), which is where its rules were tuned.
"""
import json
from pathlib import Path

import pytest

from app.harvest import HarvestError, convert
from app.harvest.detect import FORMATS, declared_conformance, detect

FIXTURES = Path(__file__).parent / "fixtures" / "CoreDiscovery"
CORE, DISCOVERY = "https://w3id.org/cdif/core/2.0", "https://w3id.org/cdif/discovery/2.0"


def ld(**node):
    return json.dumps({"@context": {"schema": "http://schema.org/", "dcterms": "http://purl.org/dc/terms/"}, **node})


def record(conforms_to):
    return {"@type": ["schema:Dataset"], "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
            "dcterms:conformsTo": [{"@id": uri} for uri in conforms_to]}


@pytest.mark.parametrize("name", ["exampleCDIFDiscoveryMinimal.json", "exampleCDIFDiscovery.json", "exampleCDIFDiscoveryComplete.json"])
def test_the_profile_examples_are_cdif_and_say_what_they_conform_to(name):
    found = detect((FIXTURES / name).read_text(encoding="utf-8"))
    assert found.format == "cdif-jsonld" and found.serialisation == "json-ld"
    assert {CORE, DISCOVERY} <= set(found.conforms_to)


def test_conformance_is_read_from_the_catalog_record_however_it_is_written():
    nested = {"schema:subjectOf": record([CORE, DISCOVERY])}
    assert declared_conformance(nested) == (CORE, DISCOVERY)
    # plain strings, an unprefixed context, and a list of catalog records
    assert declared_conformance({"subjectOf": [{"additionalType": "dcat:CatalogRecord", "conformsTo": CORE}]}) == (CORE,)
    # the catalog record as its own node in a graph
    graph = {"@graph": [{"@id": "d", "@type": "schema:Dataset"}, {"@id": "r", "@type": "dcat:CatalogRecord", "dcterms:conformsTo": {"@id": CORE}}]}
    assert declared_conformance(graph) == (CORE,)
    assert declared_conformance({"schema:name": "no catalog record"}) == ()


def test_json_ld_that_is_not_cdif_is_told_apart():
    assert detect(ld(**{"@type": "schema:Dataset", "schema:name": "x"})).format == "schemaorg-jsonld"
    assert detect(json.dumps({"@context": "https://schema.org/", "@type": "Dataset", "name": "x"})).format == "schemaorg-jsonld"
    assert detect(json.dumps({"@context": {"dcat": "http://www.w3.org/ns/dcat#"}, "@type": "dcat:Dataset"})).format == "dcat-jsonld"
    expanded = [{"@id": "https://x/d", "@type": ["http://www.w3.org/ns/dcat#Dataset"]}]
    assert detect(json.dumps(expanded)).format == "dcat-jsonld"
    croissant = {"@context": {"cr": "http://mlcommons.org/croissant/", "@vocab": "https://schema.org/"}, "@type": "Dataset"}
    assert detect(json.dumps(croissant)).format == "croissant"
    fair2 = {"@context": {**croissant["@context"], "fair2": "https://w3id.org/fair2/"}, "@graph": []}
    assert detect(json.dumps(fair2)).format == "fair2"
    crate = {"@context": "https://w3id.org/ro/crate/1.2/context", "@graph": [{"@id": "ro-crate-metadata.json"}]}
    assert detect(json.dumps(crate)).format == "rocrate"
    assert detect(json.dumps({"@context": {"ex": "https://example.org/"}, "@type": "ex:Thing"})).format == "jsonld-other"


def test_a_schema_org_record_that_declares_cdif_is_cdif():
    assert detect(ld(**{"@type": "schema:Dataset", "schema:subjectOf": record([CORE])})).format == "cdif-jsonld"


def test_plain_json_kinds():
    assert detect(json.dumps({"MetadataSpecification": {"URL": "https://cdn.earthdata.nasa.gov/umm/collection/v1.18"}})).format == "umm-c"
    assert detect(json.dumps({"hits": 1, "items": [{"meta": {}, "umm": {}}]})).format == "umm-c"
    assert detect(json.dumps({"stac_version": "1.0.0", "type": "Collection"})).format == "stac"
    assert detect(json.dumps({"data": {"attributes": {"doi": "10.1/x"}}})).format == "datacite-json"
    assert detect(json.dumps({"conformsTo": "https://project-open-data.cio.gov/v1.1/schema", "dataset": []})).format == "dcat-us-json"
    assert detect(json.dumps({"@type": "Dataset", "_id": "x", "name": "y"})).format == "niaid-json"
    other = detect(json.dumps({"alpha": 1, "beta": 2}))
    assert other.format == "json-other" and "alpha" in other.detail
    assert detect("{not json").format == "json-invalid"


XML = {
    "iso19139": '<gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"><gmd:fileIdentifier/></gmd:MD_Metadata>',
    "iso19115-2": '<gmi:MI_Metadata xmlns:gmi="http://www.isotc211.org/2005/gmi"/>',
    "iso19115-3": '<mdb:MD_Metadata xmlns:mdb="http://standards.iso.org/iso/19115/-3/mdb/2.0"/>',
    "csw-response": '<csw:GetRecordByIdResponse xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"/>',
    "dublin-core": '<csw:Record xmlns:csw="http://www.opengis.net/cat/csw/2.0.2" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>t</dc:title></csw:Record>',
    "fgdc": "<metadata><idinfo><citation/></idinfo></metadata>",
    "arcgis": "<metadata><Esri><CreaDate>20240101</CreaDate></Esri><dataIdInfo/></metadata>",
    "eml": '<eml:eml xmlns:eml="https://eml.ecoinformatics.org/eml-2.2.0"><dataset/></eml:eml>',
    "datacite-xml": '<resource xmlns="http://datacite.org/schema/kernel-4"><identifier/></resource>',
    "ddi-codebook-2.5": '<codeBook xmlns="ddi:codebook:2_5" version="2.5"/>',
    "ddi-1.2.2": '<codeBook version="1.2.2"><stdyDscr/></codeBook>',
    "ddi-lifecycle": '<DDIInstance xmlns="ddi:instance:3_2"/>',
    "ddicdi-xml": '<cdi:DDICDIModels xmlns:cdi="http://ddialliance.org/Specification/DDI-CDI/1.0/XMLSchema/"/>',
    "sdmx-ml": '<mes:Structure xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"/>',
    "oai-pmh-response": '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><responseDate/></OAI-PMH>',
    "ogc-capabilities": '<WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0"/>',
    "dcat-rdfxml": '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dcat="http://www.w3.org/ns/dcat#"><dcat:Dataset/></rdf:RDF>',
    "rdfxml-other": '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description/></rdf:RDF>',
}


@pytest.mark.parametrize("expected", sorted(XML))
def test_xml_formats_are_recognised_by_their_root_element_not_their_file_name(expected):
    text = '<?xml version="1.0" encoding="UTF-8"?>\n<!-- a comment first -->\n' + XML[expected]
    found = detect(text, content_type="application/octet-stream", url="https://x.example/record.dat")
    assert found.format == expected and found.serialisation == "xml"


def test_unrecognised_and_broken_xml_say_what_was_seen():
    other = detect('<thing xmlns="https://example.org/ns"/>')
    assert other.format == "xml-other" and "thing" in other.detail and "example.org/ns" in other.detail
    assert detect("<a><b></a>").format == "xml-invalid"


def test_only_the_start_of_an_xml_document_is_read():
    # the root says what it is; what follows, however large or broken, is not parsed
    assert detect(XML["iso19139"].replace("<gmd:fileIdentifier/>", "<a/>" * 100 + "<broken")).format == "iso19139"


def test_turtle_is_recognised_and_is_not_mistaken_for_xml():
    dcat = "@prefix dcat: <http://www.w3.org/ns/dcat#> .\n<https://x.example/d> a dcat:Dataset ."
    assert detect(dcat).format == "dcat-turtle"
    assert detect("<https://x.example/d> a <http://www.w3.org/ns/dcat#Dataset> .", url="https://x.example/d.ttl").format == "dcat-turtle"
    assert detect("PREFIX schema: <https://schema.org/>\n<https://x/d> a schema:Dataset .").format == "schemaorg-turtle"
    assert detect("@prefix ex: <https://example.org/> .\nex:a ex:b ex:c .", content_type="text/turtle").format == "turtle-other"


def test_text_that_is_none_of_these_is_unknown():
    assert detect("title,description\nA,B").format == "unknown"
    assert detect("").format == "unknown"


def test_every_format_has_a_label_and_converters_point_into_the_converters_repository():
    for fmt, (label, converter) in FORMATS.items():
        assert label and (converter is None or converter.endswith(".py")), fmt


def test_cdif_passes_straight_through_and_everything_else_says_why_not():
    text = (FIXTURES / "exampleCDIFDiscoveryMinimal.json").read_text(encoding="utf-8")
    assert convert.to_cdif(detect(text), text) == json.loads(text)
    with pytest.raises(HarvestError, match="DCAT RDF/XML.*DCAT/dcat_to_cdif.py.*not connected"):
        convert.to_cdif(detect(XML["dcat-rdfxml"]), XML["dcat-rdfxml"])
    with pytest.raises(HarvestError, match="FGDC CSDGM XML.*no converter"):
        convert.to_cdif(detect(XML["fgdc"]), XML["fgdc"])
    with pytest.raises(HarvestError, match="not valid JSON"):
        convert.to_cdif(detect("{not json"), "{not json")
