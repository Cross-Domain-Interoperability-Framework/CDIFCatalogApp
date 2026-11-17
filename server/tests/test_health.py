from fastapi.testclient import TestClient

from app.main import app


def test_health_without_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    body = TestClient(app).get("/api/health").json()
    assert body == {"status": "ok", "database": "not configured"}
