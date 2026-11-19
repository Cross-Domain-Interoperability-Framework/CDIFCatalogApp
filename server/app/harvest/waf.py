"""Harvests a web-accessible folder: a directory listing page with one file per record.

The listing page is read only for its links. Whether a file has changed is asked of the file
itself: a HEAD request returns its `Last-Modified` date without its content, and a file whose
date has not moved is not fetched. This works the same on every web server, so nothing here
depends on how Apache, nginx or IIS lay out a listing. The approach is the one Esri's Geoportal
harvester uses. (Parsers for each server's listing were written first and removed on
19 November 2026; they are in this file's history.)

A server that sends no `Last-Modified` gives no date, so its files are fetched on every run and
recognised as unchanged by their content.
"""
import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import urljoin, urlsplit

from app.harvest import Disallowed, Fetched, Gathered, Harvester, HarvestError, Item

# File types worth fetching. What each file actually is, is worked out from its content.
EXTENSIONS = [".json", ".jsonld", ".xml", ".ttl", ".rdf"]

_HREF = re.compile(r'<a\s[^>]*?href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def links(html: str) -> list[str]:
    """Every link on a listing page, as written."""
    return [unescape(href) for href in _HREF.findall(html)]


def modified_date(header: str | None) -> str | None:
    """A `Last-Modified` header as ISO text in UTC, so two of them compare correctly as text."""
    if not header:
        return None
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    return when.replace(tzinfo=None).isoformat(timespec="seconds")


class WafHarvester(Harvester):
    type = "waf"
    title = "Web folder"

    def validate_config(self, config: dict) -> dict:
        out = {"extensions": EXTENSIONS, "depth": 3, **config}
        extensions = out["extensions"]
        if not isinstance(extensions, list) or not extensions or not all(
            isinstance(e, str) and e.startswith(".") and len(e) > 1 for e in extensions
        ):
            raise HarvestError("extensions must be a list of file endings such as .json or .xml.")
        if not isinstance(out["depth"], int) or not 0 <= out["depth"] <= 10:
            raise HarvestError("depth must be a whole number from 0 to 10.")
        return out

    def gather(self, source: dict, since, http) -> Gathered:
        # A folder listing is always the whole folder, so `since` is not needed: unchanged files
        # are recognised by their own date, and missing ones are known to be gone.
        base = source["url"] if source["url"].endswith("/") else source["url"] + "/"
        config = source["config"]
        files, visited = [], set()

        def walk(url: str, depth: int) -> None:
            if url in visited:
                return
            visited.add(url)
            response = http.get(url)
            response.raise_for_status()
            for href in links(response.text):
                if href.startswith(("?", "#")):
                    continue  # column-sort links
                target = urljoin(url, href).split("#")[0]
                if not target.startswith(base) or target == url or len(target) < len(url):
                    continue  # the parent folder, or somewhere else entirely
                if target.endswith("/"):
                    if depth < config["depth"]:
                        try:
                            walk(target, depth + 1)
                        except Disallowed:
                            pass  # robots.txt closes this subfolder: leave it, harvest the rest
                elif target not in files and any(urlsplit(target).path.lower().endswith(e) for e in config["extensions"]):
                    files.append(target)

        walk(base, 0)
        items = []
        for url in files:
            try:
                items.append(Item(identifier=url, url=url, modified=self._modified(url, http)))
            except Disallowed:
                pass  # robots.txt closes this file
        return Gathered(items=items, complete=True)

    @staticmethod
    def _modified(url: str, http) -> str | None:
        """The file's own modified date, asked for without downloading it. A server that will not
        answer the question is not an error: the file is simply fetched."""
        try:
            response = http.head(url)
        except Disallowed:
            raise
        except Exception:
            return None
        return modified_date(response.headers.get("last-modified")) if response.status_code == 200 else None

    def fetch(self, source: dict, item: Item, http) -> Fetched:
        response = http.get(item.url)
        response.raise_for_status()
        return Fetched(content=response.text, content_type=response.headers.get("content-type"))
