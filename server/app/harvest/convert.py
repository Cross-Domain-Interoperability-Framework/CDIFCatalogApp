"""Turns a harvested document into a CDIF record, once `detect` has said what it is.

CDIF JSON-LD is CDIF already. The other formats go through the converters in the CDIF
`converters` repository, connected in `converters.py`. A recognised format with no connected
converter is kept as received and reported, so that connecting one later needs no second
harvest: a retry of the failed records converts them from what is stored at the source.
"""
import json

from app import validate
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
            # The catalog checks and stores one nested record. Making one (framing) is the
            # converter's job by decision, so there is no framing step here; a converter that
            # returns a graph of separate nodes is reported.
            raise HarvestError(
                f"Recognised as {detected.label} and converted, but the result is a graph of "
                f"{len(record['@graph'])} nodes. The catalog takes one nested record; the converter needs to frame its result."
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


def claim(record: dict, profile: str) -> tuple:
    """Give a converted record its conformance claim, and say which profile to check it against.

    The catalog made the record, so the catalog says what it conforms to: the levels its content
    reaches. The check that follows decides whether the claim holds; if not, the record is not
    published. A record that does not reach even a level we hold a profile for (no identifier,
    say) is given the fallback profile's claim, so that the check reports what it lacks."""
    levels = converters.conformance(record)
    installed = validate.profile_for(levels, "")
    if not installed:
        return validate.declare(profile, record), profile
    return converters.declare(record, levels), installed
