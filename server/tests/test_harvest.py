"""Harvest runs against a pretend web folder. These need a real PostgreSQL (DATABASE_URL) and
fail, not skip, without one. No network: the folder is served by an httpx mock transport."""
import datetime
import json
import os
from email.utils import format_datetime
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app import access, auth
from app.harvest import run
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures" / "CoreDiscovery"
BASE = "https://repo.example/records/"
MINIMAL = (FIXTURES / "exampleCDIFDiscoveryMinimal.json").read_text(encoding="utf-8")
COMPLETE = (FIXTURES / "exampleCDIFDiscoveryComplete.json").read_text(encoding="utf-8")
INVALID = (FIXTURES / "name-fail.json").read_text(encoding="utf-8")


class Folder:
    """A web folder whose files and dates a test can change between runs."""

    def __init__(self, files):
        self.files = dict(files)  # name -> (modified date as "30-Mar-2024 12:01" or None, text)
        self.fetched = []  # files whose content was downloaded
        self.down = False
        self.broken = set()  # files that are listed but answer with an error
        self.robots = None  # the text of /robots.txt, or None for there being none

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(503)
        url = str(request.url)
        if request.url.path == "/robots.txt" and self.robots is not None:
            return httpx.Response(200, text=self.robots)
        if url == BASE:
            rows = "".join(f'<a href="{n}">{n}</a>\n' for n in self.files)
            return httpx.Response(200, text=f'<pre><a href="../">../</a>\n{rows}</pre>')
        name = url[len(BASE):]
        if name not in self.files:
            return httpx.Response(404)
        if name in self.broken:
            return httpx.Response(500)
        date, text = self.files[name]
        headers = {}
        if date:
            when = datetime.datetime.strptime(date, "%d-%b-%Y %H:%M").replace(tzinfo=datetime.timezone.utc)
            headers["last-modified"] = format_datetime(when, usegmt=True)
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        self.fetched.append(name)
        return httpx.Response(200, text=text, headers=headers)


@pytest.fixture
def db():
    assert os.environ.get("DATABASE_URL"), "DATABASE_URL must be set to run the harvest tests"
    with TestClient(app):  # startup creates the tables
        pass
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        conn.sources = []
        yield conn
        conn.rollback()
        conn.execute("DELETE FROM harvest_sources WHERE id = ANY(%s::uuid[])", (conn.sources,))


def new_source(conn, **fields):
    row = {"title": "Test folder", "url": BASE, "type": "waf", "organisation": "org-a", **fields}
    source = conn.execute(
        "INSERT INTO harvest_sources (title, url, type, organisation) VALUES (%(title)s, %(url)s, %(type)s, "
        "%(organisation)s) RETURNING *",
        row,
    ).fetchone()
    conn.commit()
    conn.sources.append(str(source["id"]))
    return source


def harvest(conn, source, folder, retry_of=None):
    job = conn.execute(
        "INSERT INTO harvest_jobs (source_id, retry_of) VALUES (%s, %s) RETURNING id", (source["id"], retry_of)
    ).fetchone()
    conn.commit()
    with httpx.Client(transport=httpx.MockTransport(folder)) as http:
        run.run_job(conn, run.claim(conn, job["id"]), http)
    errors = conn.execute("SELECT stage, message FROM harvest_errors WHERE job_id = %s", (job["id"],)).fetchall()
    status = conn.execute("SELECT status FROM harvest_jobs WHERE id = %s", (job["id"],)).fetchone()["status"]
    return {"id": job["id"], "status": status, "stats": run.stats(conn, job["id"]), "errors": errors}


def records(conn, source):
    rows = conn.execute("SELECT * FROM records WHERE source_id = %s", (source["id"],)).fetchall()
    return {r["source_identifier"][len(BASE):]: r for r in rows}


def test_a_first_run_adds_and_publishes_valid_records(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL), "b.json": ("30-Mar-2024 12:01", COMPLETE)})
    job = harvest(db, source, folder)
    assert job["status"] == "finished" and job["errors"] == []
    assert job["stats"]["added"] == 2
    a = records(db, source)["a.json"]
    assert a["status"] == "published" and a["labels"] == ["public", "member-org-a"]
    assert a["received"] == MINIMAL and a["received_format"] == "cdif-jsonld"
    assert a["profile"] == "CoreDiscovery" and "https://w3id.org/cdif/discovery/2.0" in a["validation"]["declared"]
    assert a["published"] == json.loads(MINIMAL) and a["validation"]["valid"] is True


