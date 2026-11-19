"""Obeying a site's robots.txt: what may be fetched, and how fast."""
import httpx
import pytest

from app.harvest import HarvestError
from app.harvest.robots import MAX_DELAY_SECONDS, Polite

AGENT = "CDIFCatalogApp-harvester"


def site(robots, status=200):
    """A pretend site. `robots` is the text of its robots.txt, or None for there being none."""
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(f"{request.method} {request.url.path}")
        if request.url.path == "/robots.txt":
            return httpx.Response(404) if robots is None else httpx.Response(status, text=robots)
        return httpx.Response(200, text="ok")

    return httpx.Client(transport=httpx.MockTransport(handler)), asked


class Clock:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def __call__(self):
        return self.now


def test_no_robots_file_allows_everything_and_is_asked_for_once():
    http, asked = site(None)
    polite = Polite(http, AGENT)
    assert polite.get("https://a.example/records/").text == "ok"
    polite.head("https://a.example/records/x.json")
    assert asked == ["GET /robots.txt", "GET /records/", "HEAD /records/x.json"]


def test_a_disallowed_address_is_refused_without_being_requested():
    http, asked = site("User-agent: *\nDisallow: /private/\n")
    polite = Polite(http, AGENT)
    polite.get("https://a.example/records/x.json")
    with pytest.raises(HarvestError, match="robots.txt does not allow"):
        polite.get("https://a.example/private/x.json")
    assert "GET /private/x.json" not in asked


def test_rules_addressed_to_this_harvester_by_name_win_over_the_general_ones():
    http, _ = site(f"User-agent: *\nDisallow: /\n\nUser-agent: {AGENT}\nDisallow:\n")
    assert Polite(http, AGENT).get("https://a.example/records/x.json").text == "ok"
    http, _ = site(f"User-agent: *\nDisallow:\n\nUser-agent: {AGENT}\nDisallow: /\n")
    with pytest.raises(HarvestError):
        Polite(http, AGENT).get("https://a.example/records/x.json")


def test_a_robots_file_that_cannot_be_read_closes_the_site():
    http, asked = site("", status=503)
    with pytest.raises(HarvestError, match="could not be read"):
        Polite(http, AGENT).get("https://a.example/records/")
    assert asked == ["GET /robots.txt"]


def test_the_crawl_delay_is_waited_between_requests_but_not_before_the_first():
    http, _ = site("User-agent: *\nCrawl-delay: 2\n")
    clock = Clock()
    polite = Polite(http, AGENT, sleep=clock.sleep, clock=clock)
    polite.get("https://a.example/1")
    assert clock.slept == []
    polite.get("https://a.example/2")
    clock.now += 5  # time spent elsewhere counts towards the wait
    polite.get("https://a.example/3")
    assert clock.slept == [2.0]


def test_an_unreasonable_crawl_delay_is_capped():
    http, _ = site("User-agent: *\nCrawl-delay: 3600\n")
    clock = Clock()
    polite = Polite(http, AGENT, sleep=clock.sleep, clock=clock)
    polite.get("https://a.example/1")
    polite.get("https://a.example/2")
    assert clock.slept == [MAX_DELAY_SECONDS]


def test_each_site_has_its_own_rules():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n" if request.url.host == "closed.example" else "")
        return httpx.Response(200, text="ok")

    polite = Polite(httpx.Client(transport=httpx.MockTransport(handler)), AGENT)
    assert polite.get("https://open.example/x").text == "ok"
    with pytest.raises(HarvestError):
        polite.get("https://closed.example/x")
