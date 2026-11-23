import os
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app import auth, lookup, outbound, store, validate
from app.harvest import api as harvest_api
from app.store import connect

# Profiles a draft may be written against. The form files for each live in web/public/forms/.
PROFILES = {"CoreDiscovery"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile     text NOT NULL,
    document    jsonb NOT NULL,
    status      text NOT NULL DEFAULT 'draft',
    owner       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
)
"""

COLUMNS = "id, profile, document, status, created_at, updated_at"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.environ.get("DATABASE_URL"):
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            conn.execute(SCHEMA)
            conn.execute(store.SCHEMA)
    yield


app = FastAPI(title="CDIF Catalog", lifespan=lifespan)
app.include_router(lookup.router)
app.include_router(validate.router)
app.include_router(harvest_api.router)
app.include_router(outbound.router)
app.include_router(auth.router)


def database_status() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "not configured"
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return "ok"
    except psycopg.Error:
        return "unavailable"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "database": database_status()}


class NewDraft(BaseModel):
    profile: str
    document: dict


class DraftUpdate(BaseModel):
    document: dict


# Until sign-in exists, a draft is reachable by anyone who knows its id. The id is a random
# UUID, which is enough for a local prototype and not enough for a public deployment.


@app.post("/api/drafts", status_code=201)
def create_draft(body: NewDraft) -> dict:
    if body.profile not in PROFILES:
        raise HTTPException(422, f"Unknown profile: {body.profile}")
    with connect() as conn:
        return conn.execute(
            f"INSERT INTO drafts (profile, document) VALUES (%s, %s) RETURNING {COLUMNS}",
            (body.profile, Jsonb(body.document)),
        ).fetchone()


@app.get("/api/drafts/{draft_id}")
def read_draft(draft_id: UUID) -> dict:
    with connect() as conn:
        row = conn.execute(f"SELECT {COLUMNS} FROM drafts WHERE id = %s", (draft_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No draft with that id.")
    return row


@app.put("/api/drafts/{draft_id}")
def update_draft(draft_id: UUID, body: DraftUpdate) -> dict:
    with connect() as conn:
        row = conn.execute(
            # an edit after submission makes it a draft again; it must be checked and submitted anew
            f"UPDATE drafts SET document = %s, status = 'draft', updated_at = now() WHERE id = %s RETURNING {COLUMNS}",
            (Jsonb(body.document), draft_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "No draft with that id.")
    return row


@app.post("/api/drafts/{draft_id}/submit")
def submit_draft(draft_id: UUID) -> dict:
    """Mark a draft as submitted, but only if the server finds no violation in it. The check is
    made here on the stored document, never taken from what the browser says it found."""
    with connect() as conn:
        row = conn.execute("SELECT profile, document FROM drafts WHERE id = %s", (draft_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "No draft with that id.")
        report = validate.check(row["profile"], row["document"], str(draft_id))
        if report["valid"]:
            conn.execute("UPDATE drafts SET status = 'submitted', updated_at = now() WHERE id = %s", (draft_id,))
    return {"submitted": report["valid"], **report}


# In the deployed image the built web app sits beside the server, which serves it (WEB_DIR, set in
# deploy/Dockerfile). In development Vite serves it. Mounted last, so every route above wins.
if os.environ.get("WEB_DIR"):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=os.environ["WEB_DIR"], html=True), name="web")
