"""Sign-in with ORCID, and who the signed-in user is.

The catalog stores no passwords. A person proves who they are to ORCID; ORCID tells the catalog
their iD and name; the catalog keeps a session cookie that says which user this browser is.

Settings (see docs/setup-sandboxes.md):
  ORCID_BASE           https://sandbox.orcid.org for testing, https://orcid.org for real
  ORCID_CLIENT_ID      the registered client
  ORCID_CLIENT_SECRET  its secret; never logged, never returned
  ADMIN_ORCIDS         ORCID iDs, separated by commas, of the people who are admins
  PUBLIC_URL           the catalog's own address; ORCID sends the person back to it
"""
import hashlib
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app import access, store

router = APIRouter(prefix="/api/auth")

SESSION_COOKIE = "catalog_session"
STATE_COOKIE = "catalog_signin_state"
SESSION_DAYS = 14
CALLBACK_PATH = "/api/auth/orcid/callback"


def _setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise HTTPException(503, "Sign-in with ORCID is not set up on this server.")
    return value


def _public_url(request: Request) -> str:
    return (os.environ.get("PUBLIC_URL") or str(request.base_url)).rstrip("/")


def _secure(request: Request) -> bool:
    return _public_url(request).startswith("https://")


def admin_orcids() -> set[str]:
    return {iD.strip() for iD in os.environ.get("ADMIN_ORCIDS", "").split(",") if iD.strip()}


def _hash(token: str) -> str:
    """Sessions are stored by the hash of their token, so a copy of the table opens no session."""
    return hashlib.sha256(token.encode()).hexdigest()


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Swap the one-time code ORCID sent back for the person's iD and name. Kept as its own
    function so the tests can stand in for ORCID."""
    response = httpx.post(
        f"{_setting('ORCID_BASE').rstrip('/')}/oauth/token",
        data={
            "client_id": _setting("ORCID_CLIENT_ID"),
            "client_secret": _setting("ORCID_CLIENT_SECRET"),
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if response.status_code != 200:
        raise HTTPException(502, "ORCID did not confirm the sign-in. Try again.")
    return response.json()


# ---- the signed-in user -----------------------------------------------------------------------


def current_user(request: Request) -> access.User:
    """The user this request comes from: anonymous unless it carries a live session cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return access.ANONYMOUS
    with store.connect() as conn:
        row = conn.execute(
            "SELECT u.id, u.orcid, u.name, u.groups, u.organisations FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token_hash = %s AND s.expires_at > now()",
            (_hash(token),),
        ).fetchone()
    if row is None:
        return access.ANONYMOUS
    return access.User(
        id=str(row["id"]),
        organisations=tuple(row["organisations"]),
        permissions=access.permissions_of(row["groups"]),
        orcid=row["orcid"],
        name=row["name"],
        groups=tuple(row["groups"]),
    )


def require(permission: str):
    """A dependency that lets a request through only for a signed-in user holding a permission."""

    def check(user: access.User = Depends(current_user)) -> access.User:
        if user.id is None:
            raise HTTPException(401, "Sign in to do this.")
        if permission not in user.permissions:
            raise HTTPException(403, "Your account is not allowed to do this.")
        return user

    return check


# ---- the sign-in round trip -------------------------------------------------------------------


@router.get("/orcid/login")
def login(request: Request) -> Response:
    """Send the person to ORCID to sign in. The state value comes back with them and must match
    the cookie set here, which proves the return belongs to this browser's own request."""
    state = secrets.token_urlsafe(24)
    query = urlencode({
        "client_id": _setting("ORCID_CLIENT_ID"),
        "response_type": "code",
        "scope": "/authenticate",
        "redirect_uri": _public_url(request) + CALLBACK_PATH,
        "state": state,
    })
    response = RedirectResponse(f"{_setting('ORCID_BASE').rstrip('/')}/oauth/authorize?{query}", status_code=302)
    response.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", secure=_secure(request))
    return response


@router.get("/orcid/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
    home = _public_url(request) + "/"
    if error or not code:  # the person pressed Deny at ORCID, or came here without signing in
        response = RedirectResponse(home + "?signin=cancelled", status_code=302)
        response.delete_cookie(STATE_COOKIE)
        return response
    expected = request.cookies.get(STATE_COOKIE)
    if not state or not expected or not secrets.compare_digest(state, expected):
        raise HTTPException(400, "This sign-in did not start in this browser. Start again from the catalog.")

    answer = exchange_code(code, _public_url(request) + CALLBACK_PATH)
    orcid = answer.get("orcid")
    if not isinstance(orcid, str) or not orcid:
        raise HTTPException(502, "ORCID did not say who signed in. Try again.")
    name = answer.get("name") if isinstance(answer.get("name"), str) else None

    token = secrets.token_urlsafe(32)
    with store.connect() as conn:
        user = conn.execute(
            "INSERT INTO users (orcid, name) VALUES (%s, %s) "
            "ON CONFLICT (orcid) DO UPDATE SET name = coalesce(EXCLUDED.name, users.name), last_login = now() "
            "RETURNING id, groups",
            (orcid, name),
        ).fetchone()
        # Admins are named in a setting, so the first admin needs no admin to appoint them. The
        # setting only ever adds the group; taking it away is done in the database.
        if orcid in admin_orcids() and access.ADMINS not in user["groups"]:
            conn.execute("UPDATE users SET groups = array_append(groups, %s) WHERE id = %s", (access.ADMINS, user["id"]))
        conn.execute("DELETE FROM sessions WHERE expires_at < now()")
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + make_interval(days => %s))",
            (_hash(token), user["id"], SESSION_DAYS),
        )
    response = RedirectResponse(home, status_code=302)
    response.delete_cookie(STATE_COOKIE)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=_secure(request)
    )
    return response


@router.get("/me")
def me(request: Request, user: access.User = Depends(current_user)) -> dict:
    """Who is signed in, for the page header. `configured` tells the page whether to offer sign-in."""
    configured = all(os.environ.get(k, "").strip() for k in ("ORCID_BASE", "ORCID_CLIENT_ID", "ORCID_CLIENT_SECRET"))
    # ORCID returns the person to PUBLIC_URL, so sign-in has to start there too or its cookie
    # will not come back with them. The page uses this to link to the right address when it was
    # opened under another name for the same machine (localhost, which ORCID refuses). The
    # server cannot tell which name the browser used: a proxy in front may rewrite it.
    base = {"configured": configured, "sign_in_url": f"{_public_url(request)}/api/auth/orcid/login"}
    if user.id is None:
        return {"signed_in": False, **base}
    return {
        "signed_in": True, **base, "orcid": user.orcid, "name": user.name,
        "groups": list(user.groups), "permissions": sorted(user.permissions),
    }


@router.post("/logout")
def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with store.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_hash(token),))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE)
    return response
