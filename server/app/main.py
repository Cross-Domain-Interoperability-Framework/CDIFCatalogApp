import os
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel

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


def connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(503, "The database is not configured.")
    try:
        return psycopg.connect(url, connect_timeout=3, row_factory=dict_row)
    except psycopg.OperationalError:
        raise HTTPException(503, "The database is not reachable.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.environ.get("DATABASE_URL"):
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            conn.execute(SCHEMA)
    yield


app = FastAPI(title="CDIF Catalog", lifespan=lifespan)


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
            f"UPDATE drafts SET document = %s, updated_at = now() WHERE id = %s RETURNING {COLUMNS}",
            (Jsonb(body.document), draft_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "No draft with that id.")
    return row
