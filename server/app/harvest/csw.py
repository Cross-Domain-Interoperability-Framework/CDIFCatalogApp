"""Harvests a catalogue over CSW 2.0.2, the search interface older ISO-based catalogues offer
(GeoNetwork, pycsw, deegree, Esri Geoportal).

The catalogue is asked for its records a page at a time in the short "summary" form, which gives
each record's identifier and, where the catalogue says, the date it last changed. A record whose
date has not moved is not fetched. Each record that is wanted is then asked for by its
identifier, in full, in the form the source's `schema` setting names: ISO 19139 unless told
otherwise. What comes back is taken out of the response's wrapper and handed on like any other
file; what it is, is worked out from its content as always.

Requests are made with GET and plain parameters, which every catalogue named above answers.
The list is always the whole catalogue, so a record no longer listed is known to be gone.
"""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from lxml import etree

from app.harvest import Fetched, Gathered, Harvester, HarvestError, Item
from app.harvest.sitemap import lastmod_date

CSW = "http://www.opengis.net/cat/csw/2.0.2"
# What a record can be asked for as: the setting's word, and the address CSW knows it by.
SCHEMAS = {
    "iso": "http://www.isotc211.org/2005/gmd",
    "dublin-core": CSW,
}
_OURS = {"service", "version", "request"}


def _local(element) -> str:
    return etree.QName(element).localname if isinstance(element.tag, str) else ""


def request_url(endpoint: str, **parameters) -> str:
    """The catalogue's address with a CSW request on it. Parameters the address already carries
    are kept, except the ones naming a request: an address is often pasted from a capabilities
    link."""
    parts = urlsplit(endpoint)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _OURS]
    query = urlencode(kept + [("service", "CSW"), ("version", "2.0.2")] + list(parameters.items()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def parse(xml: bytes):
    """The answer as a tree, or the catalogue's own complaint in words."""
    # no entity expansion and no network: the document comes from a site we do not control
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        root = etree.fromstring(xml, parser)
    except etree.XMLSyntaxError as error:
        raise HarvestError(f"The catalogue's answer is not well-formed XML: {error}")
    if _local(root) == "ExceptionReport":
        said = " ".join(" ".join(e.text.split()) for e in root.iter() if _local(e) == "ExceptionText" and e.text)
        raise HarvestError(f"The catalogue refused the request: {said or 'it gave no reason'}")
    return root


def listed(xml: bytes) -> tuple[list[tuple[str, str | None]], int, int | None]:
    """One page of a record list: ([(identifier, modified), ...], next position or 0, how many
    the catalogue says it holds)."""
    root = parse(xml)
    results = next((e for e in root.iter() if _local(e) == "SearchResults"), None)
    if _local(root) != "GetRecordsResponse" or results is None:
        raise HarvestError(f"The address does not answer as a CSW catalogue: its outermost element is <{_local(root)}>.")
    found = []
    for record in results:
        values = {}
        for child in record:
            if child.text and child.text.strip():
                values.setdefault(_local(child), child.text.strip())
        if values.get("identifier"):
            found.append((values["identifier"], lastmod_date(values.get("modified"))))

    def number(name):
        value = results.get(name) or ""
        return int(value) if value.isdigit() else None

    return found, number("nextRecord") or 0, number("numberOfRecordsMatched")


def unwrapped(xml: bytes) -> str:
    """The one record inside an answer to "give me this record", without the wrapper."""
    root = parse(xml)
    if _local(root) != "GetRecordByIdResponse":
        return xml.decode("utf-8", errors="replace")  # some catalogues send the record bare
    records = [child for child in root if isinstance(child.tag, str)]
    if not records:
        raise HarvestError("The catalogue listed this record but returned nothing when asked for it.")
    if len(records) > 1:
        raise HarvestError(f"The catalogue returned {len(records)} records for one identifier.")
    return etree.tostring(records[0], encoding="unicode")


class CswHarvester(Harvester):
    type = "csw"
    title = "CSW catalogue"

    def validate_config(self, config: dict) -> dict:
        out = {"schema": "iso", "page": 100, "limit": 5000, **config}
        if out["schema"] not in SCHEMAS:
            raise HarvestError(f"schema must be one of: {', '.join(SCHEMAS)}.")
        if not isinstance(out["page"], int) or not 1 <= out["page"] <= 1000:
            raise HarvestError("page must be a whole number from 1 to 1000.")
        if not isinstance(out["limit"], int) or not 1 <= out["limit"] <= 100000:
            raise HarvestError("limit must be a whole number from 1 to 100000.")
        return out

    def gather(self, source: dict, since, http) -> Gathered:
        # The whole list is asked for each time, so `since` is not needed: a record whose date
        # has not moved is left alone, and one no longer listed is known to be gone.
        config = source["config"]
        records, position, total = {}, 1, None
        while position and len(records) < config["limit"]:
            response = http.get(request_url(
                source["url"], request="GetRecords", typeNames="csw:Record", elementSetName="summary",
                resultType="results", outputSchema=CSW, startPosition=position, maxRecords=config["page"],
            ))
            response.raise_for_status()
            found, following, total = listed(response.content)
            for identifier, modified in found:
                if len(records) < config["limit"]:
                    records.setdefault(identifier, modified)
            # a catalogue that sends nothing more, or points backwards, has reached its end
            position = following if found and following > position else 0
        items = [
            Item(
                identifier=identifier,
                url=request_url(
                    source["url"], request="GetRecordById", id=identifier, elementSetName="full",
                    outputSchema=SCHEMAS[config["schema"]],
                ),
                modified=modified,
            )
            for identifier, modified in records.items()
        ]
        # Stopped by the limit, the list is not everything: nothing may be withdrawn on its word.
        return Gathered(items=items, complete=not (position or (total or 0) > len(records)))

    def fetch(self, source: dict, item: Item, http) -> Fetched:
        response = http.get(item.url)
        response.raise_for_status()
        return Fetched(content=unwrapped(response.content), content_type="application/xml")
