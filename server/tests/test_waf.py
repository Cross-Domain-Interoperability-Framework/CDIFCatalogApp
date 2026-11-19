"""The web folder harvester: links from a listing page, and each file's own modified date.

The nginx listing and the plain Apache list below are what nginx 1.31 and Apache 2.4 really sent
(19 November 2026, default settings). The IIS listing is written from IIS's documented output.
The harvester reads only the links, so the three need no separate handling."""
import httpx

from app.harvest.waf import WafHarvester, links, modified_date

BASE = "https://repo.example/records/"

NGINX = """<html><head><title>Index of /records/</title></head><body><h1>Index of /records/</h1><hr><pre><a href="../">../</a>
<a href="sub/">sub/</a>                                               29-Mar-2024 09:15                   -
<a href="a.json">a.json</a>                                             30-Mar-2024 12:01                1234
<a href="name%20with%20space.json">name with space.json</a>                               01-Feb-2023 00:00                  10
</pre><hr></body></html>"""

APACHE_PLAIN = """<html><head><title>Index of /records</title></head><body><h1>Index of /records</h1>
<ul><li><a href="/"> Parent Directory</a></li>
<li><a href="bad.json"> bad.json</a></li>
<li><a href="minimal.json"> minimal.json</a></li>
<li><a href="sub/"> sub/</a></li>
</ul>
</body></html>"""

APACHE_FANCY = """<pre><img src="/icons/blank.gif" alt="Icon "> <a href="?C=N;O=D">Name</a>  <a href="?C=M;O=A">Last modified</a><hr>
<img src="/icons/back.gif" alt="[PARENTDIR]"> <a href="/">Parent Directory</a>   -
<img src="/icons/unknown.gif" alt="[   ]"> <a href="a.json">a.json</a>   2024-03-30 12:01  1.2K
</pre>"""

IIS = """<pre><A HREF="/">[To Parent Directory]</A><br><br> 3/30/2024 12:01 PM         1234 <A HREF="/records/a.json">a.json</A><br> 3/29/2024  9:15 AM        &lt;dir&gt; <A HREF="/records/sub/">sub</A><br></pre>"""


def test_links_are_read_the_same_way_from_every_servers_listing():
    assert links(NGINX) == ["../", "sub/", "a.json", "name%20with%20space.json"]
    assert links(APACHE_PLAIN) == ["/", "bad.json", "minimal.json", "sub/"]
    assert links(APACHE_FANCY) == ["?C=N;O=D", "?C=M;O=A", "/", "a.json"]
    assert links(IIS) == ["/", "/records/a.json", "/records/sub/"]


def test_a_last_modified_header_becomes_sortable_text():
    assert modified_date("Sat, 30 Mar 2024 12:01:05 GMT") == "2024-03-30T12:01:05"
    assert modified_date("Sat, 30 Mar 2024 14:01:05 +0200") == "2024-03-30T12:01:05"  # another zone is brought to UTC
    assert modified_date(None) is None and modified_date("yesterday") is None


def folder(listings, dated=True, head_status=200):
    """A pretend server: `listings` maps a folder address to its page; every .json file exists."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append((request.method, url[len(BASE):]))
        if url in listings:
            return httpx.Response(200, text=listings[url])
        if request.method == "HEAD":
            headers = {"last-modified": "Sat, 30 Mar 2024 12:01:05 GMT"} if dated else {}
            return httpx.Response(head_status, headers=headers)
        return httpx.Response(200, text="{}")

    return httpx.Client(transport=httpx.MockTransport(handler)), asked


def gather(http, **config):
    harvester = WafHarvester()
    source = {"url": BASE, "config": harvester.validate_config(config)}
    return harvester.gather(source, None, http)


def test_gather_walks_subfolders_and_dates_each_file_without_downloading_it():
    http, asked = folder({BASE: NGINX, BASE + "sub/": '<a href="../">../</a><a href="deep.json">deep.json</a>'})
    found = gather(http)
    assert found.complete is True
    assert {i.identifier[len(BASE):]: i.modified for i in found.items} == {
        "a.json": "2024-03-30T12:01:05", "name%20with%20space.json": "2024-03-30T12:01:05",
        "sub/deep.json": "2024-03-30T12:01:05",
    }
    assert ("GET", "a.json") not in asked and ("HEAD", "a.json") in asked


def test_gather_stays_inside_the_folder_and_skips_other_file_types():
    page = (
        '<a href="/">up</a><a href="../other/x.json">sideways</a><a href="https://elsewhere.example/y.json">away</a>'
        '<a href="?C=N;O=D">sort</a><a href="notes.txt">notes</a><a href="a.json">a</a><a href="a.json#top">again</a>'
    )
    http, _ = folder({BASE: page})
    assert [i.identifier for i in gather(http).items] == [BASE + "a.json"]


def test_absolute_links_as_iis_writes_them_are_followed():
    http, _ = folder({BASE: IIS, BASE + "sub/": '<A HREF="/records/sub/deep.json">deep.json</A>'})
    assert sorted(i.identifier[len(BASE):] for i in gather(http).items) == ["a.json", "sub/deep.json"]


def test_depth_limits_how_far_down_the_walk_goes():
    http, _ = folder({BASE: NGINX, BASE + "sub/": '<a href="deep.json">deep.json</a>'})
    assert "sub/deep.json" not in [i.identifier[len(BASE):] for i in gather(http, depth=0).items]


def test_a_server_that_gives_no_date_or_refuses_the_question_leaves_the_file_undated():
    for http, _ in (folder({BASE: APACHE_PLAIN}, dated=False), folder({BASE: APACHE_PLAIN}, head_status=405)):
        assert {i.modified for i in gather(http).items} == {None}