def test_an_unchanged_modified_date_means_the_file_is_not_fetched_again(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL)})
    harvest(db, source, folder)
    folder.fetched.clear()
    job = harvest(db, source, folder)
    assert job["stats"]["not modified"] == 1 and job["stats"]["added"] == 0
    assert folder.fetched == []


def test_a_newer_date_with_the_same_content_is_fetched_but_not_modified(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL)})
    harvest(db, source, folder)
    folder.files["a.json"] = ("31-Mar-2024 08:00", MINIMAL)
    job = harvest(db, source, folder)
    assert job["stats"]["not modified"] == 1 and job["stats"]["updated"] == 0


def test_a_file_with_no_modified_date_is_fetched_each_run_and_recognised_by_its_content(db):
    source = new_source(db)
    folder = Folder({"a.json": (None, MINIMAL)})
    assert harvest(db, source, folder)["stats"]["added"] == 1
    folder.fetched.clear()
    job = harvest(db, source, folder)
    assert job["stats"]["not modified"] == 1 and folder.fetched == ["a.json"]


def test_changed_content_updates_the_record(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL)})
    harvest(db, source, folder)
    changed = MINIMAL.replace("Sea water chemistry", "Sea water chemistry, second edition")
    folder.files["a.json"] = ("31-Mar-2024 08:00", changed)
    job = harvest(db, source, folder)
    assert job["stats"]["updated"] == 1
    assert records(db, source)["a.json"]["published"]["schema:name"] == "Sea water chemistry, second edition"


def test_a_file_gone_from_the_folder_withdraws_its_record(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL), "b.json": ("30-Mar-2024 12:01", COMPLETE)})
    harvest(db, source, folder)
    del folder.files["b.json"]
    job = harvest(db, source, folder)
    assert job["stats"]["deleted"] == 1
    b = records(db, source)["b.json"]
    assert b["status"] == "withdrawn" and "public" not in b["labels"]


def test_an_invalid_record_is_stored_reported_and_not_published(db):
    source = new_source(db)
    job = harvest(db, source, Folder({"bad.json": ("30-Mar-2024 12:01", INVALID)}))
    assert job["stats"]["errored"] == 1
    assert job["errors"][0]["stage"] == "import" and "must be fixed" in job["errors"][0]["message"]
    bad = records(db, source)["bad.json"]
    assert bad["status"] == "invalid" and "public" not in bad["labels"]
    assert bad["received"] == INVALID and bad["validation"]["counts"]["violation"] > 0


def test_a_file_that_is_not_json_is_kept_as_received_and_reported(db):
    source = new_source(db)
    job = harvest(db, source, Folder({"broken.json": ("30-Mar-2024 12:01", "{not json")}))
    assert job["stats"]["errored"] == 1 and "not valid JSON" in job["errors"][0]["message"]
    assert records(db, source)["broken.json"]["received"] == "{not json"


SDMX = '<mes:Structure xmlns:mes="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"/>'
CONVERTERS = Path(__file__).parents[1] / "converters"


def test_a_format_whose_converter_is_not_connected_is_recognised_kept_and_reported(db):
    source = new_source(db)
    job = harvest(db, source, Folder({"record.xml": ("30-Mar-2024 12:01", SDMX), "a.json": ("30-Mar-2024 12:01", MINIMAL)}))
    assert job["stats"]["added"] == 1 and job["stats"]["errored"] == 1
    message = job["errors"][0]["message"]
    assert "SDMX-ML structure message" in message and "SDMX/sdmx_to_cdif.py" in message
    kept = records(db, source)["record.xml"]
    assert kept["received"] == SDMX and kept["received_format"] == "sdmx-ml" and kept["status"] == "invalid"


def test_an_iso_record_is_converted_checked_and_published_with_the_catalogs_own_claim(db):
    examples = sorted((CONVERTERS / "ISO19115" / "examples").rglob("*.xml"))
    assert examples, "server/converters is empty: run `git submodule update --init`"
    iso = examples[0].read_text(encoding="utf-8")
    source = new_source(db)
    job = harvest(db, source, Folder({"record.xml": ("30-Mar-2024 12:01", iso)}))
    assert job["errors"] == [] and job["stats"]["added"] == 1
    record = records(db, source)["record.xml"]
    assert record["received"] == iso and record["received_format"].startswith("iso191")
    assert record["status"] == "published" and record["validation"]["valid"] is True
    declared = {c["@id"] for c in record["published"]["schema:subjectOf"]["dcterms:conformsTo"]}
    assert {"https://w3id.org/cdif/core/2.0", "https://w3id.org/cdif/discovery/2.0"} <= declared


