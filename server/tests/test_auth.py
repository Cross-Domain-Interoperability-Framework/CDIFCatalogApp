"""Sign-in with ORCID, sessions, and the admin-only harvest API.

Needs a real PostgreSQL (DATABASE_URL); fails, not skips, without one. ORCID itself is stood in
for: `auth.exchange_code` is replaced, so these tests prove the catalog's side of the round trip
and nothing about ORCID's. That needs one sign-in against the sandbox with a real client.
"""
import os
from urllib.parse import parse_qs, urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import access, auth
from app.main import app

PUBLIC = "https://catalog.example"
ADMIN = "0000-0002-1825-0097"  # ORCID's own published example iD
OTHER = "0000-0001-5109-3700"
WAF = {"title": "Folder", "url": "https://repo.example/records/", "type": "waf"}


@pytest.fixture
def client(monkeypatch):
    assert os.environ.get("DATABASE_URL"), "DATABASE_URL must be set to run the sign-in tests"
    monkeypatch.setenv("PUBLIC_URL", PUBLIC)
    monkeypatch.setenv("ORCID_BASE", "https://sandbox.orcid.org")
    monkeypatch.setenv("ORCID_CLIENT_ID", "APP-TESTTESTTESTTEST")
    monkeypatch.setenv("ORCID_CLIENT_SECRET", "not-a-real-secret")
    monkeypatch.setenv("ADMIN_ORCIDS", f" {ADMIN} , ")
    people = {"code-admin": {"orcid": ADMIN, "name": "Ada Admin"}, "code-other": {"orcid": OTHER, "name": "Otto Other"}}
    asked = []

    def exchange(code, redirect_uri):
        asked.append((code, redirect_uri))
        return people[code]

    monkeypatch.setattr(auth, "exchange_code", exchange)
    # https so that the Secure session cookie is sent back, as a browser would
    with TestClient(app, base_url=PUBLIC, follow_redirects=False) as c:
        c.asked = asked
        yield c
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("DELETE FROM harvest_sources WHERE url = %s", (WAF["url"],))
        conn.execute("DELETE FROM users WHERE orcid = ANY(%s)", ([ADMIN, OTHER],))


def sign_in(client, code):
    start = client.get("/api/auth/orcid/login")
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    return client.get("/api/auth/orcid/callback", params={"code": code, "state": state})


def test_login_sends_the_person_to_orcid_with_this_catalogs_return_address(client):
    res = client.get("/api/auth/orcid/login")
    assert res.status_code == 302
    target = urlsplit(res.headers["location"])
    query = parse_qs(target.query)
    assert f"{target.scheme}://{target.netloc}{target.path}" == "https://sandbox.orcid.org/oauth/authorize"
    assert query["client_id"] == ["APP-TESTTESTTESTTEST"] and query["response_type"] == ["code"]
    assert query["scope"] == ["/authenticate"]
    assert query["redirect_uri"] == [f"{PUBLIC}/api/auth/orcid/callback"]
    assert "not-a-real-secret" not in res.headers["location"]
    cookie = res.headers["set-cookie"]
    assert query["state"][0] in cookie and "HttpOnly" in cookie and "Secure" in cookie


def test_the_page_is_told_to_start_sign_in_at_the_public_address_whatever_host_the_request_names(client):
    # The page may have been opened as localhost, and a proxy may rewrite the host before it gets
    # here. ORCID returns the person to the public address, so sign-in must start there.
    for host in ("localhost:5173", "api:8000"):
        me = client.get("/api/auth/me", headers={"host": host}).json()
        assert me["sign_in_url"] == f"{PUBLIC}/api/auth/orcid/login"
        login = client.get("/api/auth/orcid/login", headers={"host": host})
        assert login.headers["location"].startswith("https://sandbox.orcid.org/oauth/authorize?")


