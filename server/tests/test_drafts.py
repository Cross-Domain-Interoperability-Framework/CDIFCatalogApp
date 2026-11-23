"""Draft saving. These tests need a real PostgreSQL: set DATABASE_URL.

They fail, not skip, without one: a skipped test reads the same as a passing one.
Each test removes the rows it creates.
"""
import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import access, auth
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


VALID = {
    "@type": ["schema:Dataset"],
    "schema:name": "Zircon ages",
    "schema:identifier": "https://doi.org/10.5555/x",
    "schema:dateModified": "2024-03-30",
    "schema:url": "https://repository.example/1",
    "schema:license": [
        {"@type": "schema:CreativeWork", "schema:name": "CC BY 4.0", "schema:url": "https://creativecommons.org/licenses/by/4.0/"}
    ],
}


def test_submit_is_refused_while_the_record_has_violations(client):
    draft = new_draft(client, {"@type": ["schema:Dataset"], "schema:name": "Only a name"})
    res = client.post(f"/api/drafts/{draft['id']}/submit").json()
    assert res["submitted"] is False and res["counts"]["violation"] > 0
    assert client.get(f"/api/drafts/{draft['id']}").json()["status"] == "draft"


def test_a_valid_record_submits_and_an_edit_makes_it_a_draft_again(client):
    draft = new_draft(client, VALID)
    res = client.post(f"/api/drafts/{draft['id']}/submit").json()
    assert res["submitted"] is True
    assert res["record"]["@id"] == f"urn:uuid:{draft['id']}"
    assert client.get(f"/api/drafts/{draft['id']}").json()["status"] == "submitted"
    edited = client.put(f"/api/drafts/{draft['id']}", json={"document": {**VALID, "schema:name": "x"}})
    assert edited.json()["status"] == "draft"


def test_submitting_an_unknown_draft_is_404(client):
    assert client.post(f"/api/drafts/{uuid4()}/submit").status_code == 404


def signed_in_as(user_id):
    """Sign-in itself is tested in test_auth.py; here the person is simply assumed. None signs out."""
    user = access.User(id=user_id) if user_id else access.ANONYMOUS
    app.dependency_overrides[auth.current_user] = lambda: user


@pytest.fixture
def people():
    yield signed_in_as
    app.dependency_overrides.pop(auth.current_user, None)


def test_a_draft_saved_while_signed_in_does_not_exist_for_anyone_else(client, people):
    people("test-ana")
    draft = new_draft(client, VALID)
    address = f"/api/drafts/{draft['id']}"
    for other in ("test-ben", None):
        people(other)
        assert client.get(address).status_code == 404
        assert client.put(address, json={"document": {"schema:name": "taken"}}).status_code == 404
        assert client.post(f"{address}/submit").status_code == 404
    people("test-ana")
    assert client.get(address).json()["document"] == VALID
    assert client.post(f"{address}/submit").json()["submitted"] is True


def test_a_draft_started_signed_out_becomes_the_persons_own_when_they_save_it(client, people):
    draft = new_draft(client, {"schema:name": "begun signed out"})
    address = f"/api/drafts/{draft['id']}"
    people("test-ana")
    assert client.put(address, json={"document": {"schema:name": "kept"}}).status_code == 200
    people(None)
    assert client.get(address).status_code == 404


def test_a_person_is_listed_their_own_drafts_newest_first_and_nobody_elses(client, people):
    assert client.get("/api/drafts").json() == []  # nobody signed in
    people("test-ben")
    new_draft(client, {"schema:name": "Ben's"})
    people("test-ana")
    first = new_draft(client, {"schema:name": "first"})
    second = new_draft(client, {})
    listed = client.get("/api/drafts").json()
    assert [(d["id"], d["name"], d["status"]) for d in listed] == [
        (second["id"], None, "draft"), (first["id"], "first", "draft"),
    ]
