"""/api/harvest: register sources, start and stop runs, and read what a run did.

Every request here needs a signed-in user with the `harvest` permission, which to start with
only admins hold. Registering a source makes the server fetch an address of the caller's
choosing, so this is not something to leave open.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app import access, auth
from app.harvest import HarvestError, harvesters, run, upload
from app.store import connect

router = APIRouter(prefix="/api/harvest", dependencies=[Depends(auth.require(access.HARVEST))])


class NewSource(BaseModel):
    title: str
    url: str
    type: str
    config: dict = {}
    organisation: str | None = None
    frequency: str = "MANUAL"


@router.get("/types")
def source_types() -> list:
    # the kinds that have an address to give; files are uploaded, not registered
    return [{"type": h.type, "title": h.title} for h in harvesters().values() if h.type != "upload"]


@router.post("/sources", status_code=201)
def create_source(body: NewSource) -> dict:
    harvester = harvesters().get(body.type)
    if harvester is None:
        raise HTTPException(422, f"Unknown source type: {body.type}")
    if body.type == "upload":
        raise HTTPException(422, "Uploaded files have no address to register. Send them to /api/harvest/uploads.")
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


class UploadedFile(BaseModel):
    name: str
    content: str


class Upload(BaseModel):
    files: list[UploadedFile]
    title: str = ""  # for a new batch
    source: UUID | None = None  # to add files to a batch uploaded before
    organisation: str | None = None


@router.post("/uploads", status_code=201)
def upload_files(body: Upload) -> dict:
    """Take a batch of metadata files and queue a run that converts, checks and stores them.
    The files are sent as text. Without `source` a new batch is made, named by `title`."""
    names = [f.name.strip() for f in body.files]
    if not names or len(names) > upload.MAX_FILES:
        raise HTTPException(422, f"Send between 1 and {upload.MAX_FILES} files at a time.")
    if not all(names) or len(set(names)) != len(names):
        raise HTTPException(422, "Each file needs a name, and no two may share one.")
    too_long = [f.name for f in body.files if len(f.content) > upload.MAX_CHARACTERS]
    if too_long:
        raise HTTPException(422, f"Too large (over {upload.MAX_CHARACTERS:,} characters): {', '.join(too_long)}")
    with connect() as conn:
        if body.source is None:
            if not body.title.strip():
                raise HTTPException(422, "Give the batch a name.")
            source = conn.execute(
                "INSERT INTO harvest_sources (title, url, type, organisation) VALUES (%s, '', 'upload', %s) RETURNING *",
                (body.title.strip(), body.organisation),
            ).fetchone()
        else:
            source = _source(conn, body.source)
            if source["type"] != "upload":
                raise HTTPException(422, "That source is harvested from an address; files cannot be added to it.")
            open_job = conn.execute(
                "SELECT id FROM harvest_jobs WHERE source_id = %s AND status IN ('new', 'running')", (source["id"],)
            ).fetchone()
            if open_job:
                raise HTTPException(409, f"This source already has a run in progress: {open_job['id']}")
        upload.add_files(conn, source["id"], [(name, f.content) for name, f in zip(names, body.files)])
        job = conn.execute("INSERT INTO harvest_jobs (source_id) VALUES (%s) RETURNING *", (source["id"],)).fetchone()
    return {"source": source, "job": job}


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
            "SELECT e.stage, e.message, e.created_at, o.identifier, o.record_id FROM harvest_errors e "
            "LEFT JOIN harvest_objects o ON o.id = e.object_id WHERE e.job_id = %s ORDER BY e.created_at",
            (job_id,),
        ).fetchall()
        return {**job, "stats": run.stats(conn, job_id), "errors": errors}


@router.get("/records/{record_id}")
def read_harvested_record(record_id: UUID) -> dict:
    """A harvested record that did not publish, for an admin to see why. Gives the text as it was
    received and its format, the CDIF it became (null if it could not be mapped), the validation
    findings (null if it never reached validation), and its status."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id, status, source_identifier, received, received_format, source_cdif, "
            "published, validation, profile FROM records WHERE id = %s",
            (record_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "No record with that id.")
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "identifier": row["source_identifier"],
        "received": row["received"],
        "received_format": row["received_format"],
        "cdif": row["published"] or row["source_cdif"],  # what would be published, if it mapped
        "validation": row["validation"],
        "profile": row["profile"],
    }


@router.post("/jobs/{job_id}/retry", status_code=201)
def retry_job(job_id: UUID) -> dict:
    """Queue a run that looks again at only the records that ended in an error in this one.
    Each is fetched and imported afresh, whether or not its content has changed."""
    with connect() as conn:
        job = conn.execute("SELECT source_id, status FROM harvest_jobs WHERE id = %s", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(404, "No harvest job with that id.")
        if job["status"] in ("new", "running"):
            raise HTTPException(409, "That run has not finished yet.")
        open_job = conn.execute(
            "SELECT id FROM harvest_jobs WHERE source_id = %s AND status IN ('new', 'running')", (job["source_id"],)
        ).fetchone()
        if open_job:
            raise HTTPException(409, f"This source already has a run in progress: {open_job['id']}")
        failed = conn.execute(
            "SELECT count(*) AS n FROM harvest_objects WHERE job_id = %s AND outcome = 'errored'", (job_id,)
        ).fetchone()["n"]
        if failed == 0:
            raise HTTPException(422, "That run has no failed records to retry.")
        return conn.execute(
            "INSERT INTO harvest_jobs (source_id, retry_of) VALUES (%s, %s) RETURNING *", (job["source_id"], job_id)
        ).fetchone()


@router.post("/jobs/{job_id}/abort")
def abort_job(job_id: UUID) -> dict:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM harvest_jobs WHERE id = %s", (job_id,)).fetchone() is None:
            raise HTTPException(404, "No harvest job with that id.")
        return {"aborted": run.abort(conn, job_id, "Stopped by request.")}
