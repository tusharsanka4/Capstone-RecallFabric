"""Smoke checks for the application and environment configuration."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from recallfabric.core.config import Settings
from recallfabric.main import create_app


def test_health_and_openapi():
    settings = Settings(_env_file=None, environment="test")
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        schema = client.get("/openapi.json").json()
        assert schema["info"]["title"] == "RecallFabric"
        assert "/health" in schema["paths"]


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("RECALLFABRIC_APP_NAME", "RecallFabric Test")
    monkeypatch.setenv("RECALLFABRIC_ENVIRONMENT", "test")
    settings = Settings(_env_file=None)
    assert settings.app_name == "RecallFabric Test"
    assert settings.environment == "test"


def test_invalid_environment_is_rejected(monkeypatch):
    monkeypatch.setenv("RECALLFABRIC_ENVIRONMENT", "invalid")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
