"""Harvesting: what every kind of source has to provide.

A harvester works in three stages, the split ckanext-harvest uses:

  gather   list what the source holds, without fetching it
  fetch    get one record as the source sends it
  import   map that record to CDIF (`to_cdif`); the runner then validates and stores it

The runner (`run.py`) owns everything the stages share: comparing against what is stored,
recording each record's outcome, and writing errors as rows.
"""
import json
from dataclasses import dataclass, field


class HarvestError(Exception):
    """A problem to report against the job or the object, in words a data manager can act on."""


@dataclass
class Item:
    identifier: str  # the record's identifier at the source; with the source, finds it again
    url: str | None = None
    modified: str | None = None  # the source's own modified date, ISO text, when it gives one


@dataclass
class Gathered:
    items: list[Item] = field(default_factory=list)
    # True when the list is everything the source holds. Only then does a record's absence mean
    # it was deleted; a "changed since" listing says nothing about what it leaves out.
    complete: bool = True


@dataclass
class Fetched:
    content: str
    format: str  # "jsonld", "iso19139", "iso19115-3", ...


class Harvester:
    type = ""
    title = ""

    def validate_config(self, config: dict) -> dict:
        """Return the config with defaults filled in, or raise HarvestError saying what is wrong."""
        return config

    def gather(self, source: dict, since, http) -> Gathered:
        raise NotImplementedError

    def fetch(self, source: dict, item: Item, http) -> Fetched:
        raise NotImplementedError

    def to_cdif(self, fetched: Fetched) -> dict:
        """Map a fetched record to CDIF. JSON-LD is taken as CDIF already; the mappings for other
        formats (ISO, DCAT) are not built yet, so those records are kept as received and
        reported, not dropped."""
        if fetched.format != "jsonld":
            raise HarvestError(f"There is no mapping to CDIF for the format '{fetched.format}' yet.")
        try:
            record = json.loads(fetched.content)
        except ValueError as e:
            raise HarvestError(f"The file is not valid JSON: {e}")
        if not isinstance(record, dict):
            raise HarvestError("The file does not hold a single record.")
        return record


def harvesters() -> dict:
    from app.harvest.waf import WafHarvester

    return {h.type: h for h in (WafHarvester(),)}
