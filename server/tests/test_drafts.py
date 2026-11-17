"""Draft saving. These tests need a real PostgreSQL: set DATABASE_URL.

They fail, not skip, without one: a skipped test reads the same as a passing one.
Each test removes the rows it creates.
"""
import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    assert os.environ.get("DATABASE_URL"), "DATABASE_URL must be set to run the draft tests"
    created = []
    with TestClient(app) as c:  # the context manager runs startup, which creates the table
        c.created = created
        yield c
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("DELETE FROM drafts WHERE id = ANY(%s::uuid[])", (created,))


def new_draft(client, document):
    res = client.post("/api/drafts", json={"profile": "CoreDiscovery", "document": document})
    assert res.status_code == 201
    client.created.append(res.json()["id"])
    return res.json()


def test_a_saved_draft_reads_back_unchanged(client):
    # Keys with colons and @, nested lists, and non-ASCII text all have to survive the round trip.
    document = {
        "@type": ["schema:Dataset"],
        "schema:name": "Zircon U–Pb ages, Río Grande rift",
        "schema:creator": {"@list": [{"@type": "schema:Person", "schema:name": "A"}]},
    }
    draft = new_draft(client, document)
    assert draft["status"] == "draft"
    assert client.get(f"/api/drafts/{draft['id']}").json()["document"] == document


def test_update_replaces_the_document_and_moves_the_timestamp(client):
    draft = new_draft(client, {"schema:name": "first"})
    res = client.put(f"/api/drafts/{draft['id']}", json={"document": {"schema:name": "second"}})
    assert res.status_code == 200
    assert res.json()["updated_at"] > draft["updated_at"]
    assert client.get(f"/api/drafts/{draft['id']}").json()["document"] == {"schema:name": "second"}


def test_unknown_draft_is_404_on_read_and_on_update(client):
    missing = uuid4()
    assert client.get(f"/api/drafts/{missing}").status_code == 404
    assert client.put(f"/api/drafts/{missing}", json={"document": {}}).status_code == 404


def test_unknown_profile_is_rejected(client):
    res = client.post("/api/drafts", json={"profile": "NoSuchProfile", "document": {}})
    assert res.status_code == 422


def test_document_must_be_an_object(client):
    res = client.post("/api/drafts", json={"profile": "CoreDiscovery", "document": "text"})
    assert res.status_code == 422
