"""Harvests a DCAT catalogue: one document, or a run of pages, describing many datasets. This is
what open data portals publish for each other (CKAN's `/catalog.ttl`, a European portal's feed,
a United States agency's `data.json`), and what this catalog's own feed is.

A catalogue is not a list of addresses to fetch: the datasets are all inside it. So it is read
as a graph, in whichever of Turtle, RDF/XML or JSON-LD it comes, and each dataset is cut out of
it with everything that hangs from it (its downloads, its publisher, its contact). Each cut is
handed on as a small JSON-LD document of its own, written the same way every time so that an
unchanged dataset is recognised by its content.

Pages are followed by their Hydra "next" link, the paging CKAN's DCAT feed and this catalog's
use. The list is everything the catalogue holds, so a dataset no longer in it is known to be gone.
"""
import json
from urllib.parse import quote, urljoin

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import DCTERMS, RDF

from app.harvest import Fetched, Gathered, Harvester, HarvestError, Item
from app.harvest.detect import detect
from app.harvest.sitemap import lastmod_date

DCAT = "http://www.w3.org/ns/dcat#"
DATASET, CATALOG = URIRef(DCAT + "Dataset"), URIRef(DCAT + "Catalog")
_NEXT = (URIRef("http://www.w3.org/ns/hydra/core#next"), URIRef("http://www.w3.org/ns/hydra/core#nextPage"))
# A United States data.json names its context by this address, or leaves it out altogether.
_POD_CONTEXT = "https://project-open-data.cio.gov/v1.1/schema/catalog.jsonld"
_FORMATS = {"json-ld": "json-ld", "json": "json-ld", "xml": "xml", "turtle": "turtle"}
_DEPTH = 5  # how far from a dataset its description is followed


def _inline_contexts(document: dict, url: str, http) -> dict:
    """A JSON-LD context named by address is fetched here, with the client the harvester was
    given, and written into the document. Left alone, the parser would fetch it itself, behind
    the back of robots.txt."""
    named = document.get("@context")
    entries = named if isinstance(named, list) else [named]
    if not any(isinstance(entry, str) for entry in entries):
        return document
    inline = []
    for entry in entries:
        if isinstance(entry, str):
            response = http.get(urljoin(url, entry))
            response.raise_for_status()
            entry = response.json().get("@context", {})
        inline += entry if isinstance(entry, list) else [entry]
    return {**document, "@context": inline}


def read(text: str, media: str | None, url: str, http) -> Graph:
    """A catalogue page as a graph, whichever way it is written."""
    seen = detect(text, media, url)
    form = _FORMATS.get(seen.serialisation)
    if form is None:
        raise HarvestError(f"{url} is not a DCAT catalogue: it is neither JSON-LD, RDF/XML nor Turtle.")
    if form == "json-ld":
        document = json.loads(text)
        if isinstance(document, dict):
            if seen.format == "dcat-us-json" and "@context" not in document:
                document = {"@context": _POD_CONTEXT, **document}
            text = json.dumps(_inline_contexts(document, url, http))
    graph = Graph()
    try:
        graph.parse(data=text, format=form, publicID=url)
    except Exception as error:  # the parsers raise whatever they like
        raise HarvestError(f"{url} could not be read as a DCAT catalogue: {error}")
    return graph


def datasets(graph: Graph) -> dict:
    """Each dataset in the graph, by the identifier it is known by: its own address, or where it
    has none (as in a data.json) the identifier it states."""
    found = {}
    for node in graph.subjects(RDF.type, DATASET):
        if isinstance(node, URIRef):
            found.setdefault(str(node), node)
        else:
            stated = graph.value(node, DCTERMS.identifier)
            if stated is not None:
                found.setdefault(str(stated), node)
    return found


