"""Exercise the real migration in an isolated schema, rolled back after each test."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.db.models import Memory
from recallfabric.schemas.memory import MemoryRead

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RECALLFABRIC_RUN_DB_TESTS") != "1",
        reason="Set RECALLFABRIC_RUN_DB_TESTS=1 for PostgreSQL tests",
    ),
]


@pytest.fixture
def migrated_database():
    engine = create_database_engine(Settings())
    with engine.connect() as connection:
        transaction = connection.begin()
        # Generated identifier is hexadecimal only, never user input.
        schema = "test_memory_" + uuid4().hex
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = connection
        config.attributes["schema"] = schema
        try:
            command.upgrade(config, "head")
            yield connection, config
        finally:
            transaction.rollback()
    engine.dispose()


def memory_values(**changes):
    return dict(
        id=uuid4(),
        version=1,
        user_id="user_123",
        content="Learning Spring Boot",
        type="skill",
        source="conversation_102",
        **changes,
    )


def test_round_trip_and_history(migrated_database):
    connection, _ = migrated_database
    with Session(connection, join_transaction_mode="create_savepoint") as session:
        memory = Memory(**memory_values())
        memory.attributes = {"topic": "backend"}
        session.add(memory)
        session.flush()
        result = MemoryRead.model_validate(memory)
        assert result.metadata == {"topic": "backend"}
        assert result.created_at.tzinfo is not None
        assert result.version == 1
        assert memory.embedding is None

        memory.status = "superseded"
        session.flush()
        second = Memory(
            id=memory.id,
            version=2,
            previous_version=1,
            user_id=memory.user_id,
            content="Now learning Django",
            type="skill",
            source="conversation_103",
        )
        session.add(second)
        session.flush()
        session.refresh(memory)
        assert memory.updated_at >= memory.created_at
        revisions = session.scalars(select(Memory).order_by(Memory.version)).all()
        assert [row.content for row in revisions] == ["Learning Spring Boot", "Now learning Django"]
        assert [row.status for row in revisions] == ["superseded", "active"]


@pytest.mark.parametrize(
    "changes",
    [
        {"importance": -0.1},
        {"confidence": 1.1},
        {"confidence": float("nan")},
        {"content": " "},
        {"status": "unknown"},
        {"type": "unknown"},
        {"access_count": -1},
        {"attributes": []},
        {"version": 0},
        {"version": 2, "previous_version": None},
        {"embedding": [1, 0, 0]},
        {"embedding": [1, 0, 0], "embedding_model": "test", "embedding_dimensions": 2},
    ],
)
def test_database_rejects_invalid_records(migrated_database, changes):
    connection, _ = migrated_database
    values = memory_values()
    values.update(changes)
    with Session(connection, join_transaction_mode="create_savepoint") as session:
        session.add(Memory(**values))
        with pytest.raises(IntegrityError):
            session.flush()


def test_revision_ownership_and_single_current(migrated_database):
    connection, _ = migrated_database
    memory_id = uuid4()
    with Session(connection, join_transaction_mode="create_savepoint") as session:
        first = Memory(**memory_values())
        first.id = memory_id
        session.add(first)
        session.commit()

    # A second current revision is forbidden even for the correct owner.
    for owner in ["user_123", "another_user"]:
        with Session(connection, join_transaction_mode="create_savepoint") as session:
            session.add(
                Memory(
                    id=memory_id,
                    version=2,
                    previous_version=1,
                    user_id=owner,
                    content="Changed",
                    type="fact",
                    source="conversation_104",
                    status="active" if owner == "user_123" else "superseded",
                )
            )
            with pytest.raises(IntegrityError):
                session.flush()


def test_embedding_search(migrated_database):
    connection, _ = migrated_database
    with Session(connection, join_transaction_mode="create_savepoint") as session:
        for content, vector in [("near", [1, 0, 0]), ("far", [0, 1, 0])]:
            values = memory_values()
            values.update(
                content=content,
                embedding=vector,
                embedding_model="test-model",
                embedding_dimensions=3,
            )
            session.add(Memory(**values))
        session.flush()
        nearest = session.scalar(
            select(Memory)
            .where(Memory.user_id == "user_123")
            .order_by(Memory.embedding.l2_distance([1, 0, 0]))
            .limit(1)
        )
        assert nearest.content == "near"
        assert list(nearest.embedding) == [1, 0, 0]


def test_migration_downgrade_and_reupgrade(migrated_database):
    connection, config = migrated_database
    command.downgrade(config, "base")
    assert (
        connection.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = 'memories'"
            )
        ).scalar_one()
        == 0
    )
    command.upgrade(config, "head")
    assert connection.execute(text("SELECT count(*) FROM memories")).scalar_one() == 0
