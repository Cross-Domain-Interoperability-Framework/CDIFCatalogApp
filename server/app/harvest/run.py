"""Runs one harvest job: gather, then fetch and import each record, writing what happened.

Every record a run touches gets a row in `harvest_objects` ending in one outcome: added, updated,
not modified, deleted or errored. Every failure is a row in `harvest_errors` naming its stage.
Work is committed record by record, so a run can be watched, and aborted between records.
"""
from psycopg.types.json import Jsonb

from app import access, store, validate
from app.harvest import HarvestError, Item, convert, harvesters
from app.harvest.detect import detect
from app.harvest.robots import Polite

DEFAULT_PROFILE = "CoreDiscovery"
# Sent with every request, and the name a site's robots.txt rules are matched against.
USER_AGENT = "CDIFCatalogApp-harvester"

# How often a scheduled source runs. MANUAL sources run only when asked.
FREQUENCIES = {"MANUAL": None, "DAILY": "1 day", "WEEKLY": "7 days", "BIWEEKLY": "14 days", "MONTHLY": "1 month"}


def claim(conn, job_id=None):
    """Take one waiting job and mark it running, or return None. Safe with several workers:
    a job another worker is taking is skipped, not waited for."""
    pick = "id = %s AND status = 'new'" if job_id else "status = 'new'"
    job = conn.execute(
        "UPDATE harvest_jobs SET status = 'running', gather_started = now() WHERE id = ("
        f"  SELECT id FROM harvest_jobs WHERE {pick} ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
        ") RETURNING *",
        (job_id,) if job_id else (),
    ).fetchone()
    conn.commit()
    return job


def last_error_free_start(conn, source_id, not_job):
    """When the last run that finished without any error began. A source is asked only for
    changes since then; after a run with errors the next one asks for everything again, so a
    failure cannot hide a record for good."""
    row = conn.execute(
        "SELECT gather_started FROM harvest_jobs j "
        "WHERE source_id = %s AND id <> %s AND status = 'finished' AND gather_started IS NOT NULL "
        "AND retry_of IS NULL "  # a retry looks at a few records only, so it proves nothing about the rest
        "AND NOT EXISTS (SELECT 1 FROM harvest_errors e WHERE e.job_id = j.id) "
        "ORDER BY gather_started DESC LIMIT 1",
        (source_id, not_job),
    ).fetchone()
    return row["gather_started"] if row else None


def _error(conn, job_id, object_id, stage: str, problem) -> None:
    message = str(problem) if isinstance(problem, HarvestError) else f"{type(problem).__name__}: {problem}"
    conn.execute(
        "INSERT INTO harvest_errors (job_id, object_id, stage, message) VALUES (%s, %s, %s, %s)",
        (job_id, object_id, stage, message[:2000]),
    )


def _close(conn, obj, outcome: str, record_id=None) -> None:
    """Finish an object. The newest object that left a record in place is the current one for
    its identifier."""
    current = outcome in ("added", "updated", "not modified")
    if current:
        conn.execute(
            "UPDATE harvest_objects SET current = false WHERE source_id = %s AND identifier = %s AND current",
            (obj["source_id"], obj["identifier"]),
        )
    conn.execute(
        "UPDATE harvest_objects SET state = 'done', outcome = %s, current = %s, record_id = %s, "
        "finished_at = now() WHERE id = %s",
        (outcome, current, record_id, obj["id"]),
    )


def _finish(conn, job_id) -> None:
    conn.execute(
        "UPDATE harvest_jobs SET status = 'finished', finished = now() WHERE id = %s AND status = 'running'",
        (job_id,),
    )
    conn.commit()


