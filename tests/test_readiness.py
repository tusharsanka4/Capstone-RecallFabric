from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from recallfabric.api import health
from recallfabric.core.config import Settings
from recallfabric.main import create_app


def test_ready_with_vector(monkeypatch):
    monkeypatch.setattr(health, "database_is_ready", lambda engine: True)
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/ready").json() == {"status": "ok"}


def test_missing_vector_is_not_ready(monkeypatch):
    monkeypatch.setattr(health, "database_is_ready", lambda engine: False)
    with TestClient(create_app(Settings(_env_file=None))) as client:
        assert client.get("/ready").status_code == 503
        assert client.get("/health").status_code == 200


def test_database_failure_is_sanitized(monkeypatch):
    def unavailable(engine):
        raise OperationalError("secret connection details", {}, Exception("password"))

    monkeypatch.setattr(health, "database_is_ready", unavailable)
    with TestClient(create_app(Settings(_env_file=None))) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
        assert client.get("/health").status_code == 200
