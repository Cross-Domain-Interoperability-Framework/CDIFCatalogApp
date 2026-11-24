"""Harvesting: what every kind of source has to provide.

A harvest works in three stages, the split ckanext-harvest uses:

  gather   list what the source holds, without fetching it
  fetch    get one record as the source sends it
  import   recognise what it is, convert it to CDIF, validate it and store it

A harvester provides the first two, which differ by kind of source. The third is the same for
every source: `detect.py` recognises the format from the content, `convert.py` turns it into
CDIF, and the runner (`run.py`) validates and stores it. The runner also owns what the stages
share: comparing against what is stored, recording each record's outcome, and writing errors as
rows.
"""
from dataclasses import dataclass, field


class HarvestError(Exception):
    """A problem to report against the job or the object, in words a data manager can act on."""


class Disallowed(HarvestError):
    """The site's robots.txt closes this address to us. A harvester walking a source skips such
    an address and carries on; it is an error only when it is the source's own starting point."""


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
    content_type: str | None = None  # the media type the source gave, if any; a hint only


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


def harvesters() -> dict:
    from app.harvest.sitemap import SitemapHarvester
    from app.harvest.waf import WafHarvester

    return {h.type: h for h in (WafHarvester(), SitemapHarvester())}
