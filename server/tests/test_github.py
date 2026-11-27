"""The GitHub folder harvester: a repository folder listed through the Contents API, with each
file fetched from its raw address."""
import json

import httpx
import pytest

from app.harvest import HarvestError, harvesters
from app.harvest.github import GithubHarvester, parse

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com/org/repo/main"


def file_entry(name, folder="examples"):
    path = f"{folder}/{name}" if folder else name
    return {"type": "file", "name": name, "download_url": f"{RAW}/{path}"}


def dir_entry(name, ref="main"):
    return {"type": "dir", "name": name, "url": f"{API}/repos/org/repo/contents/examples/{name}?ref={ref}"}


def site(answers):
    """A pretend GitHub: `answers` maps an API address to the list (or dict) it returns, and every
    raw address answers with a small JSON file."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url)
        if url in answers:
            body = answers[url]
            return httpx.Response(200, content=json.dumps(body).encode("utf-8"), headers={"content-type": "application/json"})
        if url.startswith(RAW):
            return httpx.Response(200, text='{"@context": "https://schema.org/", "@type": "Dataset"}')
        return httpx.Response(404, content=b'{"message": "Not Found"}', headers={"content-type": "application/json"})

    return httpx.Client(transport=httpx.MockTransport(handler)), asked


def gather(http, url, **config):
    harvester = GithubHarvester()
    return harvester.gather({"url": url, "config": harvester.validate_config(config)}, None, http)


def test_the_catalog_offers_github_as_a_kind_of_source():
    assert harvesters()["github"].title == "GitHub folder"


def test_an_address_is_split_into_owner_repo_ref_and_path():
    assert parse("https://github.com/org/repo/tree/main/examples") == ("org", "repo", "main", "examples")
    assert parse("https://github.com/org/repo/tree/updates/examples/sub") == ("org", "repo", "updates", "examples/sub")
    assert parse("https://github.com/org/repo/tree/main") == ("org", "repo", "main", "")
    assert parse("https://github.com/org/repo") == ("org", "repo", None, "")
    assert parse("https://github.com/org/repo.git") == ("org", "repo", None, "")
    assert parse("https://github.com/org/repo/") == ("org", "repo", None, "")


def test_an_address_that_is_not_a_github_folder_is_refused():
    with pytest.raises(HarvestError):
        parse("https://gitlab.example/org/repo/tree/main")
    with pytest.raises(HarvestError):
        parse("https://github.com/org")  # not a repository
    with pytest.raises(HarvestError):
        parse("https://github.com/org/repo/blob/main/a.json")  # a single file, not a folder


def test_gather_lists_raw_file_addresses_and_walks_subfolders():
    http, asked = site({
        f"{API}/repos/org/repo/contents/examples?ref=main": [
            file_entry("a.json"), file_entry("b.xml"), file_entry("notes.txt"), dir_entry("sub"),
        ],
        f"{API}/repos/org/repo/contents/examples/sub?ref=main": [
            {"type": "file", "name": "deep.jsonld", "download_url": f"{RAW}/examples/sub/deep.jsonld"},
        ],
    })
    found = gather(http, "https://github.com/org/repo/tree/main/examples")
    assert found.complete is True
    # the .txt is left out; every other file is listed by its raw address, subfolders included
    assert {i.identifier for i in found.items} == {
        f"{RAW}/examples/a.json", f"{RAW}/examples/b.xml", f"{RAW}/examples/sub/deep.jsonld",
    }
    assert all(i.url == i.identifier and i.modified is None for i in found.items)


def test_depth_limits_how_far_down_the_walk_goes():
    http, _ = site({
        f"{API}/repos/org/repo/contents/examples?ref=main": [file_entry("a.json"), dir_entry("sub")],
        f"{API}/repos/org/repo/contents/examples/sub?ref=main": [
            {"type": "file", "name": "deep.json", "download_url": f"{RAW}/examples/sub/deep.json"},
        ],
    })
    found = gather(http, "https://github.com/org/repo/tree/main/examples", depth=0)
    assert {i.identifier for i in found.items} == {f"{RAW}/examples/a.json"}


def test_the_default_branch_and_root_are_used_when_no_tree_is_given():
    http, asked = site({f"{API}/repos/org/repo/contents": [file_entry("a.json", folder="")]})
    found = gather(http, "https://github.com/org/repo")
    assert asked == [f"{API}/repos/org/repo/contents"]  # no ?ref, no path
    assert [i.identifier for i in found.items] == [f"{RAW}/a.json"]


def test_a_file_address_rather_than_a_folder_is_refused():
    http, _ = site({f"{API}/repos/org/repo/contents/a.json?ref=main": {"type": "file", "name": "a.json"}})
    with pytest.raises(HarvestError, match="single file"):
        gather(http, "https://github.com/org/repo/tree/main/a.json")


def test_being_rate_limited_is_reported_in_plain_words():
    def handler(request):
        return httpx.Response(403, text='{"message": "API rate limit exceeded for 1.2.3.4"}')

    http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(HarvestError, match="rate-limiting"):
        gather(http, "https://github.com/org/repo/tree/main/examples")


def test_fetch_returns_the_raw_file():
    http, asked = site({f"{API}/repos/org/repo/contents/examples?ref=main": [file_entry("a.json")]})
    found = gather(http, "https://github.com/org/repo/tree/main/examples")
    fetched = GithubHarvester().fetch({}, found.items[0], http)
    assert '"@type": "Dataset"' in fetched.content
    assert asked[-1] == f"{RAW}/examples/a.json"
