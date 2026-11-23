"""Works out what a harvested document is from its content, not from its file name.

A source may hold CDIF JSON-LD, other JSON-LD, plain JSON, any of several XML metadata formats,
or Turtle. The answer decides what happens next: a CDIF record is validated against the profiles
its own catalog record declares (`schema:subjectOf` ... `dcterms:conformsTo`), and anything else
needs a converter to CDIF first.

`FORMATS` names every format recognised, with the converter for it in the CDIF `converters`
repository where one exists. Recognising a format and being able to convert it are separate:
see `convert.py` for what is connected.

Near-term aim: CDIF JSON-LD and the XML formats are recognised reliably. JSON, other JSON-LD and
Turtle are recognised by a few telling features, enough to route them, and will need more
flavours over time.
"""
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO

CDIF = "https://w3id.org/cdif/"

# id -> (what a person would call it, converter in the CDIF converters repository or None)
FORMATS = {
    "cdif-jsonld": ("CDIF JSON-LD", None),
    "schemaorg-jsonld": ("schema.org JSON-LD", "soso2cdif.py"),
    "dcat-jsonld": ("DCAT JSON-LD", "DCAT/dcat_to_cdif.py"),
    "croissant": ("Croissant JSON-LD", "croissant/ConvertFromCroissant.py"),
    "rocrate": ("RO-Crate JSON-LD", "ROCrate/ROCrateToCDIF.py"),
    "ddicdi-jsonld": ("DDI-CDI JSON-LD", "DDI-CDI/ddicdi_jsonld_to_cdif.py"),
    "jsonld-other": ("JSON-LD of an unrecognised kind", None),
    "umm-c": ("NASA UMM-C JSON", "UMM/umm_to_cdif.py"),
    "fair2": ("FAIR2 JSON-LD", "FAIR2/fair2_to_cdif.py"),
    "niaid-json": ("NIAID Data Ecosystem JSON", "NIAID/harvest_niaid_to_cdif.py"),
    "dcat-us-json": ("DCAT-US data.json", None),
    "stac": ("STAC JSON", None),
    "datacite-json": ("DataCite JSON", None),
    "ckan-json": ("CKAN package JSON", None),
    "json-other": ("JSON of an unrecognised kind", None),
    "json-invalid": ("text that starts like JSON but is not valid JSON", None),
    "iso19139": ("ISO 19139 XML", "ISO19115/iso_to_cdif.py"),
    "iso19115-2": ("ISO 19115-2 XML", "ISO19115/iso_to_cdif.py"),
    "iso19115-3": ("ISO 19115-3 XML", "ISO19115/iso_to_cdif.py"),
    "csw-response": ("CSW response XML", "ISO19115/iso_to_cdif.py"),
    "fgdc": ("FGDC CSDGM XML", None),
    "arcgis": ("ArcGIS metadata XML", None),
    "eml": ("EML XML", None),
    "datacite-xml": ("DataCite XML", "DataCite/datacite_to_cdif.py"),
    "dublin-core": ("Dublin Core XML", None),
    "ddi-1.2.2": ("DDI 1.2.2 XML", "DDI/ddi122_to_cdif.py"),
    "ddi-codebook-2.5": ("DDI Codebook 2.5 XML", "DDICodebook/ddi25_to_cdif.py"),
    "ddi-lifecycle": ("DDI Lifecycle XML", None),
    "ddicdi-xml": ("DDI-CDI XML", "DDI-CDI/ddicdi_to_cdif.py"),
    "sdmx-ml": ("SDMX-ML structure message", "SDMX/sdmx_to_cdif.py"),
    "dcat-rdfxml": ("DCAT RDF/XML", "DCAT/dcat_to_cdif.py"),
    "rdfxml-other": ("RDF/XML of an unrecognised kind", None),
    "oai-pmh-response": ("OAI-PMH response XML", None),
    "ogc-capabilities": ("OGC service capabilities XML", None),
    "xml-other": ("XML of an unrecognised kind", None),
    "xml-invalid": ("text that starts like XML but is not well formed", None),
    "dcat-turtle": ("DCAT Turtle", "DCAT/dcat_to_cdif.py"),
    "schemaorg-turtle": ("schema.org Turtle", None),
    "turtle-other": ("Turtle of an unrecognised kind", None),
    "unknown": ("an unrecognised format", None),
}


