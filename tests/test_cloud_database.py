import logging
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError

from recallfabric.api import health
from recallfabric.core.config import Settings, normalize_database_url
from recallfabric.db.connection import create_database_engine
from recallfabric.main import create_app
from scripts.migrate_local_to_cloud import get_table_def, migrate_database


class TestDatabaseURLAndConfig:
    def test_normalize_database_url_schemes(self):
        cases = [
            ("postgres://user:pw@host:5432/db", "postgresql+psycopg://user:pw@host:5432/db"),
            ("postgresql://user:pw@host:5432/db", "postgresql+psycopg://user:pw@host:5432/db"),
            (
                "postgresql+psycopg2://user:pw@host:5432/db",
                "postgresql+psycopg://user:pw@host:5432/db",
            ),
            (
                "postgresql+psycopg://user:pw@host:5432/db",
                "postgresql+psycopg://user:pw@host:5432/db",
            ),
            (
                "postgresql://user:pw@host:5432/db?sslmode=require",
                "postgresql+psycopg://user:pw@host:5432/db?sslmode=require",
            ),
        ]
        for raw, expected in cases:
            assert normalize_database_url(raw) == expected

    def test_settings_url_precedence(self):
        settings_override = Settings(
            database_url=SecretStr("postgresql://cloud_user:secret@cloud_host:5432/cloud_db"),
            db_host="localhost",
            db_port=5432,
            db_name="local_db",
            _env_file=None,
        )
        assert (
            settings_override.get_database_url()
            == "postgresql+psycopg://cloud_user:secret@cloud_host:5432/cloud_db"
        )

    def test_settings_url_fallback(self):
        settings_default = Settings(
            database_url=None,
            db_host="127.0.0.1",
            db_port=5432,
            db_name="testdb",
            db_user="testuser",
            db_password=SecretStr("testpass"),
            _env_file=None,
        )
        url = settings_default.get_database_url()
        assert "postgresql+psycopg://testuser:testpass@127.0.0.1:5432/testdb" == url

    def test_engine_pool_and_ssl_settings(self):
        settings = Settings(
            database_url=SecretStr("postgresql://u:p@localhost:5432/d"),
            db_pool_size=7,
            db_max_overflow=14,
            db_pool_recycle=300,
            db_pool_pre_ping=True,
            db_sslmode="require",
            _env_file=None,
        )
        engine = create_database_engine(settings)
        try:
            assert engine.pool.size() == 7
            assert engine.pool._max_overflow == 14
            assert engine.pool._recycle == 300
            assert engine.pool._pre_ping is True
        finally:
            engine.dispose()

    def test_password_never_appears_in_logs(self, caplog):
        caplog.set_level(logging.DEBUG)
        secret_pass = "super_classified_secret_987654"
        settings = Settings(
            database_url=SecretStr(f"postgresql://user:{secret_pass}@localhost:5432/dbname"),
            _env_file=None,
        )
        engine = create_database_engine(settings)
        engine.dispose()

        for record in caplog.records:
            assert secret_pass not in record.getMessage()
            assert secret_pass not in str(record.args)

    def test_database_error_does_not_leak_password(self, monkeypatch):
        secret_pass = "my_hidden_db_password"

        def raise_op_error(engine):
            raise OperationalError(
                f"connection to postgresql://user:{secret_pass}@host failed",
                {},
                Exception(secret_pass),
            )

        monkeypatch.setattr(health, "database_is_ready", raise_op_error)
        with TestClient(create_app(Settings(_env_file=None))) as client:
            resp = client.get("/ready")
            assert resp.status_code == 503
            assert secret_pass not in resp.text
            assert resp.json() == {"detail": "Database unavailable"}


