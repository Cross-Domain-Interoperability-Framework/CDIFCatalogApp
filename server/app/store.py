"""The records table and the harvest tables, and the few queries more than one module needs.

The layout of `records` is the one in docs/design.md ("How records are stored"). The harvest
tables follow the source / job / object model of ckanext-harvest: a source is registered once, a
job is one run of it, and an object is one source record seen in one run.
"""
import hashlib
import os

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from app import access

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    orcid          text NOT NULL UNIQUE,
    name           text,
    groups         text[] NOT NULL DEFAULT '{}',
    organisations  text[] NOT NULL DEFAULT '{}',
    created_at     timestamptz NOT NULL DEFAULT now(),
    last_login     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  text PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS harvest_sources (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title         text NOT NULL,
    url           text NOT NULL,
    type          text NOT NULL,
    config        jsonb NOT NULL DEFAULT '{}',
    organisation  text,
    frequency     text NOT NULL DEFAULT 'MANUAL',
    next_run      timestamptz,
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS uploads (
    source_id    uuid NOT NULL REFERENCES harvest_sources(id) ON DELETE CASCADE,
    name         text NOT NULL,
    content      text NOT NULL,
    uploaded_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, name)
);

CREATE TABLE IF NOT EXISTS records (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile            text NOT NULL,
    source_id          uuid REFERENCES harvest_sources(id) ON DELETE CASCADE,
    source_identifier  text,
    received           text,
    received_format    text,
    source_cdif        jsonb,
    overlay            jsonb NOT NULL DEFAULT '{}',
    published          jsonb,
    validation         jsonb,
    content_hash       text,
    source_modified    text,
    status             text NOT NULL,
    organisation       text,
    creator            text,
    labels             text[] NOT NULL DEFAULT '{}',
    first_harvested    timestamptz,
    last_harvested     timestamptz,
    changed_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, source_identifier)
);
CREATE INDEX IF NOT EXISTS records_labels ON records USING gin (labels);
CREATE INDEX IF NOT EXISTS records_changed ON records (changed_at);

-- What search looks through, kept by the database itself from the published record, so no code
-- that saves a record can forget it. Title weighs most (A), then keywords and creators' names
-- (B), variable names (C), and the description (D). To change what is searched, drop the column
-- and let this add it again; it is rebuilt from the records.
ALTER TABLE records ADD COLUMN IF NOT EXISTS search tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(published->>'schema:name', '')), 'A')
    || setweight(jsonb_to_tsvector('english', jsonb_path_query_array(coalesce(published, '{}'),
        '$."schema:keywords"[*] ? (@.type() == "string")'), '["string"]'), 'B')
    || setweight(jsonb_to_tsvector('english', jsonb_path_query_array(coalesce(published, '{}'),
        '$."schema:keywords".**."schema:name"'), '["string"]'), 'B')
    || setweight(jsonb_to_tsvector('english', jsonb_path_query_array(coalesce(published, '{}'),
        '$."schema:creator".**."schema:name"'), '["string"]'), 'B')
    || setweight(jsonb_to_tsvector('english', jsonb_path_query_array(coalesce(published, '{}'),
        '$."schema:variableMeasured".**."schema:name"'), '["string"]'), 'C')
    || setweight(to_tsvector('english', coalesce(published->>'schema:description', '')), 'D')
) STORED;
CREATE INDEX IF NOT EXISTS records_search ON records USING gin (search);

CREATE TABLE IF NOT EXISTS harvest_jobs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id        uuid NOT NULL REFERENCES harvest_sources(id) ON DELETE CASCADE,
    status           text NOT NULL DEFAULT 'new',
    created_at       timestamptz NOT NULL DEFAULT now(),
    gather_started   timestamptz,
    gather_finished  timestamptz,
    finished         timestamptz
);

