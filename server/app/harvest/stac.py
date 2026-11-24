"""Harvests the collections of a STAC catalogue, the JSON layout used for satellite imagery and
other data laid out in space and time (Earth Search, Microsoft Planetary Computer, NASA CMR).

A collection describes a dataset; the items inside it are its single scenes or files, often
millions of them, and are not harvested. The address given may be any of three things, told
apart by what answers:

  a STAC service    its first page points at a list of collections, which is read page by page
  a list of collections    read the same way
  a catalogue file    its "child" links are followed, and each collection found is taken

A collection rarely says when it last changed, so each is fetched on every run and recognised
as unchanged by its content. The list is always everything the catalogue holds, so a collection
no longer listed is known to be gone.
"""
import json
from urllib.parse import quote, urljoin

from app.harvest import Disallowed, Fetched, Gathered, Harvester, HarvestError, Item
from app.harvest.sitemap import lastmod_date


def _links(document: dict, rel: str, base: str) -> list[str]:
    found = []
    for link in document.get("links") or []:
        if isinstance(link, dict) and link.get("rel") == rel and isinstance(link.get("href"), str):
            found.append(urljoin(base, link["href"]))
    return found


def _is_collection(document: dict) -> bool:
    return document.get("type") == "Collection" or ("extent" in document and "id" in document)


def _changed(collection: dict) -> str | None:
    updated = collection.get("updated")
    return lastmod_date(updated) if isinstance(updated, str) else None


def _json(response, url: str) -> dict:
    try:
        document = json.loads(response.text)
    except ValueError:
        raise HarvestError(f"{url} does not answer with JSON, so it is not a STAC catalogue.")
    if not isinstance(document, dict):
        raise HarvestError(f"{url} answers with a JSON list where a STAC catalogue or collection is expected.")
    return document


class StacHarvester(Harvester):
    type = "stac"
    title = "STAC catalogue"

    def validate_config(self, config: dict) -> dict:
        out = {"depth": 3, "limit": 5000, **config}
        if not isinstance(out["depth"], int) or not 0 <= out["depth"] <= 10:
            raise HarvestError("depth must be a whole number from 0 to 10.")
        if not isinstance(out["limit"], int) or not 1 <= out["limit"] <= 100000:
            raise HarvestError("limit must be a whole number from 1 to 100000.")
        return out

    def gather(self, source: dict, since, http) -> Gathered:
        # The whole catalogue is walked each time, so `since` is not needed: a collection that
        # has not changed is recognised by its content, and one no longer listed is known to be gone.
        config = source["config"]
        found, visited = {}, set()
        cut = False

        def add(url: str, modified) -> None:
            nonlocal cut
            if len(found) < config["limit"]:
                found.setdefault(url, modified)
            elif url not in found:
                cut = True

        def walk(url: str, depth: int) -> None:
            if url in visited or cut:
                return
            visited.add(url)
            response = http.get(url)
            response.raise_for_status()
            document = _json(response, url)
            if isinstance(document.get("collections"), list):
                # a list of collections, each given whole; a "next" link leads to the rest
                for collection in document["collections"]:
                    if isinstance(collection, dict) and collection.get("id") is not None:
                        own = _links(collection, "self", url) or [url.split("?")[0].rstrip("/") + "/" + quote(str(collection["id"]), safe="")]
                        add(own[0], _changed(collection))
                for following in _links(document, "next", url)[:1]:
                    walk(following, depth)
                return
            if _is_collection(document):
                add(url, _changed(document))
            listing = _links(document, "data", url)
            if listing:
                walk(listing[0], depth)  # a STAC service: its list of collections says it all
                return
            if depth < config["depth"]:
                for child in _links(document, "child", url):
                    try:
                        walk(child, depth + 1)
                    except Disallowed:
                        pass  # robots.txt closes this part of the catalogue: harvest the rest

        walk(source["url"], 0)
        if not found and len(visited) == 1:
            raise HarvestError("The address holds no STAC collection and leads to none: it has no collections, no list of them and no child links.")
        items = [Item(identifier=url, url=url, modified=modified) for url, modified in found.items()]
        # Stopped by the limit, the list is not everything: nothing may be withdrawn on its word.
        return Gathered(items=items, complete=not cut)

    def fetch(self, source: dict, item: Item, http) -> Fetched:
        response = http.get(item.url)
        response.raise_for_status()
        return Fetched(content=response.text, content_type=response.headers.get("content-type"))
