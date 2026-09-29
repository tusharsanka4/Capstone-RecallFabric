"""Opt-in real-database checks, using only a transaction-local temporary table."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine, database_is_ready
from recallfabric.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
        reason="Set RECALLFABRIC_RUN_DB_TESTS=1 to run against the configured database",
    ),
]


def test_vector_storage_and_nearest_neighbor():
    engine = create_database_engine(Settings())
    try:
        assert database_is_ready(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TEMP TABLE vector_smoke "
                    "(id integer, embedding vector(3)) ON COMMIT DROP"
                )
            )
            connection.execute(
                text("INSERT INTO vector_smoke VALUES (1, '[1,0,0]'), (2, '[0,1,0]')")
            )
            result = connection.execute(
                text(
                    "SELECT id, embedding <-> '[1,0,0]'::vector AS distance "
                    "FROM vector_smoke ORDER BY distance LIMIT 1"
                )
            ).one()
            assert result.id == 1
            assert result.distance == pytest.approx(0)
    finally:
        engine.dispose()


def test_live_database_readiness():
    with TestClient(create_app()) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