ALTER TABLE harvest_jobs ADD COLUMN IF NOT EXISTS retry_of uuid REFERENCES harvest_jobs(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS harvest_objects (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id       uuid NOT NULL REFERENCES harvest_jobs(id) ON DELETE CASCADE,
    source_id    uuid NOT NULL REFERENCES harvest_sources(id) ON DELETE CASCADE,
    identifier   text NOT NULL,
    url          text,
    modified     text,
    state        text NOT NULL DEFAULT 'waiting',
    outcome      text,
    current      boolean NOT NULL DEFAULT false,
    record_id    uuid REFERENCES records(id) ON DELETE SET NULL,
    gathered_at  timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);
CREATE INDEX IF NOT EXISTS harvest_objects_job ON harvest_objects (job_id);

CREATE TABLE IF NOT EXISTS harvest_errors (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      uuid NOT NULL REFERENCES harvest_jobs(id) ON DELETE CASCADE,
    object_id   uuid REFERENCES harvest_objects(id) ON DELETE CASCADE,
    stage       text NOT NULL,
    message     text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
"""

# What a harvested object can end as. A job's summary is a count of these.
OUTCOMES = ("added", "updated", "not modified", "deleted", "errored")


def connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(503, "The database is not configured.")
    try:
        return psycopg.connect(url, connect_timeout=3, row_factory=dict_row)
    except psycopg.OperationalError:
        raise HTTPException(503, "The database is not reachable.")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_overlay(source: dict, overlay: dict) -> dict:
    """The source record with a data manager's edits on top. An overlay replaces whole top-level
    properties; a property overlaid with null is removed."""
    out = {**source, **overlay}
    return {k: v for k, v in out.items() if v is not None}


def overlay_conflicts(old_source: dict | None, new_source: dict, overlay: dict) -> list[str]:
    """Overridden properties whose value has now changed at the source as well."""
    if not old_source:
        return []
    return sorted(k for k in overlay if old_source.get(k) != new_source.get(k))


def set_status(conn, record_id, status: str) -> None:
    """Change a record's status and recompute its labels, which depend on it."""
    row = conn.execute("SELECT organisation, creator FROM records WHERE id = %s", (record_id,)).fetchone()
    conn.execute(
        "UPDATE records SET status = %s, labels = %s, changed_at = now() WHERE id = %s",
        (status, access.record_labels(status, row["organisation"], row["creator"]), record_id),
    )


# The words a person typed, read the way a web search reads them: all of them wanted, "quoted
# words" together, -word left out, or for either.
_WORDS = "websearch_to_tsquery('english', %s)"
# How a list of records can be ordered. "relevance" needs words to rank by.
ORDERS = ("relevance", "modified", "title")

# The facets a search offers, each a key, and the SQL giving one record its value in that facet:
# where it came from (the harvest source), who published it, and the detail level it reaches.
_FACET_VALUE = {
    "source": "r.source_id::text",
    "publisher": "r.published->'schema:publisher'->>'schema:name'",
    "profile": "r.profile",
}
FACETS = tuple(_FACET_VALUE)
# The internal profile names, in the plain words the facet shows.
PROFILE_LABELS = {"cdifCore": "Core", "CoreDiscovery": "Discovery"}


def _search_where(user: access.User, containing, modified_since, filters, skip=None):
    """The WHERE every search query shares: published, visible, matching the words, and narrowed
    by each active facet filter (all but `skip`, so a facet's own counts are not narrowed by it)."""
    where = "r.status = 'published' AND r.labels && %s"
    params: list = [access.user_labels(user)]
    if containing:
        where += f" AND r.search @@ {_WORDS}"
        params.append(containing)
    if modified_since is not None:
        where += " AND r.changed_at >= %s"
        params.append(modified_since)
    for name, value in (filters or {}).items():
        if value and name != skip and name in _FACET_VALUE:
            where += f" AND {_FACET_VALUE[name]} = %s"
            params.append(value)
    return where, params


def visible_records(
    conn, user: access.User, modified_since=None, limit: int = 100, offset: int = 0,
    containing=None, order="modified", filters=None,
):
    """(total, rows) of published records the user may see.

    `containing` keeps the records whose title, keywords, creators, variable names or description
    hold those words, in any letter case and whatever their endings ("ages" finds "age").
    `filters` is a {facet: value} map from FACETS that narrows the set further. `order` is one of
    ORDERS: by relevance to the words (a match in the title counting most), most recently changed
    first, or by title."""
    where, params = _search_where(user, containing, modified_since, filters)
    by, ranked = "r.changed_at DESC, r.id", []
    if order == "relevance" and containing:
        by, ranked = f"ts_rank(r.search, {_WORDS}) DESC, r.changed_at DESC, r.id", [containing]
    elif order == "title":
        by = "lower(r.published->>'schema:name'), r.id"
    total = conn.execute(f"SELECT count(*) AS n FROM records r WHERE {where}", params).fetchone()["n"]
    rows = conn.execute(
        f"SELECT r.id, r.published, r.changed_at FROM records r WHERE {where} ORDER BY {by} LIMIT %s OFFSET %s",
        params + ranked + [limit, offset],
    ).fetchall()
    return total, rows


def facet_counts(conn, user: access.User, containing=None, modified_since=None, filters=None, per_facet: int = 12):
    """For each facet, the values present among the matching records, each with how many records
    carry it, most first. A facet's own filter does not narrow its own counts, so the other
    values in a chosen facet stay visible."""
    out = {}
    for name in FACETS:
        where, params = _search_where(user, containing, modified_since, filters, skip=name)
        value = _FACET_VALUE[name]
        join = "JOIN harvest_sources s ON s.id = r.source_id" if name == "source" else ""
        label = "s.title" if name == "source" else value
        rows = conn.execute(
            f"SELECT {value} AS value, {label} AS label, count(*) AS n FROM records r {join} "
            f"WHERE {where} AND ({value}) IS NOT NULL GROUP BY {value}, {label} ORDER BY n DESC, label LIMIT %s",
            params + [per_facet],
        ).fetchall()
        out[name] = [
            {
                "value": row["value"],
                "label": PROFILE_LABELS.get(row["label"], row["label"]) if name == "profile" else row["label"],
                "count": row["n"],
            }
            for row in rows
        ]
    return out


def visible_record(conn, user: access.User, record_id):
    return conn.execute(
        "SELECT id, published, changed_at, profile FROM records "
        "WHERE id = %s AND status = 'published' AND labels && %s",
        (record_id, access.user_labels(user)),
    ).fetchone()
