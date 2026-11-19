"""CDIF records as DCAT-AP 3 and GeoDCAT-AP 3.

Which CDIF property goes where is declared in mappings/cdif-to-dcat.tsv, one row per property,
including the properties DCAT has no place for. Each row names one of the small functions below.
The output is tested against the SHACL shapes SEMIC publishes (tests/fixtures/shapes).

DCAT output is a derived view: it loses detail, and the table says what. The CDIF record is the
record.
"""
import csv
import re
from functools import lru_cache
from pathlib import Path

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCAT, DCTERMS, FOAF, RDF, RDFS, SKOS, XSD

TABLE = Path(__file__).parent / "mappings" / "cdif-to-dcat.tsv"
PROFILES = ("dcat_ap", "geodcat_ap")
NO_DESCRIPTION = "description missing"

ADMS = Namespace("http://www.w3.org/ns/adms#")
GEODCAT = Namespace("http://data.europa.eu/930/")
GSP = Namespace("http://www.opengis.net/ont/geosparql#")
HYDRA = Namespace("http://www.w3.org/ns/hydra/core#")
PREFIXES = {
    "dcat": DCAT, "dcterms": DCTERMS, "foaf": FOAF, "skos": SKOS, "adms": ADMS, "geodcat": GEODCAT,
    "gsp": GSP, "hydra": HYDRA,
}
MEDIA_TYPES = "http://www.iana.org/assignments/media-types/"
FORMATS = {"ttl": "turtle", "jsonld": "json-ld", "xml": "xml"}
MEDIA = {"ttl": "text/turtle", "jsonld": "application/ld+json", "xml": "application/rdf+xml"}


