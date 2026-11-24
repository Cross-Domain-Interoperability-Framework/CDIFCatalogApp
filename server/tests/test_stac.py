"""The STAC harvester: the collections of a STAC service, of a list of collections, and of a catalogue file."""
import json

import httpx
import pytest

from app.harvest import HarvestError, Item, harvesters
from app.harvest.detect import detect
from app.harvest.stac import StacHarvester

API = "https://stac.example/v1"
FILES = "https://files.example/stac/"


def collection(name, links=(), **more):
    return {
        "type": "Collection", "stac_version": "1.0.0", "id": name, "description": f"The {name} collection", "license": "CC-BY-4.0",
        "extent": {"spatial": {"bbox": [[-180, -90, 180, 90]]}, "temporal": {"interval": [["2020-01-01T00:00:00Z", None]]}},
        "links": list(links), **more,
    }


def site(answers):
    """A pretend site: `answers` maps an address to the JSON it gives (or text, sent as it is)."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if url not in answers:
            return httpx.Response(404)
        body = answers[url]
        return httpx.Response(200, content=(body if isinstance(body, str) else json.dumps(body)).encode("utf-8"), headers={"content-type": "application/json"})

    return httpx.Client(transport=httpx.MockTransport(handler)), asked


def gather(http, url, **config):
    harvester = StacHarvester()
    return harvester.gather({"url": url, "config": harvester.validate_config(config)}, None, http)


def service():
    """A STAC service with three collections over two pages. The first page of the list is also
    what its landing page's "data" link leads to."""
    own = lambda name: [{"rel": "self", "href": f"{API}/collections/{name}"}]  # noqa: E731
    return {
        API: {"type": "Catalog", "id": "svc", "links": [
            {"rel": "data", "href": f"{API}/collections"}, {"rel": "child", "href": f"{API}/collections/a"}, {"rel": "search", "href": f"{API}/search"},
        ]},
        f"{API}/collections": {"collections": [collection("a", own("a"), updated="2024-03-30T12:00:00Z"), collection("b", own("b"))],
                               "links": [{"rel": "next", "href": f"{API}/collections?page=2"}]},
        f"{API}/collections?page=2": {"collections": [collection("c d")], "links": []},
        f"{API}/collections/a": collection("a", own("a")),
    }


def test_the_catalog_offers_stac_as_a_kind_of_source():
    assert harvesters()["stac"].title == "STAC catalogue"


def test_a_stac_service_is_read_from_its_list_of_collections_page_by_page():
    http, asked = site(service())
    found = gather(http, API)
    assert {i.identifier: i.modified for i in found.items} == {
        f"{API}/collections/a": "2024-03-30T12:00:00", f"{API}/collections/b": None,
        f"{API}/collections/c%20d": None,  # no link of its own: its address is built from its id
    }
    assert found.complete is True
    assert asked == [API, f"{API}/collections", f"{API}/collections?page=2"]  # no collection fetched one by one


def test_the_address_of_the_list_itself_works_too():
    http, _ = site(service())
    assert len(gather(http, f"{API}/collections").items) == 3


def test_a_catalogue_file_is_followed_through_its_child_links_and_items_are_left_alone():
    http, asked = site({
        FILES + "catalog.json": {"type": "Catalog", "id": "root", "links": [
            {"rel": "child", "href": "./rocks/collection.json"}, {"rel": "child", "href": "sub/catalog.json"},
            {"rel": "item", "href": "./loose-item.json"}, {"rel": "self", "href": FILES + "catalog.json"},
        ]},
        FILES + "rocks/collection.json": collection("rocks", [{"rel": "item", "href": "./scene-1.json"}, {"rel": "child", "href": "./thin/collection.json"}]),
        FILES + "rocks/thin/collection.json": collection("thin-sections"),
        FILES + "sub/catalog.json": {"type": "Catalog", "id": "sub", "links": [{"rel": "child", "href": "../maps/collection.json"}, {"rel": "parent", "href": "../catalog.json"}]},
        FILES + "maps/collection.json": collection("maps"),
    })
    found = gather(http, FILES + "catalog.json")
    assert sorted(i.identifier for i in found.items) == [FILES + "maps/collection.json", FILES + "rocks/collection.json", FILES + "rocks/thin/collection.json"]
    assert not any("item" in url or "scene" in url for url in asked)
    assert [i.identifier for i in gather(http, FILES + "catalog.json", depth=1).items] == [FILES + "rocks/collection.json"]


def test_one_collection_given_by_its_own_address_is_taken():
    http, _ = site({FILES + "maps/collection.json": collection("maps")})
    assert [i.identifier for i in gather(http, FILES + "maps/collection.json").items] == [FILES + "maps/collection.json"]


def test_a_list_cut_short_by_the_limit_is_not_called_complete():
    http, _ = site(service())
    found = gather(http, API, limit=2)
    assert len(found.items) == 2 and found.complete is False
    assert gather(http, API, limit=3).complete is True  # exactly as many as there are


def test_an_address_that_is_no_stac_catalogue_is_said_so_in_words():
    http, _ = site({API: "<html><body>Welcome</body></html>", API + "/x": {"hello": "world"}, API + "/y": [1, 2]})
    with pytest.raises(HarvestError, match="does not answer with JSON"):
        gather(http, API)
    with pytest.raises(HarvestError, match="holds no STAC collection"):
        gather(http, API + "/x")
    with pytest.raises(HarvestError, match="JSON list"):
        gather(http, API + "/y")


def test_a_child_the_catalogue_names_and_the_site_does_not_have_fails_the_run():
    http, _ = site({FILES + "catalog.json": {"type": "Catalog", "links": [{"rel": "child", "href": "gone.json"}]}})
    with pytest.raises(httpx.HTTPStatusError):
        gather(http, FILES + "catalog.json")


def test_settings_that_make_no_sense_are_refused():
    for config, word in (({"depth": -1}, "depth"), ({"limit": 0}, "limit")):
        with pytest.raises(HarvestError, match=word):
            StacHarvester().validate_config(config)


def test_fetch_hands_on_the_collection_as_the_site_sends_it():
    http, _ = site(service())
    fetched = StacHarvester().fetch({}, Item(f"{API}/collections/a", f"{API}/collections/a"), http)
    assert json.loads(fetched.content)["id"] == "a" and detect(fetched.content).format == "stac"
