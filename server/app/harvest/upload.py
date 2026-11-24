"""Harvests files a person has uploaded, for a batch of records that sits on no web site.

The files are kept in the `uploads` table, one row per file, each belonging to a source of this
kind. From there they go through a run like any other source's records: what a file is, is
worked out from its content, it is converted, checked and stored, and the run reports each
file's outcome. A file uploaded again under the same name replaces the earlier one.

This is the one harvester that reads the database and not the web, so it opens its own
connection and leaves the HTTP client it is given alone.
"""
from app import store
from app.harvest import Fetched, Gathered, Harvester, HarvestError, Item

MAX_FILES = 200  # in one upload
MAX_CHARACTERS = 5_000_000  # in one file


def add_files(conn, source_id, files: list[tuple[str, str]]) -> None:
    """Keep the files for the source, replacing any already held under the same name."""
    for name, content in files:
        conn.execute(
            "INSERT INTO uploads (source_id, name, content) VALUES (%s, %s, %s) "
            "ON CONFLICT (source_id, name) DO UPDATE SET content = EXCLUDED.content, uploaded_at = now()",
            (source_id, name, content),
        )


class UploadHarvester(Harvester):
    type = "upload"
    title = "Uploaded files"

    def gather(self, source: dict, since, http) -> Gathered:
        with store.connect() as conn:
            rows = conn.execute(
                "SELECT name, uploaded_at FROM uploads WHERE source_id = %s ORDER BY name", (source["id"],)
            ).fetchall()
        # A file not uploaded again since it was last read is left alone, by its upload time.
        items = [Item(identifier=r["name"], modified=r["uploaded_at"].isoformat(timespec="microseconds")) for r in rows]
        return Gathered(items=items, complete=True)

    def fetch(self, source: dict, item: Item, http) -> Fetched:
        with store.connect() as conn:
            row = conn.execute(
                "SELECT content FROM uploads WHERE source_id = %s AND name = %s", (source["id"], item.identifier)
            ).fetchone()
        if row is None:
            raise HarvestError("The uploaded file is no longer held.")
        return Fetched(content=row["content"])
