"""Harvests a sitemap: the file a site publishes to list its pages, each with the date it last
changed.

The sitemap gives the list and the dates, so a page that has not changed since the last run is
not fetched. A sitemap may be an index of other sitemaps; those are followed. Each address it
lists is either a metadata file, taken as it is, or a web page. A page carries its metadata the
way science-on-schema.org asks: as JSON-LD inside a `<script type="application/ld+json">`
element. That is taken out of the page and handed on like any other file; what it is, is
worked out from its content as always.

A sitemap lists every page of a site, and most pages of most sites describe no dataset. The
`only` setting keeps the addresses that hold a given piece of text, such as "/dataset/".
"""
import gzip
import json
import re
from datetime import datetime, timezone
from html import unescape
from xml.etree import ElementTree

from app.harvest import Disallowed, Fetched, Gathered, Harvester, HarvestError, Item

_SCRIPT = re.compile(
    r'<script\b[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>', re.IGNORECASE | re.DOTALL
)
_DATASET = re.compile(r"(^|[/:#])Dataset$")


def lastmod_date(text: str | None) -> str | None:
    """A sitemap's `lastmod` as ISO text in UTC, so two of them compare correctly as text. The
    sitemap standard allows a date alone, or a date and time with a zone."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    return when.replace(tzinfo=None).isoformat(timespec="seconds")


def entries(xml: str) -> tuple[str, list[tuple[str, str | None]]]:
    """What a sitemap file lists: ("pages" or "sitemaps", [(address, lastmod), ...])."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise HarvestError(f"The sitemap is not well-formed XML: {error}")
    local = lambda element: element.tag.rsplit("}", 1)[-1]  # noqa: E731  the namespace varies by site
    kind = {"urlset": "pages", "sitemapindex": "sitemaps"}.get(local(root))
    if kind is None:
        raise HarvestError(f"The address does not answer with a sitemap: its outermost element is <{local(root)}>.")
    found = []
    for entry in root:
        values = {local(child): (child.text or "").strip() for child in entry}
        if values.get("loc"):
            found.append((values["loc"], values.get("lastmod") or None))
    return kind, found


def _is_dataset(node) -> bool:
    types = node.get("@type") if isinstance(node, dict) else None
    return any(isinstance(t, str) and _DATASET.search(t) for t in (types if isinstance(types, list) else [types]))


def embedded_metadata(html: str) -> str:
    """The JSON-LD a web page carries about its dataset, as text. A page may hold several blocks
    (one for the site, one for the breadcrumb trail); the one describing a dataset is wanted."""
    blocks = []
    for raw in _SCRIPT.findall(html):
        try:
            blocks.append(json.loads(unescape(raw).strip()))
        except ValueError:
            continue  # a block that is not JSON is not ours to mend
    if not blocks:
        raise HarvestError("The page holds no embedded metadata: no script of type application/ld+json.")
    for block in blocks:
        # A list of things, one of them the dataset: take that one.
        for node in block if isinstance(block, list) else [block]:
            if _is_dataset(node):
                return json.dumps(node)
        # A graph of nodes with a dataset among them is passed whole: its parts refer to each other.
        if isinstance(block, dict) and any(_is_dataset(n) for n in block.get("@graph") or []):
            return json.dumps(block)
    if len(blocks) == 1 and isinstance(blocks[0], dict):
        return json.dumps(blocks[0])  # not marked as a dataset; say what it is from its content
    raise HarvestError(f"The page holds {len(blocks)} blocks of embedded metadata and none describes a dataset.")


def _text(response) -> str:
    """A sitemap is often served compressed, as a .gz file the client does not unpack itself."""
    body = response.content
    return gzip.decompress(body).decode("utf-8", errors="replace") if body[:2] == b"\x1f\x8b" else response.text


class SitemapHarvester(Harvester):
    type = "sitemap"
    title = "Sitemap"

    def validate_config(self, config: dict) -> dict:
        out = {"only": "", "limit": 5000, **config}
        if not isinstance(out["only"], str):
            raise HarvestError("only must be text that the wanted addresses hold, such as /dataset/.")
        if not isinstance(out["limit"], int) or not 1 <= out["limit"] <= 100000:
            raise HarvestError("limit must be a whole number from 1 to 100000.")
        return out

    def gather(self, source: dict, since, http) -> Gathered:
        # A sitemap is always the whole list, so `since` is not needed: a page whose date has not
        # moved is left alone, and one no longer listed is known to be gone.
        config = source["config"]
        pages, visited = {}, set()

        def walk(url: str, depth: int) -> None:
            if url in visited or len(pages) >= config["limit"]:
                return
            visited.add(url)
            response = http.get(url)
            response.raise_for_status()
            kind, found = entries(_text(response))
            for address, lastmod in found:
                if kind == "sitemaps":
                    if depth < 3:
                        try:
                            walk(address, depth + 1)
                        except Disallowed:
                            pass  # robots.txt closes this part of the sitemap: harvest the rest
                elif config["only"] in address and len(pages) < config["limit"]:
                    pages.setdefault(address, lastmod_date(lastmod))

        walk(source["url"], 0)
        # Stopped by the limit, the list may not be everything: nothing is withdrawn on its word.
        return Gathered(items=[Item(identifier=u, url=u, modified=m) for u, m in pages.items()], complete=len(pages) < config["limit"])

    def fetch(self, source: dict, item: Item, http) -> Fetched:
        response = http.get(item.url)
        response.raise_for_status()
        media = response.headers.get("content-type")
        text = response.text
        if "html" in (media or "").lower() or text.lstrip()[:15].lower().startswith(("<!doctype html", "<html")):
            return Fetched(content=embedded_metadata(text), content_type="application/ld+json")
        return Fetched(content=text, content_type=media)
