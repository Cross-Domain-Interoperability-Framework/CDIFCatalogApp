"""Harvests a repository over OAI-PMH 2.0, the interface most data and publication repositories
offer for handing their metadata to aggregators (Zenodo, Dataverse, DSpace, DataCite, PANGAEA).

The repository is asked for the identifiers of its records, a batch at a time, each with the
date it last changed. A record whose date has not moved is not fetched. Each record that is
wanted is then asked for by its identifier, in the form the source's `prefix` setting names:
`oai_dc`, the Dublin Core every repository must offer, unless told otherwise. What comes back is
taken out of the response's wrapper and handed on like any other file; what it is, is worked out
from its content as always.

The list is always everything the repository holds (in the set named, if one is), so a record
no longer listed is known to be gone. A record the repository marks as deleted is left out of
the list, which comes to the same thing.
"""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from lxml import etree

from app.harvest import Fetched, Gathered, Harvester, HarvestError, Item
from app.harvest.sitemap import lastmod_date

_VERB_ARGUMENTS = {"verb", "identifier", "metadataprefix", "set", "from", "until", "resumptiontoken"}


def _local(element) -> str:
    return etree.QName(element).localname if isinstance(element.tag, str) else ""


def _children(element, name: str) -> list:
    return [child for child in element if _local(child) == name]


def request_url(endpoint: str, **arguments) -> str:
    """The repository's address with an OAI-PMH request on it. Parameters the address already
    carries are kept, except a request's own: an address is often pasted with `?verb=Identify`."""
    parts = urlsplit(endpoint)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in _VERB_ARGUMENTS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept + list(arguments.items())), ""))


def parse(xml: bytes, verb: str):
    """The part of the answer that belongs to the request made, or None when the repository says
    nothing matches. The repository's own complaint is passed on in words."""
    # no entity expansion and no network: the document comes from a site we do not control
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        root = etree.fromstring(xml, parser)
    except etree.XMLSyntaxError as error:
        raise HarvestError(f"The repository's answer is not well-formed XML: {error}")
    if _local(root) != "OAI-PMH":
        raise HarvestError(f"The address does not answer as an OAI-PMH repository: its outermost element is <{_local(root)}>.")
    errors = _children(root, "error")
    if errors:
        if all(e.get("code") == "noRecordsMatch" for e in errors):
            return None
        said = "; ".join(f"{e.get('code')}: {' '.join((e.text or '').split())}".rstrip(": ") for e in errors)
        raise HarvestError(f"The repository refused the request ({said}).")
    found = _children(root, verb)
    if not found:
        raise HarvestError(f"The repository's answer holds no <{verb}> element.")
    return found[0]


def listed(xml: bytes) -> tuple[list[tuple[str, str | None]], str]:
    """One batch of a list of identifiers: ([(identifier, modified), ...], the token that asks
    for the next batch or "" at the end). Records marked as deleted are left out."""
    answer = parse(xml, "ListIdentifiers")
    if answer is None:
        return [], ""
    found = []
    for header in _children(answer, "header"):
        if header.get("status") == "deleted":
            continue
        values = {_local(child): (child.text or "").strip() for child in header}
        if values.get("identifier"):
            found.append((values["identifier"], lastmod_date(values.get("datestamp"))))
    token = _children(answer, "resumptionToken")
    return found, (token[0].text or "").strip() if token else ""


def unwrapped(xml: bytes) -> str:
    """The one record inside an answer to "give me this record", without the wrapper."""
    answer = parse(xml, "GetRecord")
    records = _children(answer, "record") if answer is not None else []
    if not records:
        raise HarvestError("The repository listed this record but returned nothing when asked for it.")
    header = _children(records[0], "header")
    if header and header[0].get("status") == "deleted":
        raise HarvestError("The repository says this record has been deleted.")
    metadata = _children(records[0], "metadata")
    inside = [child for child in metadata[0] if isinstance(child.tag, str)] if metadata else []
    if len(inside) != 1:
        raise HarvestError(f"The repository's answer holds {len(inside)} metadata documents for this record; one is expected.")
    return etree.tostring(inside[0], encoding="unicode")


class OaiHarvester(Harvester):
    type = "oai-pmh"
    title = "OAI-PMH repository"

    def validate_config(self, config: dict) -> dict:
        out = {"prefix": "oai_dc", "set": "", "limit": 5000, **config}
        for name in ("prefix", "set"):
            if not isinstance(out[name], str) or (name == "prefix" and not out[name].strip()):
                raise HarvestError(f"{name} must be text, as the repository itself writes it.")
        if not isinstance(out["limit"], int) or not 1 <= out["limit"] <= 100000:
            raise HarvestError("limit must be a whole number from 1 to 100000.")
        return out

    def gather(self, source: dict, since, http) -> Gathered:
        # The whole list is asked for each time, so `since` is not needed: a record whose date
        # has not moved is left alone, and one no longer listed is known to be gone.
        config = source["config"]
        first = {"verb": "ListIdentifiers", "metadataPrefix": config["prefix"]}
        if config["set"]:
            first["set"] = config["set"]
        records, arguments, tokens = {}, first, set()
        while arguments and len(records) < config["limit"]:
            response = http.get(request_url(source["url"], **arguments))
            response.raise_for_status()
            found, token = listed(response.content)
            for identifier, modified in found:
                if len(records) < config["limit"]:
                    records.setdefault(identifier, modified)
            # a repository that hands back a token it has given before would be asked for ever
            arguments = {"verb": "ListIdentifiers", "resumptionToken": token} if token and token not in tokens else None
            tokens.add(token)
        items = [
            Item(
                identifier=identifier,
                url=request_url(source["url"], verb="GetRecord", identifier=identifier, metadataPrefix=config["prefix"]),
                modified=modified,
            )
            for identifier, modified in records.items()
        ]
        # Stopped by the limit, the list is not everything: nothing may be withdrawn on its word.
        return Gathered(items=items, complete=arguments is None and len(records) < config["limit"])

    def fetch(self, source: dict, item: Item, http) -> Fetched:
        response = http.get(item.url)
        response.raise_for_status()
        return Fetched(content=unwrapped(response.content), content_type="application/xml")