def _stable(value, in_list=False):
    """The same JSON for the same graph: keys in order, and values in order wherever their order
    carries no meaning (everywhere but inside an RDF list)."""
    if isinstance(value, dict):
        return {key: _stable(value[key], key == "@list") for key in sorted(value)}
    if isinstance(value, list):
        items = [_stable(item) for item in value]
        return items if in_list else sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def address(identifier: str, page: str) -> str:
    """The address a dataset is written under. One with none of its own (as in a data.json,
    where a dataset has only a short identifier) is addressed as a part of its catalogue; a
    record must have an address to be a CDIF record at all."""
    return identifier if identifier.startswith(("http://", "https://")) else f"{page.split('#')[0]}#{quote(identifier, safe='')}"


def cut(graph: Graph, node, named: str | None = None) -> str:
    """One dataset and what hangs from it, as expanded JSON-LD text. `named` is the address to
    write a dataset under when it has none of its own."""
    out, seen, waiting = Graph(), set(), [(node, 0)]
    while waiting:
        subject, depth = waiting.pop()
        if subject in seen:
            continue
        seen.add(subject)
        for predicate, value in graph.predicate_objects(subject):
            out.add((subject, predicate, value))
            if isinstance(value, Literal) or depth >= _DEPTH:
                continue
            # another dataset, or the catalogue itself, is referred to and not described again
            kinds = set(graph.objects(value, RDF.type))
            if isinstance(value, BNode) or not kinds & {DATASET, CATALOG}:
                waiting.append((value, depth + 1))
    if isinstance(node, BNode) and named:
        for predicate, value in list(out.predicate_objects(node)):
            out.remove((node, predicate, value))
            out.add((URIRef(named), predicate, value))
    # nodes with no address get the same labels every time, so the text does not change by itself
    return json.dumps(_stable(json.loads(to_canonical_graph(out).serialize(format="json-ld"))), ensure_ascii=False)


class DcatHarvester(Harvester):
    type = "dcat"
    title = "DCAT catalogue"

    def __init__(self):
        self._pages = {}  # address -> (graph, datasets); a run fetches each page once

    def validate_config(self, config: dict) -> dict:
        out = {"limit": 5000, **config}
        if not isinstance(out["limit"], int) or not 1 <= out["limit"] <= 100000:
            raise HarvestError("limit must be a whole number from 1 to 100000.")
        return out

    def _page(self, url: str, http):
        if url not in self._pages:
            response = http.get(url)
            response.raise_for_status()
            graph = read(response.text, response.headers.get("content-type"), url, http)
            self._pages[url] = (graph, datasets(graph))
        return self._pages[url]

    def gather(self, source: dict, since, http) -> Gathered:
        # The whole catalogue is read each time, so `since` is not needed: a dataset whose date
        # has not moved is left alone, and one no longer in the catalogue is known to be gone.
        limit = source["config"]["limit"]
        found, visited, url, cut_short = {}, set(), source["url"], False
        while url and url not in visited and not cut_short:
            visited.add(url)
            graph, held = self._page(url, http)
            for identifier, node in held.items():
                if identifier in found:
                    continue
                if len(found) >= limit:
                    cut_short = True
                    break
                modified = graph.value(node, DCTERMS.modified)
                found[identifier] = Item(identifier=identifier, url=url, modified=lastmod_date(str(modified)) if modified else None)
            following = [str(o) for link in _NEXT for o in graph.objects(None, link)]
            url = urljoin(url, following[0]) if following else None
        if not found and len(visited) == 1:
            raise HarvestError("The address holds no DCAT dataset: nothing in it is described as a dcat:Dataset.")
        # Stopped by the limit, the list is not everything: nothing may be withdrawn on its word.
        return Gathered(items=list(found.values()), complete=not cut_short)

    def fetch(self, source: dict, item: Item, http) -> Fetched:
        graph, held = self._page(item.url, http)
        if item.identifier not in held:
            raise HarvestError("The catalogue page no longer holds this dataset.")
        content = cut(graph, held[item.identifier], address(item.identifier, item.url))
        return Fetched(content=content, content_type="application/ld+json")