def run_job(conn, job: dict, http) -> None:
    """Run a job that `claim` has marked running."""
    job_id = job["id"]
    source = conn.execute("SELECT * FROM harvest_sources WHERE id = %s", (job["source_id"],)).fetchone()
    harvester = harvesters().get(source["type"])
    retrying = job.get("retry_of") is not None
    missing = []  # records the source no longer lists

    # ---- gather: what does the source hold? ----
    try:
        if harvester is None:
            raise HarvestError(f"No harvester is installed for the source type '{source['type']}'.")
        source = {**source, "config": harvester.validate_config(source["config"] or {})}
        if not source["config"].get("ignore_robots"):
            http = Polite(http, USER_AGENT)
        if retrying:
            _gather_failures(conn, job)
        else:
            since = last_error_free_start(conn, source["id"], job_id)
            gathered = harvester.gather(source, since, http)
            missing = _record_gathered(conn, job_id, source, gathered)
    except Exception as e:  # a source can fail in ways no harvester foresaw; record it, never crash
        conn.rollback()
        _error(conn, job_id, None, "gather", e)
        _finish(conn, job_id)
        return
    conn.execute("UPDATE harvest_jobs SET gather_finished = now() WHERE id = %s", (job_id,))
    conn.commit()

    # ---- fetch and import, one record at a time ----
    waiting = conn.execute(
        "SELECT * FROM harvest_objects WHERE job_id = %s AND state = 'waiting' ORDER BY identifier", (job_id,)
    ).fetchall()
    for obj in waiting:
        status = conn.execute("SELECT status FROM harvest_jobs WHERE id = %s", (job_id,)).fetchone()["status"]
        if status != "running":  # aborted while running
            return
        _harvest_one(conn, harvester, source, obj, http, force=retrying)
        conn.commit()

    # ---- withdraw what the source no longer lists ----
    # Only after a run in which every listed record could be fetched. If the source was
    # misbehaving, its listing is not to be trusted either, and a record wrongly withdrawn is
    # worse than one withdrawn a run late. (Esri's Geoportal harvester has the same rule.)
    if missing:
        trouble = conn.execute(
            "SELECT count(*) AS n FROM harvest_errors WHERE job_id = %s AND stage = 'fetch'", (job_id,)
        ).fetchone()["n"]
        if trouble == 0:
            for record_id, identifier in missing:
                obj = conn.execute(
                    "INSERT INTO harvest_objects (job_id, source_id, identifier) VALUES (%s, %s, %s) RETURNING *",
                    (job_id, source["id"], identifier),
                ).fetchone()
                store.set_status(conn, record_id, "withdrawn")
                _close(conn, obj, "deleted", record_id)
    _finish(conn, job_id)


def _record_gathered(conn, job_id, source: dict, gathered) -> list:
    """Write an object for everything the source listed, closing at once those whose own
    modified date has not moved. Returns (record id, identifier) for stored records the source
    no longer lists, when its listing was complete."""
    stored = {
        r["source_identifier"]: r
        for r in conn.execute(
            "SELECT id, source_identifier, source_modified, content_hash, status FROM records WHERE source_id = %s",
            (source["id"],),
        )
    }
    seen = set()
    for item in gathered.items:
        if item.identifier in seen:
            continue
        seen.add(item.identifier)
        known = stored.get(item.identifier)
        # The source's own modified date has not moved: no need to fetch the record at all.
        unchanged = bool(
            known and known["status"] != "withdrawn" and item.modified and known["source_modified"]
            and item.modified <= known["source_modified"]
        )
        obj = conn.execute(
            "INSERT INTO harvest_objects (job_id, source_id, identifier, url, modified) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (job_id, source["id"], item.identifier, item.url, item.modified),
        ).fetchone()
        if unchanged:
            conn.execute("UPDATE records SET last_harvested = now() WHERE id = %s", (known["id"],))
            _close(conn, obj, "not modified", known["id"])
    if not gathered.complete:
        return []
    return [
        (known["id"], identifier) for identifier, known in stored.items()
        if identifier not in seen and known["status"] != "withdrawn"
    ]


def _gather_failures(conn, job: dict) -> None:
    """For a retry: queue again only the records that ended in an error in the earlier run."""
    conn.execute(
        "INSERT INTO harvest_objects (job_id, source_id, identifier, url, modified) "
        "SELECT %s, source_id, identifier, url, modified FROM harvest_objects "
        "WHERE job_id = %s AND outcome = 'errored'",
        (job["id"], job["retry_of"]),
    )


