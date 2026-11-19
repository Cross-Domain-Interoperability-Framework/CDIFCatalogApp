"""Turns a harvested document into a CDIF record, once `detect` has said what it is.

CDIF JSON-LD is CDIF already. The other formats go through the converters in the CDIF
`converters` repository, connected in `converters.py`. A recognised format with no connected
converter is kept as received and reported, so that connecting one later needs no second
harvest: a retry of the failed records converts them from what is stored at the source.
"""
import json

from app.harvest import HarvestError, converters
from app.harvest.detect import Detected


def _cdif(content: str) -> dict:
    record = json.loads(content)
    if isinstance(record, dict) and "@graph" not in record:
        return record
    raise HarvestError("The file holds more than one record, or a graph of nodes; one CDIF record per file is expected.")


# format id -> function(text) -> CDIF record
CONVERTERS = {"cdif-jsonld": _cdif, **converters.CONNECTED}


def to_cdif(detected: Detected, content: str) -> dict:
    convert = CONVERTERS.get(detected.format)
    if convert is not None:
        try:
            record = convert(content)
        except HarvestError:
            raise
        except Exception as e:  # the converters are scripts written for well-formed input
            raise HarvestError(f"Recognised as {detected.label}, but it could not be converted to CDIF: {type(e).__name__}: {e}")
        if "@graph" in record:
            # Some converters (DDI) return the dataset with its code lists as separate nodes. The
            # catalog checks and stores one nested record, and has no framing step to make one.
            raise HarvestError(
                f"Recognised as {detected.label} and converted, but the result is a graph of "
                f"{len(record['@graph'])} nodes, which the catalog cannot check or store yet."
            )
        return record
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