def test_signing_in_creates_the_user_and_a_session(client):
    assert client.get("/api/auth/me").json()["signed_in"] is False
    res = sign_in(client, "code-other")
    assert res.status_code == 302 and res.headers["location"] == f"{PUBLIC}/"
    assert client.asked == [("code-other", f"{PUBLIC}/api/auth/orcid/callback")]
    me = client.get("/api/auth/me").json()
    assert me["signed_in"] is True and me["orcid"] == OTHER and me["name"] == "Otto Other"
    assert me["groups"] == [] and me["permissions"] == []


def test_the_session_cookie_is_not_readable_by_scripts_and_is_stored_only_as_a_hash(client):
    res = sign_in(client, "code-other")
    cookie = next(c for c in res.headers.get_list("set-cookie") if c.startswith(auth.SESSION_COOKIE))
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Secure" in cookie
    token = client.cookies[auth.SESSION_COOKIE]
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        stored = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
    assert token not in stored and auth._hash(token) in stored


def test_a_return_that_did_not_start_in_this_browser_is_refused(client):
    client.get("/api/auth/orcid/login")
    assert client.get("/api/auth/orcid/callback", params={"code": "code-admin", "state": "forged"}).status_code == 400
    client.cookies.clear()
    assert client.get("/api/auth/orcid/callback", params={"code": "code-admin", "state": "x"}).status_code == 400
    assert client.asked == [] and client.get("/api/auth/me").json()["signed_in"] is False


def test_pressing_deny_at_orcid_returns_to_the_catalog_signed_out(client):
    client.get("/api/auth/orcid/login")
    res = client.get("/api/auth/orcid/callback", params={"error": "access_denied"})
    assert res.status_code == 302 and res.headers["location"] == f"{PUBLIC}/?signin=cancelled"
    assert client.get("/api/auth/me").json()["signed_in"] is False


def test_a_person_named_in_the_admin_setting_becomes_an_admin(client):
    sign_in(client, "code-admin")
    me = client.get("/api/auth/me").json()
    assert me["groups"] == ["admins"] and access.HARVEST in me["permissions"]


def test_signing_out_ends_the_session_on_the_server_too(client):
    sign_in(client, "code-admin")
    token = client.cookies[auth.SESSION_COOKIE]
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").json()["signed_in"] is False
    client.cookies.set(auth.SESSION_COOKIE, token)  # a copy of the old cookie no longer works
    assert client.get("/api/auth/me").json()["signed_in"] is False


def test_an_expired_or_made_up_session_is_anonymous(client):
    sign_in(client, "code-admin")
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("UPDATE sessions SET expires_at = now() - interval '1 minute'")
    assert client.get("/api/auth/me").json()["signed_in"] is False
    client.cookies.set(auth.SESSION_COOKIE, "made-up")
    assert client.get("/api/auth/me").json()["signed_in"] is False


def test_the_harvest_api_is_for_signed_in_admins_only(client):
    # nobody signed in
    assert client.post("/api/harvest/sources", json=WAF).status_code == 401
    assert client.get("/api/harvest/sources").status_code == 401
    assert client.get("/api/harvest/types").status_code == 401
    # signed in, but not an admin
    sign_in(client, "code-other")
    assert client.post("/api/harvest/sources", json=WAF).status_code == 403
    assert client.get("/api/harvest/sources").status_code == 403
    client.post("/api/auth/logout")
    # an admin
    sign_in(client, "code-admin")
    created = client.post("/api/harvest/sources", json=WAF)
    assert created.status_code == 201
    assert client.post(f"/api/harvest/sources/{created.json()['id']}/jobs").status_code == 201


def test_reading_the_catalog_needs_no_sign_in(client):
    assert client.get("/catalog.ttl").status_code == 200


def test_without_a_registered_client_sign_in_says_it_is_not_set_up(client, monkeypatch):
    monkeypatch.delenv("ORCID_CLIENT_ID")
    assert client.get("/api/auth/orcid/login").status_code == 503
    me = client.get("/api/auth/me").json()
    assert me["signed_in"] is False and me["configured"] is False


def test_an_unknown_group_carries_no_permissions():
    assert access.permissions_of(["admins", "no-such-group"]) == access.GROUPS["admins"]
    assert access.permissions_of([]) == frozenset()
