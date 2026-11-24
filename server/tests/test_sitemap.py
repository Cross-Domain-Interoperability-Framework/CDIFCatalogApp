"""The sitemap harvester: the list and dates from a sitemap, and the metadata embedded in a page."""
import gzip
import json

import httpx
import pytest

from app.harvest import HarvestError, harvesters
from app.harvest.detect import detect
from app.harvest.sitemap import SitemapHarvester, embedded_metadata, entries, lastmod_date

SITE = "https://repo.example/"
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def urlset(*pages):
    rows = "".join(f"<url><loc>{loc}</loc>{f'<lastmod>{mod}</lastmod>' if mod else ''}</url>" for loc, mod in pages)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset {NS}>{rows}</urlset>'


def index(*sitemaps):
    return f"<sitemapindex {NS}>" + "".join(f"<sitemap><loc>{s}</loc></sitemap>" for s in sitemaps) + "</sitemapindex>"


DATASET = {"@context": "https://schema.org/", "@type": "Dataset", "name": "Zircon ages", "url": SITE + "dataset/1"}
PAGE = (
    "<!DOCTYPE html><html><head><title>Zircon ages</title>"
    '<script type="application/ld+json">{"@context": "https://schema.org", "@type": "WebSite", "name": "Repo"}</script>'
    f'<script type="application/ld+json">\n{json.dumps(DATASET)}\n</script>'
    "</head><body><h1>Zircon ages</h1></body></html>"
)