@dataclass(frozen=True)
class Detected:
    format: str
    serialisation: str  # "json-ld", "json", "xml", "turtle" or "unknown"
    conforms_to: tuple = ()  # what a JSON-LD record's own catalog record says it conforms to
    detail: str = ""  # for the unrecognised kinds: what was seen, to help add the format later

    @property
    def label(self) -> str:
        return FORMATS[self.format][0]

    @property
    def converter(self) -> str | None:
        return FORMATS[self.format][1]


def detect(content: str, content_type: str | None = None, url: str | None = None) -> Detected:
    """What `content` is. The media type and address are only tie-breakers for text that does
    not announce itself, which in practice means Turtle."""
    text = content.lstrip("﻿ \t\r\n")
    media = (content_type or "").split(";")[0].strip().lower()
    if text[:1] in ("{", "["):
        return _json(text)
    if text[:1] == "<" and not _looks_like_turtle(text, media, url):
        return _xml(text)
    if _looks_like_turtle(text, media, url):
        return _turtle(text)
    return Detected("unknown", "unknown", detail=text[:40])


# ---- JSON and JSON-LD -------------------------------------------------------------------------

_CONFORMS_TO = ("dcterms:conformsTo", "dct:conformsTo", "conformsTo", "http://purl.org/dc/terms/conformsTo")
_SUBJECT_OF = ("schema:subjectOf", "subjectOf", "http://schema.org/subjectOf", "https://schema.org/subjectOf")
_ADDITIONAL_TYPE = ("schema:additionalType", "additionalType", "http://schema.org/additionalType")


