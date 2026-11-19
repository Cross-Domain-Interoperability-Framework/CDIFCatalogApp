"""The directory-listing parsers.

The nginx listing and the plain Apache list below are what nginx 1.31 and Apache 2.4 really sent
(19 November 2026, default settings). The two dated Apache forms are written from Apache's
documented output and have not been checked against a live server."""
from app.harvest.waf import parse_apache, parse_listing, parse_nginx, parser_for

APACHE_PRE = """<html><body><h1>Index of /records</h1>
<pre><img src="/icons/blank.gif" alt="Icon "> <a href="?C=N;O=D">Name</a>                    <a href="?C=M;O=A">Last modified</a>      <a href="?C=S;O=A">Size</a>  <a href="?C=D;O=A">Description</a><hr><img src="/icons/back.gif" alt="[PARENTDIR]"> <a href="/">Parent Directory</a>                             -
<img src="/icons/unknown.gif" alt="[   ]"> <a href="a.json">a.json</a>                  2024-03-30 12:01  1.2K
<img src="/icons/folder.gif" alt="[DIR]"> <a href="sub/">sub/</a>                    2024-03-29 09:15    -
<hr></pre></body></html>"""

APACHE_TABLE = """<table><tr><th><a href="?C=N;O=D">Name</a></th><th><a href="?C=M;O=A">Last modified</a></th></tr>
<tr><td valign="top"><img src="/icons/back.gif" alt="[PARENTDIR]"></td><td><a href="/">Parent Directory</a></td><td>&nbsp;</td></tr>
<tr><td valign="top"><img src="/icons/unknown.gif" alt="[   ]"></td><td><a href="a.json">a.json</a></td><td align="right">2024-03-30 12:01  </td><td align="right">1.2K</td></tr>
</table>"""

NGINX = """<html><head><title>Index of /records/</title></head><body><h1>Index of /records/</h1><hr><pre><a href="../">../</a>
<a href="sub/">sub/</a>                                               29-Mar-2024 09:15                   -
<a href="a.json">a.json</a>                                             30-Mar-2024 12:01                1234
<a href="name%20with%20space.json">name with space.json</a>                               01-Feb-2023 00:00                  10
</pre><hr></body></html>"""

# Apache with no fancy indexing: a bare list with no dates, so every file is fetched each run.
APACHE_PLAIN = """<html><head><title>Index of /records</title></head><body><h1>Index of /records</h1>
<ul><li><a href="/"> Parent Directory</a></li>
<li><a href="bad.json"> bad.json</a></li>
<li><a href="minimal.json"> minimal.json</a></li>
<li><a href="sub/"> sub/</a></li>
</ul>
</body></html>"""

def test_apache_pre_listing():
    entries = dict(parse_apache(APACHE_PRE))
    assert entries["a.json"] == "2024-03-30T12:01"
    assert entries["sub/"] == "2024-03-29T09:15"
    assert entries["?C=N;O=D"] is None  # a sort link: listed, undated, and skipped by the harvester


def test_apache_table_listing():
    assert dict(parse_apache(APACHE_TABLE))["a.json"] == "2024-03-30T12:01"


def test_apache_plain_list_gives_the_files_without_dates():
    assert dict(parse_apache(APACHE_PLAIN)) == {"/": None, "bad.json": None, "minimal.json": None, "sub/": None}


def test_nginx_listing():
    entries = dict(parse_nginx(NGINX))
    assert entries["a.json"] == "2024-03-30T12:01"
    assert entries["name%20with%20space.json"] == "2023-02-01T00:00"
    assert entries["../"] is None


def test_the_server_header_chooses_the_parser():
    assert parser_for("Apache/2.4.58 (Ubuntu)") is parse_apache
    assert parser_for("nginx/1.25.3") is parse_nginx
    assert parser_for("cloudflare") is None and parser_for(None) is None
    assert parser_for("Microsoft-IIS/10.0") is None  # no IIS parser; see waf.py


def test_an_iis_listing_still_yields_its_links_but_no_dates():
    listing = '<pre> 3/30/2024 12:01 PM         1234 <A HREF="/records/a.json">a.json</A><br></pre>'
    assert dict(parse_listing(listing, "Microsoft-IIS/10.0")) == {"/records/a.json": None}


def test_without_a_server_header_the_parser_that_reads_the_dates_is_used():
    assert dict(parse_listing(APACHE_PRE, "cloudflare"))["a.json"] == "2024-03-30T12:01"
    assert dict(parse_listing(NGINX, None))["a.json"] == "2024-03-30T12:01"
