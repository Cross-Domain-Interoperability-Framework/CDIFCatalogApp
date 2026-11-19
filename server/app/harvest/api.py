"""/api/harvest: register sources, start and stop runs, and read what a run did.

Until sign-in exists these are open to anyone who can reach the server, and registering a source
makes the server fetch an address of the caller's choosing. That is acceptable only on a
developer machine.
"""
from uuid import UUID

from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app.harvest import HarvestError, harvesters, run
from app.store import connect

router = APIRouter(prefix="/api/harvest")


class NewSource(BaseModel):
    title: str
    url: str
    type: str
    config: dict = {}
    organisation: str | None = None
    frequency: str = "MANUAL"


@router.get("/types")
def source_types() -> list:
    return [{"type": h.type, "title": h.title} for h in harvesters().values()]


@router.post("/sources", status_code=201)
def create_source(body: NewSource) -> dict:
    harvester = harvesters().get(body.type)
    if harvester is None:
        raise HTTPException(422, f"Unknown source type: {body.type}")
    if body.frequency not in run.FREQUENCIES:
        raise HTTPException(422, "Frequency must be one of: " + ", ".join(run.FREQUENCIES))
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(422, "The address must start with http:// or https://")
    try:
        config = harvester.validate_config(body.config)
    except HarvestError as e:
        raise HTTPException(422, str(e))
    with connect() as conn:
        return conn.execute(
            "INSERT INTO harvest_sources (title, url, type, config, organisation, frequency) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
            (body.title, body.url, body.type, Jsonb(config), body.organisation, body.frequency),
        ).fetchone()


@router.get("/sources")
def list_sources() -> list:
    with connect() as conn:
        return conn.execute("SELECT * FROM harvest_sources ORDER BY created_at").fetchall()


def _source(conn, source_id):
    source = conn.execute("SELECT * FROM harvest_sources WHERE id = %s", (source_id,)).fetchone()
    if source is None:
        raise HTTPException(404, "No harvest source with that id.")
    return source


@router.get("/sources/{source_id}")
def read_source(source_id: UUID) -> dict:
    with connect() as conn:
        source = _source(conn, source_id)
        jobs = conn.execute(
            "SELECT id, status, created_at, finished FROM harvest_jobs WHERE source_id = %s "
            "ORDER BY created_at DESC LIMIT 10",
            (source_id,),
        ).fetchall()
        records = conn.execute(
            "SELECT status, count(*) AS n FROM records WHERE source_id = %s GROUP BY status", (source_id,)
        ).fetchall()
    return {**source, "jobs": jobs, "records": {r["status"]: r["n"] for r in records}}


@router.post("/sources/{source_id}/jobs", status_code=201)
def start_job(source_id: UUID) -> dict:
    """Queue a run. The worker picks it up; read the job to follow it."""
    with connect() as conn:
        _source(conn, source_id)
        open_job = conn.execute(
            "SELECT id FROM harvest_jobs WHERE source_id = %s AND status IN ('new', 'running')", (source_id,)
        ).fetchone()
        if open_job:
            raise HTTPException(409, f"This source already has a run in progress: {open_job['id']}")
        return conn.execute("INSERT INTO harvest_jobs (source_id) VALUES (%s) RETURNING *", (source_id,)).fetchone()


@router.post("/sources/{source_id}/clear")
def clear_source(source_id: UUID) -> dict:
    """Remove every record and every run of a source, keeping the source itself."""
    with connect() as conn:
        _source(conn, source_id)
        jobs = conn.execute("DELETE FROM harvest_jobs WHERE source_id = %s", (source_id,)).rowcount
        records = conn.execute("DELETE FROM records WHERE source_id = %s", (source_id,)).rowcount
    return {"records_removed": records, "jobs_removed": jobs}


@router.get("/jobs/{job_id}")
def read_job(job_id: UUID) -> dict:
    with connect() as conn:
        job = conn.execute("SELECT * FROM harvest_jobs WHERE id = %s", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(404, "No harvest job with that id.")
        errors = conn.execute(
            "SELECT e.stage, e.message, e.created_at, o.identifier FROM harvest_errors e "
            "LEFT JOIN harvest_objects o ON o.id = e.object_id WHERE e.job_id = %s ORDER BY e.created_at",
            (job_id,),
        ).fetchall()
        return {**job, "stats": run.stats(conn, job_id), "errors": errors}


@router.post("/jobs/{job_id}/abort")
def abort_job(job_id: UUID) -> dict:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM harvest_jobs WHERE id = %s", (job_id,)).fetchone() is None:
            raise HTTPException(404, "No harvest job with that id.")
        return {"aborted": run.abort(conn, job_id, "Stopped by request.")}