def _many(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _ids(value) -> list[str]:
    """Addresses from a value that may hold strings, {"@id": ...} objects, or a list of either."""
    out = []
    for v in _many(value):
        v = v.get("@id") if isinstance(v, dict) else v
        if isinstance(v, str):
            out.append(v)
    return out


def _first(node: dict, keys) -> object:
    return next((node[k] for k in keys if k in node), None)


def _types(node: dict) -> set[str]:
    return {t for t in _many(node.get("@type")) if isinstance(t, str)}


def _is_catalog_record(node: dict) -> bool:
    kinds = _types(node) | set(_ids(_first(node, _ADDITIONAL_TYPE)))
    return any(k.endswith("CatalogRecord") for k in kinds)


def declared_conformance(document) -> tuple:
    """Every address a JSON-LD document's catalog record gives under conformsTo. The catalog
    record is usually nested in `subjectOf`; it may also be a node of its own in an `@graph`."""
    nodes = [n for n in _many(document) if isinstance(n, dict)]
    for n in list(nodes):
        nodes += [g for g in _many(n.get("@graph")) if isinstance(g, dict)]
    found = []
    for node in nodes:
        records = [r for r in _many(_first(node, _SUBJECT_OF)) if isinstance(r, dict)]
        if _is_catalog_record(node):
            records.append(node)
        for record in records:
            found += [uri for uri in _ids(_first(record, _CONFORMS_TO)) if uri not in found]
    return tuple(found)


def _context_text(document) -> str:
    context = document.get("@context") if isinstance(document, dict) else None
    return json.dumps(context) if context is not None else ""


def _json(text: str) -> Detected:
    try:
        document = json.loads(text)
    except ValueError as e:
        return Detected("json-invalid", "json", detail=str(e))
    top = document if isinstance(document, dict) else {}
    listed = [d for d in document if isinstance(d, dict)] if isinstance(document, list) else []
    # A list of nodes carrying @id or @type is expanded JSON-LD, which has no @context.
    is_ld = "@context" in top or "@graph" in top or any("@context" in d or "@type" in d or "@id" in d for d in listed)
    if not is_ld:
        return _plain_json(top)

    declared = declared_conformance(document)
    context = (_context_text(top) + "".join(_context_text(d) for d in listed)).lower()
    nodes = [top] + listed
    nodes += [g for n in list(nodes) for g in _many(n.get("@graph")) if isinstance(g, dict)]
    types = set().union(*(_types(n) for n in nodes))

    def found(fmt):
        return Detected(fmt, "json-ld", declared)

    # A crate made from a CDIF record keeps that record's claims, so the crate has to be asked first.
    if "w3id.org/ro/crate" in context or any(n.get("@id") == "ro-crate-metadata.json" for n in nodes):
        return found("rocrate")
    if any(uri.startswith(CDIF) for uri in declared):
        return found("cdif-jsonld")
    if '"fair2"' in context:  # FAIR2 builds on Croissant, so it has to be asked first
        return found("fair2")
    if any("mlcommons.org/croissant" in uri for uri in declared) or "mlcommons.org/croissant" in context:
        return found("croissant")
    if "ddi-cdi" in context and not types & {"schema:Dataset", "Dataset"}:
        return found("ddicdi-jsonld")
    dcat_kinds = {"Dataset", "Catalog", "DataService", "DatasetSeries", "Distribution", "CatalogRecord"}
    if any(t.startswith(("dcat:", "http://www.w3.org/ns/dcat#")) for t in types) or (
        "www.w3.org/ns/dcat" in context and "schema.org" not in context and types & dcat_kinds
    ):
        return found("dcat-jsonld")
    if "schema.org" in context and any(t.split(":")[-1].split("/")[-1] == "Dataset" for t in types):
        return found("schemaorg-jsonld")
    return Detected("jsonld-other", "json-ld", declared, detail=", ".join(sorted(types))[:120])


def _plain_json(top: dict) -> Detected:
    def found(fmt):
        return Detected(fmt, "json")

    spec = top.get("MetadataSpecification")
    if (isinstance(spec, dict) and "umm" in str(spec.get("URL", "")).lower()) or {"ShortName", "EntryTitle"} <= set(top):
        return found("umm-c")
    items = top.get("items")  # a CMR search answer: UMM records wrapped in a list
    if isinstance(items, list) and items and isinstance(items[0], dict) and "umm" in items[0]:
        return found("umm-c")
    if {"@type", "_id"} <= set(top) and "@context" not in top:  # an NIAID Data Ecosystem API record
        return found("niaid-json")
    if "stac_version" in top:
        return found("stac")
    if isinstance(top.get("dataset"), list) and "project-open-data" in str(top.get("conformsTo", "")):
        return found("dcat-us-json")
    attributes = top.get("data", {}).get("attributes") if isinstance(top.get("data"), dict) else None
    if (isinstance(attributes, dict) and "doi" in attributes) or {"doi", "titles", "creators"} <= set(top):
        return found("datacite-json")
    package = top.get("result") if isinstance(top.get("result"), dict) else top
    if {"resources", "name"} <= set(package) and ("owner_org" in package or "metadata_modified" in package):
        return found("ckan-json")
    return Detected("json-other", "json", detail=", ".join(list(top)[:8]))


# ---- XML --------------------------------------------------------------------------------------

_NO_NAMESPACE_ROOT = {"codebook": "ddi-1.2.2"}
_BY_NAMESPACE = (
    # (start of the root element's namespace, root element name or None for any, format)
    ("http://www.isotc211.org/2005/gmd", "MD_Metadata", "iso19139"),
    ("http://www.isotc211.org/2005/gmi", "MI_Metadata", "iso19115-2"),
    ("http://standards.iso.org/iso/19115/-3/mdb", "MD_Metadata", "iso19115-3"),
    ("http://www.opengis.net/cat/csw", "Record", "dublin-core"),
    ("http://www.opengis.net/cat/csw", "SummaryRecord", "dublin-core"),
    ("http://www.opengis.net/cat/csw", "BriefRecord", "dublin-core"),
    ("http://www.opengis.net/cat/csw", None, "csw-response"),
    ("eml://ecoinformatics.org/eml", None, "eml"),
    ("https://eml.ecoinformatics.org/eml", None, "eml"),
    ("http://datacite.org/schema/kernel", "resource", "datacite-xml"),
    ("http://www.openarchives.org/OAI/2.0/oai_dc", None, "dublin-core"),
    ("http://purl.org/dc/elements/1.1", None, "dublin-core"),
    ("http://purl.org/dc/terms", None, "dublin-core"),
    ("http://www.openarchives.org/OAI/2.0/", "OAI-PMH", "oai-pmh-response"),
    ("ddi:codebook:2_5", None, "ddi-codebook-2.5"),
    ("http://www.icpsr.umich.edu/DDI", None, "ddi-1.2.2"),
    ("ddi:instance:3", None, "ddi-lifecycle"),
    ("http://ddialliance.org/Specification/DDI-CDI", None, "ddicdi-xml"),
    ("http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message", None, "sdmx-ml"),
    ("http://www.opengis.net/wms", None, "ogc-capabilities"),
    ("http://www.opengis.net/wfs", None, "ogc-capabilities"),
    ("http://www.opengis.net/wmts", None, "ogc-capabilities"),
    ("http://www.opengis.net/wcs", None, "ogc-capabilities"),
)
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_DCAT = "http://www.w3.org/ns/dcat#"


def _split(tag: str) -> tuple[str, str]:
    return (tag[1:].split("}", 1)[0], tag.split("}", 1)[1]) if tag.startswith("{") else ("", tag)


def _opening_elements(text: str, limit: int = 40) -> list[tuple[str, str]]:
    """(namespace, name) of the first few elements. Only the start of the document is read, so
    its size, and anything a hostile document tries further in, does not matter."""
    seen = []
    for _, element in ET.iterparse(BytesIO(text.encode("utf-8")), events=("start",)):
        seen.append(_split(element.tag))
        if len(seen) >= limit:
            break
    return seen


def _xml(text: str) -> Detected:
    try:
        elements = _opening_elements(text)
    except ET.ParseError as e:
        return Detected("xml-invalid", "xml", detail=str(e))
    if not elements:
        return Detected("xml-invalid", "xml", detail="no elements")
    namespace, name = elements[0]

    def found(fmt):
        return Detected(fmt, "xml")

    if namespace == _RDF and name == "RDF":
        # DCAT may show only as an rdf:type or far into the file, so look for its namespace anywhere
        return found("dcat-rdfxml" if _DCAT in text else "rdfxml-other")
    for start, root, fmt in _BY_NAMESPACE:
        if namespace.startswith(start) and root in (None, name):
            return found(fmt)
    if not namespace:
        names = {n for _, n in elements}
        if name == "metadata" and "idinfo" in names:
            return found("fgdc")
        if name == "metadata" and "Esri" in names:
            return found("arcgis")
        if name.lower() in _NO_NAMESPACE_ROOT:
            return found(_NO_NAMESPACE_ROOT[name.lower()])
        if name in ("WMS_Capabilities", "WMT_MS_Capabilities", "WFS_Capabilities", "Capabilities"):
            return found("ogc-capabilities")
    return Detected("xml-other", "xml", detail=f"{name} in namespace {namespace or '(none)'}")


# ---- Turtle -----------------------------------------------------------------------------------

_TURTLE_START = re.compile(r"^\s*(@prefix|@base|PREFIX|BASE)\s", re.IGNORECASE | re.MULTILINE)


def _looks_like_turtle(text: str, media: str, url: str | None) -> bool:
    if text[:1] == "<" and re.match(r"<\?xml|<!--|<!DOCTYPE|<[A-Za-z_][\w.-]*(:[\w.-]+)?[\s>/]", text):
        return False  # XML: a Turtle document may also open with "<", but then with an address
    return (
        media in ("text/turtle", "application/x-turtle", "text/n3")
        or bool(_TURTLE_START.search(text[:4000]))
        or bool(url and url.lower().split("?")[0].endswith((".ttl", ".n3")))
    )


def _turtle(text: str) -> Detected:
    if "http://www.w3.org/ns/dcat#" in text:
        return Detected("dcat-turtle", "turtle")
    if re.search(r"https?://schema\.org/", text):
        return Detected("schemaorg-turtle", "turtle")
    return Detected("turtle-other", "turtle")
