"""The harvest worker: `python -m app.harvest.worker`.

A loop that starts scheduled jobs, aborts stuck ones, and runs whatever job is waiting. The
queue is the `harvest_jobs` table itself, so there is no message broker to run.
"""
import logging
import os
import time

import httpx
import psycopg
from psycopg.rows import dict_row

from app import store
from app.harvest import run
from app.harvest.run import USER_AGENT

log = logging.getLogger("harvest")


def http_client() -> httpx.Client:
    return httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT})


def tick(conn, http, timeout_minutes: int) -> bool:
    """One pass. Returns True if a job was run, so the loop can go straight to the next."""
    run.schedule_due(conn)
    run.abort_stale(conn, timeout_minutes)
    job = run.claim(conn)
    if job is None:
        return False
    log.info("running job %s", job["id"])
    run.run_job(conn, job, http)
    log.info("job %s: %s", job["id"], run.stats(conn, job["id"]))
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    timeout_minutes = int(os.environ.get("HARVEST_TIMEOUT_MINUTES", "1440"))
    poll = float(os.environ.get("HARVEST_POLL_SECONDS", "5"))
    with http_client() as http:
        while True:
            try:
                with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
                    conn.execute(store.SCHEMA)
                    conn.commit()
                    while True:
                        if not tick(conn, http, timeout_minutes):
                            time.sleep(poll)
            except psycopg.OperationalError as e:  # the database went away; wait and reconnect
                log.warning("database unavailable: %s", e)
                time.sleep(poll)


if __name__ == "__main__":
    main()