def site(answers):
    """A pretend site: `answers` maps an address to (body, media type). Bytes are sent as they are."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if url not in answers:
            return httpx.Response(404)
        body, media = answers[url]
        content = body if isinstance(body, bytes) else body.encode("utf-8")
        return httpx.Response(200, content=content, headers={"content-type": media})

    return httpx.Client(transport=httpx.MockTransport(handler)), asked


def gather(http, url=SITE + "sitemap.xml", **config):
    harvester = SitemapHarvester()
    return harvester.gather({"url": url, "config": harvester.validate_config(config)}, None, http)


def test_the_catalog_offers_the_sitemap_as_a_kind_of_source():
    assert harvesters()["sitemap"].title == "Sitemap"


def test_a_lastmod_becomes_sortable_text_whichever_form_the_standard_allows():
    assert lastmod_date("2024-03-30") == "2024-03-30T00:00:00"
    assert lastmod_date("2024-03-30T14:01:05+02:00") == "2024-03-30T12:01:05"  # another zone is brought to UTC
    assert lastmod_date("2024-03-30T12:01:05Z") == "2024-03-30T12:01:05"
    assert lastmod_date(None) is None and lastmod_date("last week") is None


def test_a_sitemap_gives_each_page_and_its_date_without_fetching_the_pages():
    http, asked = site({SITE + "sitemap.xml": (urlset((SITE + "dataset/1", "2024-03-30"), (SITE + "dataset/2", None)), "application/xml")})
    found = gather(http)
    assert found.complete is True
    assert {i.identifier: i.modified for i in found.items} == {SITE + "dataset/1": "2024-03-30T00:00:00", SITE + "dataset/2": None}
    assert asked == [SITE + "sitemap.xml"]


def test_an_index_of_sitemaps_is_followed_and_a_compressed_one_is_unpacked():
    packed = gzip.compress(urlset((SITE + "dataset/2", "2024-01-01")).encode("utf-8"))
    http, _ = site({
        SITE + "sitemap.xml": (index(SITE + "a.xml", SITE + "b.xml.gz", SITE + "gone.xml"), "application/xml"),
        SITE + "a.xml": (urlset((SITE + "dataset/1", "2024-03-30")), "application/xml"),
        SITE + "b.xml.gz": (packed, "application/gzip"),
    })
    with pytest.raises(httpx.HTTPStatusError):  # a sitemap the index names and the site does not have
        gather(http)
    http, _ = site({
        SITE + "sitemap.xml": (index(SITE + "a.xml", SITE + "b.xml.gz"), "application/xml"),
        SITE + "a.xml": (urlset((SITE + "dataset/1", "2024-03-30")), "application/xml"),
        SITE + "b.xml.gz": (packed, "application/gzip"),
    })
    assert sorted(i.identifier for i in gather(http).items) == [SITE + "dataset/1", SITE + "dataset/2"]


def test_only_keeps_the_addresses_that_hold_the_text_and_limit_stops_the_list():
    pages = [(SITE + "about", None)] + [(f"{SITE}dataset/{n}", None) for n in range(5)]
    http, _ = site({SITE + "sitemap.xml": (urlset(*pages), "application/xml")})
    assert len(gather(http).items) == 6
    assert all("/dataset/" in i.identifier for i in gather(http, only="/dataset/").items)
    cut = gather(http, only="/dataset/", limit=2)
    assert len(cut.items) == 2 and cut.complete is False  # a list cut short withdraws nothing


def test_an_address_that_is_not_a_sitemap_is_said_so_in_words():
    http, _ = site({SITE + "sitemap.xml": ("<html><body>Not found</body></html>", "text/html")})
    with pytest.raises(HarvestError, match="does not answer with a sitemap"):
        gather(http)
    assert entries(urlset())[0] == "pages"
    with pytest.raises(HarvestError, match="not well-formed"):
        entries("<urlset><url>")


def test_settings_that_make_no_sense_are_refused():
    with pytest.raises(HarvestError, match="limit"):
        SitemapHarvester().validate_config({"limit": 0})
    with pytest.raises(HarvestError, match="only"):
        SitemapHarvester().validate_config({"only": ["/dataset/"]})


def test_the_dataset_block_is_taken_out_of_a_page_that_holds_several():
    record = json.loads(embedded_metadata(PAGE))
    assert record == DATASET
    assert detect(json.dumps(record)).format == "schemaorg-jsonld"


def test_a_dataset_inside_a_list_or_a_graph_is_found():
    in_list = f'<script type="application/ld+json">{json.dumps([{"@type": "Organization"}, DATASET])}</script>'
    assert json.loads(embedded_metadata(in_list)) == DATASET
    graph = {"@context": "https://schema.org/", "@graph": [{"@type": "Person", "@id": "#a"}, {**DATASET, "@type": ["schema:Dataset"]}]}
    in_graph = f"<script type='application/ld+json'>{json.dumps(graph)}</script>"
    assert json.loads(embedded_metadata(in_graph)) == graph


def test_a_page_with_no_metadata_or_none_about_a_dataset_is_reported_in_words():
    with pytest.raises(HarvestError, match="no embedded metadata"):
        embedded_metadata("<html><body>Nothing here</body></html>")
    two = '<script type="application/ld+json">{"@type": "WebSite"}</script>' * 2
    with pytest.raises(HarvestError, match="2 blocks.*none describes a dataset"):
        embedded_metadata(two)
    # the only block on the page is passed on even when it does not call itself a dataset
    assert json.loads(embedded_metadata('<script type="application/ld+json">{"@type": "WebSite"}</script>')) == {"@type": "WebSite"}


def test_fetch_hands_on_a_pages_metadata_and_a_files_own_content():
    http, _ = site({
        SITE + "dataset/1": (PAGE, "text/html; charset=utf-8"),
        SITE + "records/2.xml": ("<metadata><idinfo/></metadata>", "application/xml"),
    })
    harvester = SitemapHarvester()
    from app.harvest import Item

    page = harvester.fetch({}, Item(SITE + "dataset/1", SITE + "dataset/1"), http)
    assert json.loads(page.content) == DATASET and page.content_type == "application/ld+json"
    file = harvester.fetch({}, Item(SITE + "records/2.xml", SITE + "records/2.xml"), http)
    assert file.content == "<metadata><idinfo/></metadata>" and file.content_type == "application/xml"