@lru_cache
def table() -> list[dict]:
    lines = [l for l in TABLE.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def lost(profile: str = "dcat_ap") -> list[str]:
    """The CDIF properties this output leaves out."""
    return [r["cdif"] for r in table() if r["how"] == "lost" or r["profile"] not in ("all", profile)]


# ---- reading CDIF values ----------------------------------------------------------------------


def _many(value) -> list:
    if value is None:
        return []
    if isinstance(value, dict) and "@list" in value:
        return list(value["@list"])
    return value if isinstance(value, list) else [value]


def _iri(value, context: dict) -> URIRef | None:
    """An address from a string or an {"@id": ...}, with the record's prefixes expanded. None
    when the value is not an address."""
    if isinstance(value, dict):
        value = value.get("@id")
    if not isinstance(value, str) or " " in value:
        return None
    prefix, sep, rest = value.partition(":")
    if sep and isinstance(context.get(prefix), str) and not rest.startswith("//"):
        return URIRef(context[prefix] + rest)
    return URIRef(value) if re.match(r"^(https?|urn|ftp|mailto):", value) else None


def _web(value, context) -> URIRef | None:
    iri = _iri(value, context)
    return iri if iri is not None and str(iri).startswith(("http://", "https://")) else None


def _text(value) -> str | None:
    """A label from a string or from a named thing such as a vocabulary term."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _text(value.get("schema:name"))
    return None


def _date(value) -> Literal | None:
    if not isinstance(value, str):
        return None
    for pattern, datatype in (
        (r"\d{4}", XSD.gYear), (r"\d{4}-\d{2}", XSD.gYearMonth), (r"\d{4}-\d{2}-\d{2}", XSD.date),
        (r"\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:\d{2})?", XSD.dateTime),
    ):
        if re.fullmatch(pattern, value):
            return Literal(value, datatype=datatype)
    return None


# ---- one function per kind of property --------------------------------------------------------
# Each takes (graph, dataset node, DCAT property, CDIF value, state). `state` carries the
# record's prefixes, the profile being written, and the distribution nodes written so far.


def text(g, s, p, value, state):
    for v in _many(value):
        if isinstance(v, str) and v.strip():
            g.add((s, p, Literal(v)))


def date(g, s, p, value, state):
    literal = _date(value)
    if literal is not None:
        g.add((s, p, literal))


def page(g, s, p, value, state):
    iri = _web(value, state["context"])
    if iri is not None:
        g.add((s, p, iri))
        g.add((iri, RDF.type, FOAF.Document))


def identifier(g, s, p, value, state):
    for v in _many(value):
        if isinstance(v, dict):
            v = v.get("schema:url") or v.get("schema:value")
        if isinstance(v, str) and v.strip():
            g.add((s, p, Literal(v)))


def other_identifiers(g, s, p, value, state):
    for v in _many(value):
        v = v.get("@id") if isinstance(v, dict) else v
        if isinstance(v, str) and v.strip():
            node = BNode()
            g.add((s, p, node))
            g.add((node, RDF.type, ADMS.Identifier))
            g.add((node, SKOS.notation, Literal(v)))


def keywords(g, s, p, value, state):
    for v in _many(value):
        label = _text(v)
        if label:
            g.add((s, p, Literal(label)))


def _agent(g, value, state) -> URIRef | BNode | None:
    if isinstance(value, dict) and "schema:Role" in _many(value.get("@type")):
        value = value.get("schema:contributor")  # a role wraps the person or organisation
    if not isinstance(value, (dict, str)):
        return None
    node = _iri(value, state["context"]) or BNode()
    name = _text(value) if isinstance(value, dict) else None
    if isinstance(node, BNode) and not name:
        return None
    state["agents"].add(node)
    g.add((node, RDF.type, FOAF.Agent))
    if isinstance(value, dict):
        types = _many(value.get("@type"))
        if "schema:Person" in types:
            g.add((node, RDF.type, FOAF.Person))
        if "schema:Organization" in types:
            g.add((node, RDF.type, FOAF.Organization))
    if name:
        g.add((node, FOAF.name, Literal(name)))
    return node


def agents(g, s, p, value, state):
    values = _many(value)
    if p == DCTERMS.publisher:
        values = values[:1]  # DCAT-AP allows one publisher
    for v in values:
        node = _agent(g, v, state)
        if node is not None:
            g.add((s, p, node))


def license(g, s, p, value, state):
    for v in _many(value):
        node = _iri(v, state["context"])
        if node is None:
            label = _text(v)
            if not label:
                continue
            node = BNode()
            g.add((node, RDFS.label, Literal(label)))
        g.add((node, RDF.type, DCTERMS.LicenseDocument))
        # DCAT-AP puts the licence on the distribution, and allows one there
        for target in state["distributions"] or [s]:
            if (target, p, None) not in g:
                g.add((target, p, node))


def access_rights(g, s, p, value, state):
    values = _many(value)
    addresses = [i for i in (_iri(v, state["context"]) for v in values) if i is not None]
    labels = [v for v in values if isinstance(v, str) and _iri(v, state["context"]) is None and v.strip()]
    if not addresses and not labels:
        return
    node = addresses[0] if len(addresses) == 1 and not labels else BNode()
    g.add((s, p, node))
    g.add((node, RDF.type, DCTERMS.RightsStatement))
    if isinstance(node, BNode):
        for label in labels + [str(a) for a in addresses]:
            g.add((node, RDFS.label, Literal(label)))


def distributions(g, s, p, value, state):
    for v in _many(value):
        if not isinstance(v, dict):
            continue
        download = _web(v.get("schema:contentUrl"), state["context"])
        access = download or _web(v.get("schema:url"), state["context"])
        if access is None:
            continue  # DCAT-AP requires an access address
        node = BNode()
        g.add((s, p, node))
        g.add((node, RDF.type, DCAT.Distribution))
        g.add((node, DCAT.accessURL, access))
        g.add((access, RDF.type, RDFS.Resource))
        if download is not None:
            g.add((node, DCAT.downloadURL, download))
        text(g, node, DCTERMS.title, v.get("schema:name"), state)
        text(g, node, DCTERMS.description, v.get("schema:description"), state)
        media = [m for m in _many(v.get("schema:encodingFormat")) if isinstance(m, str) and re.fullmatch(r"[\w.+-]+/[\w.+-]+", m)]
        if media:
            iri = URIRef(MEDIA_TYPES + media[0])
            g.add((node, DCAT.mediaType, iri))
            g.add((iri, RDF.type, DCTERMS.MediaType))
        for standard in _many(v.get("dcterms:conformsTo")):
            iri = _iri(standard, state["context"])
            if iri is not None:
                g.add((node, DCTERMS.conformsTo, iri))
                g.add((iri, RDF.type, DCTERMS.Standard))
        state["distributions"].append(node)


def _wkt(geo) -> str | None:
    if not isinstance(geo, dict):
        return None
    box = geo.get("schema:box")
    if isinstance(box, str):
        try:
            south, west, north, east = (float(n) for n in box.replace(",", " ").split())
        except ValueError:
            return None
        return f"POLYGON(({west} {south}, {east} {south}, {east} {north}, {west} {north}, {west} {south}))"
    lat, lon = geo.get("schema:latitude"), geo.get("schema:longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"POINT({lon} {lat})"
    return None


def spatial(g, s, p, value, state):
    for v in _many(value):
        if not isinstance(v, dict):
            continue
        label, wkt = _text(v.get("schema:name")), _wkt(v.get("schema:geo"))
        if not label and not wkt:
            continue
        node = BNode()
        g.add((s, p, node))
        g.add((node, RDF.type, DCTERMS.Location))
        if label:
            g.add((node, SKOS.prefLabel, Literal(label)))
        if wkt:
            literal = Literal(wkt, datatype=GSP.wktLiteral)
            g.add((node, DCAT.centroid if wkt.startswith("POINT") else DCAT.bbox, literal))


def temporal(g, s, p, value, state):
    for v in _many(value):
        if not isinstance(v, str) or "/" not in v:
            continue
        start, end = (_date(part) for part in v.split("/", 1))
        if start is None and end is None:
            continue
        node = BNode()
        g.add((s, p, node))
        g.add((node, RDF.type, DCTERMS.PeriodOfTime))
        if start is not None:
            g.add((node, DCAT.startDate, start))
        if end is not None:
            g.add((node, DCAT.endDate, end))


def catalog_record(g, s, p, value, state):
    """The catalog's own entry for the record: its address here, and when it last changed here."""
    node = state["record"]
    g.add((node, RDF.type, DCAT.CatalogRecord))
    g.add((node, FOAF.primaryTopic, s))
    g.add((node, DCTERMS.modified, Literal(state["changed_at"].isoformat(), datatype=XSD.dateTime)))
    if isinstance(value, dict):
        date(g, node, DCTERMS.issued, value.get("schema:sdDatePublished"), state)
        for standard in _many(value.get("dcterms:conformsTo")):
            iri = _iri(standard, state["context"])
            if iri is not None:
                g.add((node, DCTERMS.conformsTo, iri))
                g.add((iri, RDF.type, DCTERMS.Standard))


def lost_property(g, s, p, value, state):
    pass


HOW = {
    "text": text, "date": date, "page": page, "identifier": identifier,
    "other_identifiers": other_identifiers, "keywords": keywords, "agents": agents, "license": license,
    "access_rights": access_rights, "distributions": distributions, "spatial": spatial,
    "temporal": temporal, "catalog_record": catalog_record, "lost": lost_property,
}


# ---- records and catalogs ---------------------------------------------------------------------


def new_graph() -> Graph:
    g = Graph()
    for prefix, namespace in PREFIXES.items():
        g.bind(prefix, namespace)
    return g


def _property(curie: str) -> URIRef | None:
    prefix, _, local = curie.partition(":")
    # built by hand: rdflib's own DCAT list predates DCAT 3 and warns on dcat:version
    return URIRef(str(PREFIXES[prefix]) + local) if curie else None


def has_geography(record: dict) -> bool:
    """Whether GeoDCAT-AP has anything to add for this record."""
    return any(isinstance(v, dict) and _wkt(v.get("schema:geo")) for v in _many(record.get("schema:spatialCoverage")))


def add_record(g: Graph, record: dict, record_url: str, changed_at, profile: str = "dcat_ap"):
    """Write one CDIF record into the graph. Returns (dataset node, catalog record node)."""
    context = record.get("@context") if isinstance(record.get("@context"), dict) else {}
    dataset = _web(record.get("@id"), context) or URIRef(record_url + "#dataset")
    state = {
        "context": context, "profile": profile, "record": URIRef(record_url), "changed_at": changed_at,
        "distributions": [], "agents": set(),
    }
    g.add((dataset, RDF.type, DCAT.Dataset))
    g.add((dataset, RDF.type, DCAT.Resource))  # the shapes do no inference, so say it outright
    # the licence goes on the distributions, so they have to be written first
    for row in sorted(table(), key=lambda r: r["how"] == "license"):
        if row["profile"] in ("all", profile) and (row["cdif"] in record or row["how"] == "catalog_record"):
            HOW[row["how"]](g, dataset, _property(row["dcat"]), record.get(row["cdif"]), state)
    # DCAT-AP requires a description; CDIF only recommends one. Leaving the record out of every
    # DCAT harvest would be worse, so give the title and say plainly that there is none.
    if (dataset, DCTERMS.description, None) not in g:
        for title in list(g.objects(dataset, DCTERMS.title)):
            g.add((dataset, DCTERMS.description, Literal(f"{title}: {NO_DESCRIPTION}")))
    # DCAT-AP requires an agent to have a name. One given only as an address, and named nowhere
    # else in the record, is left out.
    for agent in state["agents"]:
        if (agent, FOAF.name, None) not in g:
            g.remove((agent, None, None))
            g.remove((None, None, agent))
    return dataset, state["record"]


def record_graph(record: dict, record_url: str, changed_at, profile: str = "dcat_ap") -> Graph:
    g = new_graph()
    add_record(g, record, record_url, changed_at, profile)
    return g


def catalog_graph(rows, about: dict, profile: str = "dcat_ap", paging: dict | None = None) -> Graph:
    """A catalog page. `rows` are (record, record address, changed_at). `about` has the catalog's
    address, title, description and publisher name. `paging` has the page addresses and counts."""
    g = new_graph()
    catalog = URIRef(about["url"])
    g.add((catalog, RDF.type, DCAT.Catalog))
    g.add((catalog, DCTERMS.title, Literal(about["title"])))
    g.add((catalog, DCTERMS.description, Literal(about["description"])))
    publisher = BNode()
    g.add((catalog, DCTERMS.publisher, publisher))
    g.add((publisher, RDF.type, FOAF.Agent))
    g.add((publisher, FOAF.name, Literal(about["publisher"])))
    for record, record_url, changed_at in rows:
        dataset, entry = add_record(g, record, record_url, changed_at, profile)
        g.add((catalog, DCAT.dataset, dataset))
        g.add((catalog, DCAT.record, entry))
    if paging:
        # Both the current Hydra terms and the older ones, because harvesters in use read either.
        page_node = URIRef(paging["this"])
        g.add((page_node, RDF.type, HYDRA.PagedCollection))
        g.add((page_node, HYDRA.totalItems, Literal(paging["total"])))
        g.add((page_node, HYDRA.itemsPerPage, Literal(paging["per_page"])))
        for key in ("first", "last", "next", "previous"):
            if paging.get(key):
                g.add((page_node, HYDRA[key], Literal(paging[key])))
                g.add((page_node, HYDRA[key + "Page"], Literal(paging[key])))
    return g


def serialize(g: Graph, fmt: str) -> str:
    return g.serialize(format=FORMATS[fmt])
