"""Turns a harvested document into a CDIF record, once `detect` has said what it is.

Only CDIF JSON-LD is taken in today: it is CDIF already. Every other recognised format is kept
as received and reported, naming the converter that exists for it in the CDIF `converters`
repository, so that connecting that converter later needs no second harvest.

To connect a converter: add its format id to `CONVERTERS` with a function taking the text and
returning a CDIF record.
"""
import json

from app.harvest import HarvestError
from app.harvest.detect import Detected


def _cdif(content: str) -> dict:
    record = json.loads(content)
    if isinstance(record, dict) and "@graph" not in record:
        return record
    raise HarvestError("The file holds more than one record, or a graph of nodes; one CDIF record per file is expected.")


# format id -> function(text) -> CDIF record
CONVERTERS = {
    "cdif-jsonld": _cdif,
}


def to_cdif(detected: Detected, content: str) -> dict:
    convert = CONVERTERS.get(detected.format)
    if convert is not None:
        return convert(content)
    if detected.format == "json-invalid":
        raise HarvestError(f"The file is not valid JSON: {detected.detail}")
    if detected.format == "xml-invalid":
        raise HarvestError(f"The file is not well-formed XML: {detected.detail}")
    seen = f" ({detected.detail})" if detected.detail else ""
    if detected.converter:
        raise HarvestError(
            f"Recognised as {detected.label}. A converter to CDIF exists ({detected.converter} in the "
            "converters repository) but is not connected to the catalog yet."
        )
    raise HarvestError(f"Recognised as {detected.label}{seen}. There is no converter to CDIF for it.")
