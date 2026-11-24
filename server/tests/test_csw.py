"""The CSW harvester: the list a catalogue gives a page at a time, and one record asked for by its identifier."""
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.harvest import HarvestError, Item, harvesters
from app.harvest.csw import CswHarvester, listed, request_url, unwrapped
from app.harvest.detect import detect

CATALOGUE = "https://catalogue.example/srv/eng/csw"
NS = (
    'xmlns:csw="http://www.opengis.net/cat/csw/2.0.2" xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:dct="http://purl.org/dc/terms/" xmlns:gmd="http://www.isotc211.org/2005/gmd"'
)
ISO = '<gmd:MD_Metadata xmlns:gmd="http://www.isotc211.org/2005/gmd"><gmd:fileIdentifier/></gmd:MD_Metadata>'


def page(records, following, matched):
    rows = "".join(
        f"<csw:SummaryRecord><dc:identifier>{i}</dc:identifier><dc:title>Record {i}</dc:title>"
        f"{f'<dct:modified>{m}</dct:modified>' if m else ''}</csw:SummaryRecord>"
        for i, m in records
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><csw:GetRecordsResponse {NS}><csw:SearchStatus/>'
        f'<csw:SearchResults numberOfRecordsMatched="{matched}" numberOfRecordsReturned="{len(records)}" '
        f'nextRecord="{following}">{rows}</csw:SearchResults></csw:GetRecordsResponse>'
    )


def catalogue(held):
    """A pretend catalogue holding `held`, a list of (identifier, modified). It answers the two
    requests the harvester makes and records the parameters of each."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        asked.append(q)
        if q["request"] == "GetRecords":
            start, size = int(q["startPosition"]), int(q["maxRecords"])
            rows = held[start - 1:start - 1 + size]
            following = start + size if start - 1 + size < len(held) else 0
            return httpx.Response(200, content=page(rows, following, len(held)).encode("utf-8"))
        body = f"<csw:GetRecordByIdResponse {NS}>{ISO if any(i == q['id'] for i, _ in held) else ''}</csw:GetRecordByIdResponse>"
        return httpx.Response(200, content=body.encode("utf-8"))

    return httpx.Client(transport=httpx.MockTransport(handler)), asked


def gather(http, url=CATALOGUE, **config):
    harvester = CswHarvester()
    return harvester.gather({"url": url, "config": harvester.validate_config(config)}, None, http)


def test_the_catalog_offers_csw_as_a_kind_of_source():
    assert harvesters()["csw"].title == "CSW catalogue"


def test_a_request_keeps_what_the_address_carries_except_a_request_of_its_own():
    url = request_url("https://maps.example/cgi?map=/a.map&SERVICE=CSW&request=GetCapabilities", request="GetRecords")
    assert parse_qs(urlsplit(url).query) == {"map": ["/a.map"], "service": ["CSW"], "version": ["2.0.2"], "request": ["GetRecords"]}


def test_the_list_is_read_a_page_at_a_time_with_each_records_date():
    held = [("a", "2024-03-30"), ("b", "2024-03-30T12:00:00Z"), ("c", None), ("d", None), ("e", None)]
    http, asked = catalogue(held)
    found = gather(http, page=2)
    assert {i.identifier: i.modified for i in found.items} == {
        "a": "2024-03-30T00:00:00", "b": "2024-03-30T12:00:00", "c": None, "d": None, "e": None,
    }
    assert found.complete is True
    assert [q["startPosition"] for q in asked] == ["1", "3", "5"]
    assert asked[0]["elementSetName"] == "summary" and asked[0]["typeNames"] == "csw:Record"


def test_a_list_cut_short_by_the_limit_is_not_called_complete():
    http, _ = catalogue([(str(n), None) for n in range(7)])
    found = gather(http, page=3, limit=4)
    assert len(found.items) == 4 and found.complete is False
    http, _ = catalogue([(str(n), None) for n in range(4)])
    assert gather(http, page=4, limit=4).complete is True  # exactly as many as the catalogue holds


def test_a_catalogue_that_never_says_it_has_ended_is_not_asked_for_ever():
    def handler(request):  # always the same page, always pointing at the same place
        return httpx.Response(200, content=page([("a", None)], 1, 1).encode("utf-8"))

    assert len(gather(httpx.Client(transport=httpx.MockTransport(handler))).items) == 1


def test_each_record_is_asked_for_in_the_form_the_setting_names():
    http, _ = catalogue([("a b/c", None)])
    asked = parse_qs(urlsplit(gather(http).items[0].url).query)
    assert asked["id"] == ["a b/c"] and asked["outputSchema"] == ["http://www.isotc211.org/2005/gmd"]
    assert asked["request"] == ["GetRecordById"] and asked["elementSetName"] == ["full"]
    asked = parse_qs(urlsplit(gather(http, schema="dublin-core").items[0].url).query)
    assert asked["outputSchema"] == ["http://www.opengis.net/cat/csw/2.0.2"]


def test_a_record_is_handed_on_without_the_wrapper_it_arrived_in():
    http, _ = catalogue([("a", None)])
    harvester = CswHarvester()
    item = gather(http).items[0]
    fetched = harvester.fetch({}, item, http)
    assert detect(fetched.content).format == "iso19139"
    dublin = f"<csw:GetRecordByIdResponse {NS}><csw:Record><dc:identifier>a</dc:identifier></csw:Record></csw:GetRecordByIdResponse>"
    assert detect(unwrapped(dublin.encode("utf-8"))).format == "dublin-core"
    assert detect(unwrapped(ISO.encode("utf-8"))).format == "iso19139"  # sent bare


def test_a_record_the_catalogue_lists_and_will_not_give_is_reported_in_words():
    http, _ = catalogue([])
    with pytest.raises(HarvestError, match="returned nothing"):
        CswHarvester().fetch({}, Item("gone", request_url(CATALOGUE, request="GetRecordById", id="gone")), http)


def test_the_catalogues_own_complaint_and_an_address_that_is_no_catalogue_are_said_in_words():
    report = (
        '<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows"><ows:Exception exceptionCode="InvalidParameterValue">'
        "<ows:ExceptionText>typeNames\n   is not known</ows:ExceptionText></ows:Exception></ows:ExceptionReport>"
    )
    with pytest.raises(HarvestError, match="refused the request: typeNames is not known"):
        listed(report.encode("utf-8"))
    with pytest.raises(HarvestError, match="does not answer as a CSW catalogue.*<html>"):
        listed(b"<html><body>Welcome</body></html>")
    with pytest.raises(HarvestError, match="not well-formed"):
        listed(b"<csw:GetRecordsResponse>")


def test_settings_that_make_no_sense_are_refused():
    for config, word in (({"schema": "fgdc"}, "schema"), ({"page": 0}, "page"), ({"limit": "all"}, "limit")):
        with pytest.raises(HarvestError, match=word):
            CswHarvester().validate_config(config)