def _harvest_one(conn, harvester, source: dict, obj: dict, http, force: bool = False) -> None:
    job_id = obj["job_id"]
    item = Item(obj["identifier"], obj["url"], obj["modified"])
    try:
        fetched = harvester.fetch(source, item, http)
    except Exception as e:
        _error(conn, job_id, obj["id"], "fetch", e)
        _close(conn, obj, "errored")
        return

    known = conn.execute(
        "SELECT * FROM records WHERE source_id = %s AND source_identifier = %s", (source["id"], item.identifier)
    ).fetchone()
    digest = store.content_hash(fetched.content)
    # Unchanged content needs no second look, except on a retry, which exists to look again.
    if known and known["content_hash"] == digest and known["status"] != "withdrawn" and not force:
        conn.execute(
            "UPDATE records SET last_harvested = now(), source_modified = %s WHERE id = %s",
            (item.modified, known["id"]),
        )
        _close(conn, obj, "not modified", known["id"])
        return

    detected = detect(fetched.content, fetched.content_type, item.url)
    # A CDIF record says which profiles it follows; that, not a setting, picks what it is checked against.
    profile = validate.profile_for(detected.conforms_to, source["config"].get("profile", DEFAULT_PROFILE))
    overlay = known["overlay"] if known else {}
    cdif = published = report = None
    problem = None
    try:
        cdif = convert.to_cdif(detected, fetched.content)
        if detected.format != "cdif-jsonld":
            # The catalog made this record, so the catalog says what it conforms to.
            cdif, profile = convert.claim(cdif, profile)
        conflicts = store.overlay_conflicts(known["source_cdif"] if known else None, cdif, overlay)
        if conflicts:
            # Changed at the source in a property a data manager has overridden: keep what is
            # published and leave the choice to a person.
            status, published, report = "conflict", known["published"], known["validation"]
            problem = HarvestError("Changed at the source in properties edited here: " + ", ".join(conflicts) + ".")
        else:
            published = store.apply_overlay(cdif, overlay)
            report = validate.check_record(profile, published)
            report = {k: report[k] for k in ("valid", "counts", "findings")}
            report["declared"] = list(detected.conforms_to)
            status = "published" if report["valid"] else "invalid"
            if not report["valid"]:
                n = report["counts"]["violation"]
                problem = HarvestError(
                    f"The record has {n} problem{'s' if n != 1 else ''} that must be fixed. "
                    "It is stored but not published."
                )
    except Exception as e:
        # Not mappable or not checkable. The text as received is still kept, so the record can
        # be mapped again later without another harvest.
        status, problem = "invalid", e

    labels = access.record_labels(status, source["organisation"])
    values = (
        fetched.content, detected.format, Jsonb(cdif), Jsonb(published), Jsonb(report), digest,
        item.modified, status, labels, profile,
    )
    if known:
        conn.execute(
            "UPDATE records SET received = %s, received_format = %s, source_cdif = %s, published = %s, "
            "validation = %s, content_hash = %s, source_modified = %s, status = %s, labels = %s, profile = %s, "
            "last_harvested = now(), changed_at = now() WHERE id = %s",
            values + (known["id"],),
        )
        record_id = known["id"]
    else:
        record_id = conn.execute(
            "INSERT INTO records (received, received_format, source_cdif, published, validation, content_hash, "
            "source_modified, status, labels, profile, source_id, source_identifier, organisation, "
            "first_harvested, last_harvested) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now()) RETURNING id",
            values + (source["id"], item.identifier, source["organisation"]),
        ).fetchone()["id"]

    if problem is not None:
        _error(conn, job_id, obj["id"], "import", problem)
        _close(conn, obj, "errored", record_id)
    else:
        _close(conn, obj, "updated" if known else "added", record_id)


# ---- what the worker does between jobs --------------------------------------------------------


def schedule_due(conn) -> int:
    """Start a job for every scheduled source whose time has come and which has none open."""
    due = conn.execute(
        "SELECT id, frequency FROM harvest_sources s WHERE active AND frequency <> 'MANUAL' "
        "AND (next_run IS NULL OR next_run <= now()) "
        "AND NOT EXISTS (SELECT 1 FROM harvest_jobs j WHERE j.source_id = s.id AND j.status IN ('new', 'running'))"
    ).fetchall()
    for source in due:
        conn.execute("INSERT INTO harvest_jobs (source_id) VALUES (%s)", (source["id"],))
        conn.execute(
            "UPDATE harvest_sources SET next_run = now() + %s::interval WHERE id = %s",
            (FREQUENCIES[source["frequency"]], source["id"]),
        )
    conn.commit()
    return len(due)


def abort_stale(conn, timeout_minutes: int) -> int:
    """Abort running jobs that have done nothing for longer than the timeout, such as one whose
    worker died. The clock runs from the job's last finished record."""
    stale = conn.execute(
        "SELECT j.id FROM harvest_jobs j WHERE j.status = 'running' AND greatest(j.gather_started, "
        "(SELECT max(o.finished_at) FROM harvest_objects o WHERE o.job_id = j.id)) "
        "< now() - make_interval(mins => %s)",
        (timeout_minutes,),
    ).fetchall()
    for job in stale:
        abort(conn, job["id"], f"Stopped: no progress for more than {timeout_minutes} minutes.")
    return len(stale)


def abort(conn, job_id, reason: str) -> bool:
    row = conn.execute(
        "UPDATE harvest_jobs SET status = 'aborted', finished = now() "
        "WHERE id = %s AND status IN ('new', 'running') RETURNING id",
        (job_id,),
    ).fetchone()
    if row:
        _error(conn, job_id, None, "job", HarvestError(reason))
    conn.commit()
    return row is not None


def stats(conn, job_id) -> dict:
    counts = {outcome: 0 for outcome in store.OUTCOMES}
    counts["waiting"] = 0
    for row in conn.execute(
        "SELECT coalesce(outcome, 'waiting') AS outcome, count(*) AS n FROM harvest_objects "
        "WHERE job_id = %s GROUP BY 1",
        (job_id,),
    ):
        counts[row["outcome"]] = row["n"]
    return counts
