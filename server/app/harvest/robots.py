"""Makes the harvester behave as a site's robots.txt asks.

`Polite` wraps the HTTP client a harvester is given. Before the first request to a site it reads
that site's /robots.txt; after that it refuses addresses the file disallows for us and waits the
crawl delay the file sets between requests. A source's owner can switch this off for their own
site with `"ignore_robots": true` in the source's settings. The idea is from Esri's Geoportal
harvester.

What a missing or broken robots.txt means follows RFC 9309: not found (4xx) allows everything;
a server error (5xx) or no answer allows nothing, because the site may be saying it is not ready.
"""
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from app.harvest import Disallowed, HarvestError

MAX_DELAY_SECONDS = 30  # a site asking for more than this between requests is not harvested slower


class Polite:
    def __init__(self, http, user_agent: str, sleep=time.sleep, clock=time.monotonic):
        self._http, self._agent, self._sleep, self._clock = http, user_agent, sleep, clock
        self._rules = {}  # site -> RobotFileParser, or None when everything is disallowed
        self._last = {}  # site -> when the last request to it was made

    def _site(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    def _rules_for(self, site: str):
        if site not in self._rules:
            rules = RobotFileParser()
            try:
                response = self._http.get(site + "/robots.txt")
                status = response.status_code
            except Exception:
                status = 599
            if status >= 500:
                rules = None
            elif status >= 400:
                rules.parse([])  # no robots.txt: nothing is disallowed
            else:
                rules.parse(response.text.splitlines())
            self._rules[site] = rules
        return self._rules[site]

    def _before(self, url: str) -> None:
        site = self._site(url)
        rules = self._rules_for(site)
        if rules is None:
            raise HarvestError(f"{site}/robots.txt could not be read, so the site is treated as closed to harvesting.")
        if not rules.can_fetch(self._agent, url):
            raise Disallowed(f"The site's robots.txt does not allow harvesting {url}")
        delay = rules.crawl_delay(self._agent)
        if delay and site in self._last:
            wait = min(float(delay), MAX_DELAY_SECONDS) - (self._clock() - self._last[site])
            if wait > 0:
                self._sleep(wait)
        self._last[site] = self._clock()

    def get(self, url, **kwargs):
        self._before(str(url))
        return self._http.get(url, **kwargs)

    def head(self, url, **kwargs):
        self._before(str(url))
        return self._http.head(url, **kwargs)
