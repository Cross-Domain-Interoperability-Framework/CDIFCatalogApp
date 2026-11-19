"""Harvests a web-accessible folder: a directory listing page with one file per record.

Apache, nginx and IIS each write their listing differently, so each has its own parser, chosen
by the response's `Server` header. A listing's modified date lets an unchanged file be skipped
without fetching it.
"""
import re
from datetime import datetime
from html import unescape
from urllib.parse import urljoin, urlsplit

from app.harvest import Fetched, Gathered, Harvester, HarvestError, Item

FORMATS = {".json": "jsonld", ".jsonld": "jsonld", ".xml": "xml"}

_LINK = r'<a\s+href="(?P<href>[^"]+)"[^>]*>.*?</a>'
_FLAGS = re.IGNORECASE | re.DOTALL

# Apache: the date follows the link, either in the same <pre> line or in the next table cell.
#   <a href="a.json">a.json</a>      2024-03-30 12:01  1.2K
#   <td><a href="a.json">a.json</a></td><td align="right">2024-03-30 12:01  </td>
# Older Apache versions write the date as 30-Mar-2024 12:01.
_APACHE = re.compile(
    _LINK + r"(?:\s*</td>\s*<td[^>]*>)?\s*(?P<date>\d{4}-\d{2}-\d{2} \d{2}:\d{2}|\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2})?",
    _FLAGS,
)
# nginx: <a href="a.json">a.json</a>       30-Mar-2024 12:01      1234
_NGINX = re.compile(_LINK + r"\s*(?P<date>\d{2}-[A-Za-z]{3}-\d{4} \d{2}:\d{2})?", _FLAGS)
# IIS: the date comes before the link, in US order with AM or PM, and the address is absolute.
#   3/30/2024 12:01 PM         1234 <A HREF="/folder/a.json">a.json</A><br>
_IIS = re.compile(
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)\s+(?:&lt;dir&gt;|\d+)\s+" + _LINK, _FLAGS
)

_DATE_FORMATS = ("%Y-%m-%d %H:%M", "%d-%b-%Y %H:%M", "%m/%d/%Y %I:%M %p")


def _iso(text: str | None) -> str | None:
    """A listing's date as ISO text, so two of them compare correctly as text."""
    if not text:
        return None
    text = " ".join(text.split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).isoformat(timespec="minutes")
        except ValueError:
            pass
    return None


def _entries(pattern, html: str) -> list[tuple[str, str | None]]:
    return [(unescape(m.group("href")), _iso(m.group("date"))) for m in pattern.finditer(html)]


def parse_apache(html: str):
    return _entries(_APACHE, html)


def parse_nginx(html: str):
    return _entries(_NGINX, html)


def parse_iis(html: str):
    return _entries(_IIS, html)


def parser_for(server_header: str | None):
    """The parser for the server that wrote the listing, or None when the header does not say."""
    server = (server_header or "").lower()
    if "apache" in server:
        return parse_apache
    if "nginx" in server:
        return parse_nginx
    if "iis" in server:
        return parse_iis
    return None


def parse_listing(html: str, server_header: str | None = None):
    """[(href, modified or None)] for a listing page. With no usable Server header (a proxy
    often hides it), take whichever parser reads the most dated entries."""
    parser = parser_for(server_header)
    if parser:
        return parser(html)
    results = [p(html) for p in (parse_apache, parse_nginx, parse_iis)]
    return max(results, key=lambda entries: (sum(1 for _, d in entries if d), len(entries)))


class WafHarvester(Harvester):
    type = "waf"
    title = "Web folder"

    def validate_config(self, config: dict) -> dict:
        out = {"extensions": [".json", ".jsonld"], "depth": 3, **config}
        unknown = [e for e in out["extensions"] if e not in FORMATS]
        if unknown:
            raise HarvestError(f"Unknown file extensions: {', '.join(unknown)}. Known: {', '.join(FORMATS)}.")
        if not isinstance(out["depth"], int) or not 0 <= out["depth"] <= 10:
            raise HarvestError("depth must be a whole number from 0 to 10.")
        return out

    def gather(self, source: dict, since, http) -> Gathered:
        # A folder listing is always the whole folder, so `since` is not needed: unchanged files
        # are recognised by their listed date, and missing ones are known to be gone.
        base = source["url"] if source["url"].endswith("/") else source["url"] + "/"
        config = source["config"]
        items, visited = [], set()

        def walk(url: str, depth: int) -> None:
            if url in visited:
                return
            visited.add(url)
            response = http.get(url)
            response.raise_for_status()
            for href, modified in parse_listing(response.text, response.headers.get("server")):
                if href.startswith(("?", "#")):
                    continue  # column-sort links
                target = urljoin(url, href)
                if not target.startswith(base) or target == url or len(target) < len(url):
                    continue  # the parent folder, or somewhere else entirely
                if target.endswith("/"):
                    if depth < config["depth"]:
                        walk(target, depth + 1)
                elif any(urlsplit(target).path.lower().endswith(e) for e in config["extensions"]):
                    items.append(Item(identifier=target, url=target, modified=modified))

        walk(base, 0)
        return Gathered(items=items, complete=True)

    def fetch(self, source: dict, item: Item, http) -> Fetched:
        response = http.get(item.url)
        response.raise_for_status()
        path = urlsplit(item.url).path.lower()
        fmt = next(f for ext, f in FORMATS.items() if path.endswith(ext))
        return Fetched(content=response.text, format=fmt)
