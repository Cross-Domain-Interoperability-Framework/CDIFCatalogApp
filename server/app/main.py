import os

import psycopg
from fastapi import FastAPI

app = FastAPI(title="CDIF Catalog")


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
