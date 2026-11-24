"""Uploaded files: sent through the API, kept, and run through the same import as any harvest.
These need a real PostgreSQL (DATABASE_URL) and fail, not skip, without one."""
import os
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app import access, auth
from app.harvest import run, upload
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures" / "CoreDiscovery"
MINIMAL = (FIXTURES / "exampleCDIFDiscoveryMinimal.json").read_text(encoding="utf-8")
COMPLETE = (FIXTURES / "exampleCDIFDiscoveryComplete.json").read_text(encoding="utf-8")
INVALID = (FIXTURES / "name-fail.json").read_text(encoding="utf-8")
DUBLIN_CORE = (
    '<oai_dc:dc xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" xmlns:dc="http://purl.org/dc/elements/1.1/">'
    "<dc:title>Zircon ages of the Tucson Mountains</dc:title><dc:identifier>https://doi.org/10.5555/zircon</dc:identifier>"
    "<dc:description>Uranium-lead ages of zircon from twelve samples.</dc:description><dc:date>2024-03-30</dc:date></oai_dc:dc>"
)


@pytest.fixture
def db():
    assert os.environ.get("DATABASE_URL"), "DATABASE_URL must be set to run the upload tests"
    with TestClient(app):  # startup creates the tables
        pass
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        conn.sources = []
        yield conn
        conn.rollback()
        conn.execute("DELETE FROM harvest_sources WHERE id = ANY(%s::uuid[])", (conn.sources,))


@pytest.fixture
def client(db):
    admin = access.User(id="test-admin", permissions=access.GROUPS[access.ADMINS])
    app.dependency_overrides[auth.current_user] = lambda: admin
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.pop(auth.current_user)


def no_web(request):
    raise AssertionError(f"an upload run asked the web for {request.url}")


def send(client, db, files, **more):
    res = client.post("/api/harvest/uploads", json={"files": [{"name": n, "content": c} for n, c in files.items()], **more})
    if res.status_code == 201 and res.json()["source"]["id"] not in db.sources:
        db.sources.append(res.json()["source"]["id"])
    return res


def work(db, job_id):
    """What the worker does with a queued run."""
    with httpx.Client(transport=httpx.MockTransport(no_web)) as http:
        run.run_job(db, run.claim(db, job_id), http)
    errors = db.execute(
        "SELECT o.identifier, e.message FROM harvest_errors e LEFT JOIN harvest_objects o ON o.id = e.object_id WHERE e.job_id = %s",
        (job_id,),
    ).fetchall()
    return run.stats(db, job_id), {e["identifier"]: e["message"] for e in errors}


def records(db, source_id):
    return {r["source_identifier"]: r for r in db.execute("SELECT * FROM records WHERE source_id = %s", (source_id,))}


def test_uploaded_files_are_converted_checked_and_stored_like_harvested_ones(client, db):
    res = send(client, db, {"a.json": MINIMAL, "dc.xml": DUBLIN_CORE, "bad.json": INVALID, "notes.txt": "hello"}, title="Batch one")
    assert res.status_code == 201
    source, job = res.json()["source"], res.json()["job"]
    assert source["type"] == "upload" and source["title"] == "Batch one" and job["status"] == "new"

    stats, errors = work(db, job["id"])
    assert stats["added"] == 2 and stats["errored"] == 2
    found = records(db, source["id"])
    assert found["a.json"]["status"] == "published" and found["a.json"]["received_format"] == "cdif-jsonld"
    assert found["dc.xml"]["status"] == "published" and found["dc.xml"]["received_format"] == "dublin-core"
    assert found["bad.json"]["status"] == "invalid" and "must be fixed" in errors["bad.json"]
    assert found["notes.txt"]["status"] == "invalid" and found["notes.txt"]["received"] == "hello"


def test_adding_files_to_a_batch_reads_only_what_is_new_or_replaced(client, db):
    first = send(client, db, {"a.json": MINIMAL, "b.json": INVALID}, title="Batch")
    source = first.json()["source"]["id"]
    work(db, first.json()["job"]["id"])

    # b is sent again, corrected, and c is new; a is not sent and stays as it is
    second = send(client, db, {"b.json": COMPLETE, "c.xml": DUBLIN_CORE}, source=source)
    assert second.status_code == 201 and second.json()["source"]["id"] == source
    stats, errors = work(db, second.json()["job"]["id"])
    assert (stats["not modified"], stats["updated"], stats["added"], stats["deleted"]) == (1, 1, 1, 0) and errors == {}
    assert {name: r["status"] for name, r in records(db, source).items()} == {
        "a.json": "published", "b.json": "published", "c.xml": "published",
    }


def test_a_batch_is_refused_when_it_makes_no_sense(client, db):
    assert send(client, db, {"a.json": MINIMAL}).status_code == 422  # a new batch needs a name
    assert send(client, db, {}, title="Empty").status_code == 422
    assert send(client, db, {" ": MINIMAL}, title="No name").status_code == 422
    assert send(client, db, {"big.json": "x" * (upload.MAX_CHARACTERS + 1)}, title="Big").status_code == 422
    twice = client.post("/api/harvest/uploads", json={"title": "Twice", "files": [{"name": "a", "content": "1"}, {"name": "a", "content": "2"}]})
    assert twice.status_code == 422
    assert db.execute("SELECT count(*) AS n FROM harvest_sources WHERE title IN ('Empty', 'No name', 'Big', 'Twice')").fetchone()["n"] == 0


def test_files_cannot_be_added_to_a_source_with_an_address_or_while_a_run_is_waiting(client, db):
    folder = client.post("/api/harvest/sources", json={"title": "Folder", "url": "https://repo.example/records/", "type": "waf"}).json()
    db.sources.append(folder["id"])
    assert send(client, db, {"a.json": MINIMAL}, source=folder["id"]).status_code == 422
    first = send(client, db, {"a.json": MINIMAL}, title="Busy")
    assert send(client, db, {"b.json": MINIMAL}, source=first.json()["source"]["id"]).status_code == 409


def test_an_upload_is_not_offered_as_a_kind_of_address_and_cannot_be_registered_as_one(client, db):
    assert "upload" not in [t["type"] for t in client.get("/api/harvest/types").json()]
    res = client.post("/api/harvest/sources", json={"title": "x", "url": "https://repo.example/", "type": "upload"})
    assert res.status_code == 422


def test_uploading_needs_an_administrator(db):
    with TestClient(app) as anyone:
        res = anyone.post("/api/harvest/uploads", json={"title": "x", "files": [{"name": "a.json", "content": MINIMAL}]})
    assert res.status_code in (401, 403)
