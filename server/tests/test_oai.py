"""The OAI-PMH harvester: the identifiers a repository lists a batch at a time, and one record asked for by its identifier."""
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.harvest import HarvestError, Item, harvesters
from app.harvest.detect import detect
from app.harvest.oai import OaiHarvester, listed, request_url, unwrapped

REPOSITORY = "https://repo.example/oai"
OPEN = '<?xml version="1.0" encoding="UTF-8"?><OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><responseDate>2026-11-23T00:00:00Z</responseDate>'
DC = (
    '<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" xmlns:dc="http://purl.org/dc/elements/1.1/">'
    "<dc:title>Zircon ages</dc:title></oai_dc:dc>"
)


def header(identifier, stamp, deleted=False):
    return f"<header{' status=\"deleted\"' if deleted else ''}><identifier>{identifier}</identifier><datestamp>{stamp}</datestamp></header>"


def batch(headers, token=""):
    return f"{OPEN}<ListIdentifiers>{''.join(headers)}{f'<resumptionToken>{token}</resumptionToken>' if token is not None else ''}</ListIdentifiers></OAI-PMH>"


def record(identifier, inside=DC, deleted=False):
    metadata = "" if deleted else f"<metadata>{inside}</metadata>"
    return f"{OPEN}<GetRecord><record>{header(identifier, '2024-03-30', deleted)}{metadata}</record></GetRecord></OAI-PMH>"


def error(code, text=""):
    return f'{OPEN}<error code="{code}">{text}</error></OAI-PMH>'


def repository(batches, size=2):
    """A pretend repository holding `batches`, a list of (identifier, datestamp, deleted), handed
    out `size` at a time with a token for the rest. It records the arguments of each request."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}
        asked.append(q)
        if q["verb"] == "GetRecord":
            return httpx.Response(200, content=record(q["identifier"]).encode("utf-8"))
        start = int(q["resumptionToken"]) if "resumptionToken" in q else 0
        rows = batches[start:start + size]
        if not rows:
            return httpx.Response(200, content=error("noRecordsMatch").encode("utf-8"))
        token = str(start + size) if start + size < len(batches) else ""
        return httpx.Response(200, content=batch([header(*r) for r in rows], token).encode("utf-8"))

    return httpx.Client(transport=httpx.MockTransport(handler)), asked


def gather(http, url=REPOSITORY, **config):
    harvester = OaiHarvester()
    return harvester.gather({"url": url, "config": harvester.validate_config(config)}, None, http)


def test_the_catalog_offers_oai_pmh_as_a_kind_of_source():
    assert harvesters()["oai-pmh"].title == "OAI-PMH repository"


def test_a_request_keeps_what_the_address_carries_except_a_request_of_its_own():
    url = request_url("https://repo.example/oai?verb=Identify&key=abc", verb="ListIdentifiers", metadataPrefix="oai_dc")
    assert parse_qs(urlsplit(url).query) == {"key": ["abc"], "verb": ["ListIdentifiers"], "metadataPrefix": ["oai_dc"]}


def test_the_list_is_followed_batch_by_batch_and_deleted_records_are_left_out():
    held = [("a", "2024-03-30", False), ("b", "2024-03-30T12:00:00Z", False), ("c", "2024-01-01", True), ("d", "2023-01-01", False), ("e", "2023-01-02", False)]
    http, asked = repository(held)
    found = gather(http, set="geology")
    assert {i.identifier: i.modified for i in found.items} == {
        "a": "2024-03-30T00:00:00", "b": "2024-03-30T12:00:00", "d": "2023-01-01T00:00:00", "e": "2023-01-02T00:00:00",
    }
    assert found.complete is True
    assert asked[0] == {"verb": "ListIdentifiers", "metadataPrefix": "oai_dc", "set": "geology"}
    # a later batch is asked for by its token alone, as the protocol requires
    assert asked[1:] == [{"verb": "ListIdentifiers", "resumptionToken": "2"}, {"verb": "ListIdentifiers", "resumptionToken": "4"}]


def test_a_repository_with_nothing_to_list_gives_an_empty_complete_list():
    http, _ = repository([])
    found = gather(http)
    assert found.items == [] and found.complete is True


def test_a_list_cut_short_by_the_limit_is_not_called_complete():
    http, _ = repository([(str(n), "2024-01-01", False) for n in range(7)])
    found = gather(http, limit=3)
    assert len(found.items) == 3 and found.complete is False


def test_a_repository_that_repeats_its_token_is_not_asked_for_ever():
    def handler(request):
        return httpx.Response(200, content=batch([header("a", "2024-01-01")], "same").encode("utf-8"))

    assert len(gather(httpx.Client(transport=httpx.MockTransport(handler))).items) == 1


def test_each_record_is_asked_for_in_the_form_the_setting_names():
    http, _ = repository([("oai:repo.example:10/5 x", "2024-01-01", False)])
    asked = parse_qs(urlsplit(gather(http, prefix="datacite").items[0].url).query)
    assert asked == {"verb": ["GetRecord"], "identifier": ["oai:repo.example:10/5 x"], "metadataPrefix": ["datacite"]}


def test_a_record_is_handed_on_without_the_wrapper_it_arrived_in():
    http, _ = repository([("a", "2024-01-01", False)])
    fetched = OaiHarvester().fetch({}, gather(http).items[0], http)
    assert detect(fetched.content).format == "dublin-core"
    datacite = '<resource xmlns="http://datacite.org/schema/kernel-4"><identifier identifierType="DOI">10.5/x</identifier></resource>'
    assert detect(unwrapped(record("a", datacite).encode("utf-8"))).format == "datacite-xml"


def test_a_record_that_is_deleted_or_empty_is_reported_in_words():
    with pytest.raises(HarvestError, match="has been deleted"):
        unwrapped(record("a", deleted=True).encode("utf-8"))
    with pytest.raises(HarvestError, match="holds 0 metadata documents"):
        unwrapped(record("a", inside="").encode("utf-8"))
    with pytest.raises(HarvestError, match="idDoesNotExist: No such record"):
        unwrapped(error("idDoesNotExist", "No such\n  record").encode("utf-8"))


def test_the_repositorys_own_complaint_and_an_address_that_is_no_repository_are_said_in_words():
    with pytest.raises(HarvestError, match=r"refused the request \(cannotDisseminateFormat: no iso19139 here\)"):
        listed(error("cannotDisseminateFormat", "no iso19139 here").encode("utf-8"))
    with pytest.raises(HarvestError, match="does not answer as an OAI-PMH repository.*<html>"):
        listed(b"<html><body>Welcome</body></html>")
    with pytest.raises(HarvestError, match="not well-formed"):
        listed(b"<OAI-PMH>")


def test_settings_that_make_no_sense_are_refused():
    for config, word in (({"prefix": ""}, "prefix"), ({"set": 3}, "set"), ({"limit": 0}, "limit")):
        with pytest.raises(HarvestError, match=word):
            OaiHarvester().validate_config(config)


def test_fetch_needs_no_more_than_the_address_gathered():
    http, asked = repository([("a", "2024-01-01", False)])
    OaiHarvester().fetch({}, Item("a", request_url(REPOSITORY, verb="GetRecord", identifier="a", metadataPrefix="oai_dc")), http)
    assert asked[-1]["verb"] == "GetRecord"
