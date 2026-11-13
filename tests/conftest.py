import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine, get_database_engine
from recallfabric.embeddings.service import EmbeddingResult, get_embedding_provider
from recallfabric.main import create_app


class DeterministicEmbedder:
    model_id = "test-retrieval-model"
    dimensions = 3

    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def embed(self, text, kind="passage"):
        vec = self.mapping.get(text, [0.0, 0.0, 1.0])
        return EmbeddingResult(model=self.model_id, dimensions=3, vector=vec)


@pytest.fixture
def retrieval_api():
    if os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1":
        pytest.skip("Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL retrieval tests")
    admin = create_database_engine(Settings())
    engine = create_database_engine(Settings())
    schema = "test_retrieval_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    @event.listens_for(engine, "connect")
    def set_schema(dbapi_connection, record):
        dbapi_connection.autocommit = True
        with dbapi_connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}", public')
        dbapi_connection.autocommit = False

    try:
        with engine.begin() as connection:
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes.update(connection=connection, schema=schema)
            command.upgrade(config, "head")
        app = create_app(Settings(_env_file=None, retrieval_min_similarity=0.4))
        app.dependency_overrides[get_database_engine] = lambda: engine
        embedder = DeterministicEmbedder(
            mapping={
                "target memory": [1.0, 0.0, 0.0],
                "semantically close": [0.9, 0.1, 0.0],
                "semantically distant": [0.1, 0.9, 0.0],
                "orthogonal": [0.0, 1.0, 0.0],
                "opposite": [-1.0, 0.0, 0.0],
                "query close": [1.0, 0.0, 0.0],
                "query unrelated": [0.0, 1.0, 0.0],
            }
        )
        app.dependency_overrides[get_embedding_provider] = lambda: embedder
        with TestClient(app) as client:
            yield client, engine, embedder
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