def test_what_a_file_is_comes_from_its_content_not_its_name(db):
    source = new_source(db)
    harvest(db, source, Folder({"cdif-named-as.xml": ("30-Mar-2024 12:01", MINIMAL)}))
    record = records(db, source)["cdif-named-as.xml"]
    assert record["received_format"] == "cdif-jsonld" and record["status"] == "published"


def test_robots_txt_is_obeyed_unless_the_source_says_to_ignore_it(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL)})
    folder.robots = "User-agent: *\nDisallow: /records/\n"  # the source's own starting point
    job = harvest(db, source, folder)
    assert [e["stage"] for e in job["errors"]] == ["gather"] and "robots.txt" in job["errors"][0]["message"]
    assert records(db, source) == {} and folder.fetched == []
    db.execute("UPDATE harvest_sources SET config = %s WHERE id = %s", (psycopg.types.json.Jsonb({"ignore_robots": True}), source["id"]))
    db.commit()
    assert harvest(db, source, folder)["stats"]["added"] == 1


def test_files_closed_by_robots_txt_are_left_out_and_the_rest_is_harvested(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL), "secret.json": ("30-Mar-2024 12:01", COMPLETE)})
    folder.robots = "User-agent: *\nDisallow: /records/secret.json\n"
    job = harvest(db, source, folder)
    assert job["errors"] == [] and job["stats"]["added"] == 1
    assert list(records(db, source)) == ["a.json"] and folder.fetched == ["a.json"]


def test_nothing_is_withdrawn_in_a_run_where_a_file_could_not_be_fetched(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL), "b.json": ("30-Mar-2024 12:01", COMPLETE), "c.json": ("30-Mar-2024 12:01", MINIMAL)})
    harvest(db, source, folder)
    del folder.files["b.json"]  # gone from the listing
    folder.files["c.json"] = ("31-Mar-2024 08:00", MINIMAL)
    folder.broken.add("c.json")  # and another file now fails: the source is misbehaving
    job = harvest(db, source, folder)
    assert job["stats"]["errored"] == 1 and job["stats"]["deleted"] == 0
    assert records(db, source)["b.json"]["status"] == "published"
    folder.broken.clear()  # once the source is well again, the missing record is withdrawn
    assert harvest(db, source, folder)["stats"]["deleted"] == 1
    assert records(db, source)["b.json"]["status"] == "withdrawn"


def test_a_retry_looks_again_at_only_the_records_that_failed(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL), "bad.json": ("30-Mar-2024 12:01", INVALID), "c.json": ("30-Mar-2024 12:01", COMPLETE)})
    folder.broken.add("c.json")
    first = harvest(db, source, folder)
    assert first["stats"]["added"] == 1 and first["stats"]["errored"] == 2
    folder.broken.clear()
    folder.fetched.clear()
    retry = harvest(db, source, folder, retry_of=first["id"])
    assert sorted(folder.fetched) == ["bad.json", "c.json"]  # a.json is left alone
    assert retry["stats"]["added"] == 1 and retry["stats"]["errored"] == 1  # c.json now in; bad.json still invalid
    assert retry["stats"]["deleted"] == 0 and records(db, source)["a.json"]["status"] == "published"


def test_a_retry_does_not_count_as_a_clean_full_run(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL)})
    folder.broken.add("a.json")
    first = harvest(db, source, folder)
    folder.broken.clear()
    retry = harvest(db, source, folder, retry_of=first["id"])
    assert retry["errors"] == []
    later = db.execute("INSERT INTO harvest_jobs (source_id) VALUES (%s) RETURNING id", (source["id"],)).fetchone()
    assert run.last_error_free_start(db, source["id"], later["id"]) is None


def test_a_source_that_cannot_be_listed_is_a_gather_error_and_withdraws_nothing(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL)})
    harvest(db, source, folder)
    folder.down = True
    job = harvest(db, source, folder)
    assert job["status"] == "finished"
    assert [e["stage"] for e in job["errors"]] == ["gather"]
    assert records(db, source)["a.json"]["status"] == "published"


def test_only_a_run_without_errors_counts_as_the_last_clean_one(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL)})
    clean = harvest(db, source, folder)
    folder.down = True
    failed = harvest(db, source, folder)
    third = db.execute("INSERT INTO harvest_jobs (source_id) VALUES (%s) RETURNING id", (source["id"],)).fetchone()
    since = run.last_error_free_start(db, source["id"], third["id"])
    started = db.execute("SELECT gather_started FROM harvest_jobs WHERE id = %s", (clean["id"],)).fetchone()
    assert failed["errors"] and since == started["gather_started"]