class TestReadinessEndpoint:
    def test_ready_reports_all_components(self, monkeypatch):
        monkeypatch.setattr(health, "database_is_ready", lambda engine: True)
        monkeypatch.setattr(health, "check_migration_matches_head", lambda engine: True)
        monkeypatch.setattr(health, "check_ssl_in_use", lambda engine: False)

        with TestClient(create_app(Settings(_env_file=None))) as client:
            resp = client.get("/ready?detailed=true")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["database_reachable"] is True
            assert data["vector_extension_enabled"] is True
            assert data["migration_revision_matches_head"] is True
            assert data["ssl_in_use"] is False
            assert resp.headers["x-database-reachable"] == "true"
            assert resp.headers["x-vector-extension-enabled"] == "true"
            assert resp.headers["x-migration-revision-matches-head"] == "true"
            assert resp.headers["x-ssl-in-use"] == "false"

    def test_ready_migration_mismatch_returns_503(self, monkeypatch):
        monkeypatch.setattr(health, "database_is_ready", lambda engine: True)
        monkeypatch.setattr(health, "check_migration_matches_head", lambda engine: False)

        with TestClient(create_app(Settings(_env_file=None))) as client:
            resp = client.get("/ready")
            assert resp.status_code == 503
            assert resp.json() == {"detail": "Migration revision mismatch"}

    def test_ready_ssl_required_but_missing_returns_503(self, monkeypatch):
        monkeypatch.setattr(health, "database_is_ready", lambda engine: True)
        monkeypatch.setattr(health, "check_migration_matches_head", lambda engine: True)
        monkeypatch.setattr(health, "check_ssl_in_use", lambda engine: False)

        settings = Settings(db_sslmode="require", _env_file=None)
        with TestClient(create_app(settings)) as client:
            resp = client.get("/ready")
            assert resp.status_code == 503
            assert resp.json() == {"detail": "SSL connection required but not in use"}


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
    reason="Set RECALLFABRIC_RUN_DB_TESTS=1 to run against the configured database",
)
class TestMigrationScriptSchemas:
    def test_migration_between_schemas(self):
        settings = Settings()
        db_url = settings.get_database_url()
        engine = create_engine(db_url)

        src_schema = f"test_src_{uuid.uuid4().hex[:8]}"
        dst_schema = f"test_dst_{uuid.uuid4().hex[:8]}"

        try:
            with engine.begin() as conn:
                conn.execute(text(f"CREATE SCHEMA {src_schema}"))
                conn.execute(text(f"CREATE SCHEMA {dst_schema}"))

            # Create tables in both schemas
            src_mem_tbl = get_table_def("memories", schema=src_schema)
            dst_mem_tbl = get_table_def("memories", schema=dst_schema)
            src_ev_tbl = get_table_def("memory_events", schema=src_schema)
            dst_ev_tbl = get_table_def("memory_events", schema=dst_schema)
            src_key_tbl = get_table_def("api_keys", schema=src_schema)
            dst_key_tbl = get_table_def("api_keys", schema=dst_schema)
            src_log_tbl = get_table_def("audit_logs", schema=src_schema)
            dst_log_tbl = get_table_def("audit_logs", schema=dst_schema)

            with engine.begin() as conn:
                src_mem_tbl.create(conn)
                src_ev_tbl.create(conn)
                src_key_tbl.create(conn)
                src_log_tbl.create(conn)

                dst_mem_tbl.create(conn)
                dst_ev_tbl.create(conn)
                dst_key_tbl.create(conn)
                dst_log_tbl.create(conn)

            # Insert sample rows into source schema
            mem_id = uuid.uuid4()
            fake_embedding = [0.1 * i for i in range(384)]

            with engine.begin() as conn:
                # Memory v1
                conn.execute(
                    src_mem_tbl.insert(),
                    [
                        {
                            "id": mem_id,
                            "version": 1,
                            "user_id": "user_123",
                            "previous_version": None,
                            "content": "User prefers dark mode",
                            "type": "preference",
                            "importance": 0.8,
                            "confidence": 0.9,
                            "source": "cli_test",
                            "creation_reason": "testing",
                            "status": "superseded",
                            "metadata": {"test": True},
                            "embedding": fake_embedding,
                            "embedding_model": "BAAI/bge-small-en-v1.5",
                            "embedding_dimensions": 384,
                            "access_count": 1,
                        },
                        {
                            "id": mem_id,
                            "version": 2,
                            "user_id": "user_123",
                            "previous_version": 1,
                            "content": "User prefers high contrast dark mode",
                            "type": "preference",
                            "importance": 0.85,
                            "confidence": 0.95,
                            "source": "cli_test",
                            "creation_reason": "updating",
                            "status": "active",
                            "metadata": {"test": True, "v": 2},
                            "embedding": fake_embedding,
                            "embedding_model": "BAAI/bge-small-en-v1.5",
                            "embedding_dimensions": 384,
                            "access_count": 0,
                        },
                    ],
                )
                conn.execute(
                    src_ev_tbl.insert(),
                    [
                        {
                            "id": uuid.uuid4(),
                            "memory_id": mem_id,
                            "memory_version": 1,
                            "user_id": "user_123",
                            "event_type": "created",
                            "reason": "initial",
                            "source": "test",
                            "actor": "system",
                            "detail": {},
                        }
                    ],
                )
                conn.execute(
                    src_key_tbl.insert(),
                    [
                        {
                            "id": uuid.uuid4(),
                            "user_id": "user_123",
                            "name": "default-key",
                            "key_hash": uuid.uuid4().hex,
                        }
                    ],
                )
                conn.execute(
                    src_log_tbl.insert(),
                    [
                        {
                            "id": uuid.uuid4(),
                            "user_id": "user_123",
                            "event_type": "login",
                            "ip_address": "127.0.0.1",
                            "detail": {},
                        }
                    ],
                )

            # 1. Test Dry Run
            dry_report = migrate_database(
                source_url=db_url,
                target_url=db_url,
                dry_run=True,
                source_schema=src_schema,
                target_schema=dst_schema,
            )
            assert dry_report.success is True
            assert dry_report.source_counts["memories"] == 2
            assert dry_report.source_counts["memory_events"] == 1
            # Verify target is still 0
            with engine.connect() as conn:
                assert conn.execute(select(func.count()).select_from(dst_mem_tbl)).scalar() == 0

            # 2. Execute Real Migration
            live_report = migrate_database(
                source_url=db_url,
                target_url=db_url,
                dry_run=False,
                force=False,
                source_schema=src_schema,
                target_schema=dst_schema,
            )
            assert live_report.success is True
            assert live_report.target_counts["memories"] == 2
            assert live_report.target_counts["memory_events"] == 1
            assert live_report.target_counts["api_keys"] == 1
            assert live_report.target_counts["audit_logs"] == 1
            assert live_report.verified_vectors > 0

            # 3. Test Safety: re-running without force refuses
            refused_report = migrate_database(
                source_url=db_url,
                target_url=db_url,
                dry_run=False,
                force=False,
                source_schema=src_schema,
                target_schema=dst_schema,
            )
            assert refused_report.success is False
            assert "Refusing to migrate" in (refused_report.error_message or "")

            # 4. Test --force flag allowed
            force_report = migrate_database(
                source_url=db_url,
                target_url=db_url,
                dry_run=True,
                force=True,
                source_schema=src_schema,
                target_schema=dst_schema,
            )
            assert force_report.success is True

        finally:
            with engine.begin() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {src_schema} CASCADE"))
                conn.execute(text(f"DROP SCHEMA IF EXISTS {dst_schema} CASCADE"))
            engine.dispose()
