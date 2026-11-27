"""Harvests a folder in a GitHub repository.

A GitHub folder address (github.com/{owner}/{repo}/tree/{ref}/{path}) is an HTML page, and each
file under it is served as an HTML page wrapping the file, not as the file itself. The raw file
lives on raw.githubusercontent.com. This harvester lists the folder with GitHub's Contents API,
which names each file's raw address, and fetches the raw file from there.

It is otherwise the web-folder harvester: the listing is always the whole folder (so a file no
longer listed is withdrawn), and files are recognised as unchanged by their content, because the
Contents API gives no per-file modified date.

Unauthenticated, GitHub's API allows 60 requests an hour from one address; a run spends one on
each folder it lists (raw files are fetched from the CDN, which is not rate-limited this way).
"""
import re
from urllib.parse import quote, urlsplit

from app.harvest import Fetched, Gathered, Harvester, HarvestError, Item

# File types worth fetching. What each file actually is, is worked out from its content.
EXTENSIONS = [".json", ".jsonld", ".xml", ".ttl", ".rdf"]
API = "https://api.github.com"

# /{owner}/{repo}, optionally /tree/{ref}/{path}. The ref is one segment: a branch name with a
# slash in it cannot be told from the path that follows, so such a branch is not supported here.
_PATH = re.compile(r"^/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+)(?:/(.*))?)?/?$")


def parse(url: str) -> tuple[str, str, str | None, str]:
    """Pull owner, repo, ref and path out of a github.com address. Without a /tree/ part the
    repository's default branch and its root are used."""
    parts = urlsplit(url)
    if parts.netloc.lower() != "github.com":
        raise HarvestError(
            "The address must be a github.com folder, such as https://github.com/owner/repo/tree/main/folder."
        )
    match = _PATH.match(parts.path)
    if not match:
        raise HarvestError(
            "The address must name a repository or a folder in one, such as "
            "https://github.com/owner/repo/tree/main/folder."
        )
    owner, repo, ref, path = match.groups()
    return owner, repo, ref, (path or "").strip("/")


class GithubHarvester(Harvester):
    type = "github"
    title = "GitHub folder"

    def validate_config(self, config: dict) -> dict:
        out = {"extensions": EXTENSIONS, "depth": 3, **config}
        extensions = out["extensions"]
        if not isinstance(extensions, list) or not extensions or not all(
            isinstance(e, str) and e.startswith(".") and len(e) > 1 for e in extensions
        ):
            raise HarvestError("extensions must be a list of file endings such as .json or .xml.")
        if not isinstance(out["depth"], int) or not 0 <= out["depth"] <= 10:
            raise HarvestError("depth must be a whole number from 0 to 10.")
        return out

    def gather(self, source: dict, since, http) -> Gathered:
        # The Contents API lists the whole folder, so `since` is not needed: a file is recognised
        # as unchanged by its content, and a file no longer listed is known to be gone.
        owner, repo, ref, path = parse(source["url"])
        config = source["config"]
        items, visited = [], set()
        query = f"?ref={quote(ref, safe='')}" if ref else ""
        start = f"{API}/repos/{owner}/{repo}/contents" + (f"/{quote(path)}" if path else "") + query

        def walk(url: str, depth: int) -> None:
            if url in visited:
                return
            visited.add(url)
            entries = _entries(http, url)
            for entry in entries:
                if entry.get("type") == "dir":
                    if depth < config["depth"]:
                        walk(entry["url"], depth + 1)  # the entry carries the ref already
                elif entry.get("type") == "file" and entry.get("download_url"):
                    if any(entry["name"].lower().endswith(e) for e in config["extensions"]):
                        raw = entry["download_url"]  # a raw.githubusercontent.com address
                        items.append(Item(identifier=raw, url=raw))

        walk(start, 0)
        return Gathered(items=items, complete=True)

    def fetch(self, source: dict, item: Item, http) -> Fetched:
        response = http.get(item.url)
        response.raise_for_status()
        return Fetched(content=response.text, content_type=response.headers.get("content-type"))


def _entries(http, url: str) -> list:
    response = http.get(url, headers={"Accept": "application/vnd.github+json"})
    if response.status_code == 403 and "rate limit" in response.text.lower():
        raise HarvestError(
            "GitHub is rate-limiting this address (60 requests an hour without a token). Try again later."
        )
    if response.status_code == 404:
        raise HarvestError("No such repository or folder on GitHub, or it is private.")
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, list):
        raise HarvestError("That address is a single file, not a folder. Give the address of a folder.")
    return body