def test_an_overlay_survives_a_change_elsewhere_and_conflicts_on_the_same_property(db):
    source = new_source(db)
    folder = Folder({"a.json": ("30-Mar-2024 12:01", MINIMAL)})
    harvest(db, source, folder)
    db.execute(
        "UPDATE records SET overlay = %s WHERE source_id = %s",
        (psycopg.types.json.Jsonb({"schema:name": "A better title"}), source["id"]),
    )
    db.commit()
    # the source changes a property that is not overridden: the edit is reapplied
    folder.files["a.json"] = ("31-Mar-2024 08:00", MINIMAL.replace("2025-06-15", "2025-07-01"))
    assert harvest(db, source, folder)["stats"]["updated"] == 1
    a = records(db, source)["a.json"]
    assert a["published"]["schema:name"] == "A better title" and a["published"]["schema:dateModified"] == "2025-07-01"
    # the source now changes the overridden property: a conflict, and the published record stays
    folder.files["a.json"] = ("01-Apr-2024 08:00", MINIMAL.replace("Sea water chemistry", "Renamed upstream"))
    job = harvest(db, source, folder)
    assert job["stats"]["errored"] == 1 and "schema:name" in job["errors"][0]["message"]
    a = records(db, source)["a.json"]
    assert a["status"] == "conflict" and a["published"]["schema:name"] == "A better title"


def test_scheduled_sources_get_a_job_when_due_and_manual_ones_never(db):
    daily = new_source(db, title="Daily")
    manual = new_source(db, title="Manual")
    db.execute("UPDATE harvest_sources SET frequency = 'DAILY' WHERE id = %s", (daily["id"],))
    db.commit()
    run.schedule_due(db)
    run.schedule_due(db)  # a second pass must not queue a second job
    jobs = lambda s: db.execute("SELECT count(*) AS n FROM harvest_jobs WHERE source_id = %s", (s["id"],)).fetchone()["n"]
    assert jobs(daily) == 1 and jobs(manual) == 0
    next_run = db.execute("SELECT next_run > now() AS later FROM harvest_sources WHERE id = %s", (daily["id"],)).fetchone()
    assert next_run["later"] is True


def test_a_job_with_no_progress_past_the_timeout_is_aborted(db):
    source = new_source(db)
    job = db.execute(
        "INSERT INTO harvest_jobs (source_id, status, gather_started) VALUES (%s, 'running', now() - interval '3 hours') "
        "RETURNING id",
        (source["id"],),
    ).fetchone()
    db.commit()
    assert run.abort_stale(db, timeout_minutes=240) == 0
    assert run.abort_stale(db, timeout_minutes=60) == 1
    row = db.execute("SELECT status FROM harvest_jobs WHERE id = %s", (job["id"],)).fetchone()
    assert row["status"] == "aborted"


@pytest.fixture
def as_admin():
    # Sign-in itself is tested in test_auth.py; here an admin is simply assumed.
    admin = access.User(id="test-admin", permissions=access.GROUPS[access.ADMINS])
    app.dependency_overrides[auth.current_user] = lambda: admin
    yield
    app.dependency_overrides.pop(auth.current_user)


def test_the_api_registers_a_source_queues_one_run_at_a_time_and_clears(db, as_admin):
    with TestClient(app) as client:
        bad = client.post("/api/harvest/sources", json={"title": "x", "url": BASE, "type": "ftp"})
        assert bad.status_code == 422
        res = client.post("/api/harvest/sources", json={"title": "Folder", "url": BASE, "type": "waf"})
        assert res.status_code == 201
        source = res.json()
        db.sources.append(source["id"])
        assert source["config"] == {"extensions": [".json", ".jsonld", ".xml", ".ttl", ".rdf"], "depth": 3}
        job = client.post(f"/api/harvest/sources/{source['id']}/jobs")
        assert job.status_code == 201 and job.json()["status"] == "new"
        assert client.post(f"/api/harvest/sources/{source['id']}/jobs").status_code == 409
        assert client.post(f"/api/harvest/jobs/{job.json()['id']}/abort").json() == {"aborted": True}
        read = client.get(f"/api/harvest/jobs/{job.json()['id']}").json()
        assert read["status"] == "aborted" and read["errors"][0]["stage"] == "job"
        assert client.post(f"/api/harvest/jobs/{job.json()['id']}/retry").status_code == 422  # nothing failed in it
        assert client.post(f"/api/harvest/sources/{source['id']}/clear").json()["jobs_removed"] == 1
