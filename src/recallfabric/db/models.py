"""Memory revisions. A stable ID and increasing version identify each revision."""

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        UniqueConstraint("user_id", "id", "version", name="uq_memory_owner_revision"),
        ForeignKeyConstraint(
            ["user_id", "id", "previous_version"],
            ["memories.user_id", "memories.id", "memories.version"],
            name="fk_memory_previous_revision",
        ),
        CheckConstraint("btrim(user_id) <> ''", name="ck_memory_user"),
        CheckConstraint("btrim(content) <> ''", name="ck_memory_content"),
        CheckConstraint("btrim(source) <> ''", name="ck_memory_source"),
        CheckConstraint(
            "type IN ('preference', 'goal', 'skill', 'profile', 'fact', 'other')",
            name="ck_memory_type",
        ),
        CheckConstraint("status IN ('active', 'disabled', 'superseded')", name="ck_memory_status"),
        CheckConstraint("importance BETWEEN 0 AND 1", name="ck_memory_importance"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_memory_confidence"),
        CheckConstraint(
            "(version = 1 AND previous_version IS NULL) OR "
            "(version > 1 AND previous_version IS NOT NULL AND previous_version = version - 1)",
            name="ck_memory_version",
        ),
        CheckConstraint("access_count >= 0", name="ck_memory_access_count"),
        CheckConstraint("updated_at >= created_at", name="ck_memory_timestamps"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_memory_metadata"),
        CheckConstraint(
            "(embedding IS NULL AND embedding_model IS NULL AND embedding_dimensions IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model IS NOT NULL "
            "AND btrim(embedding_model) <> '' AND embedding_dimensions IS NOT NULL "
            "AND embedding_dimensions BETWEEN 1 AND 16000 "
            "AND vector_dims(embedding) = embedding_dimensions)",
            name="ck_memory_embedding",
        ),
        Index(
            "uq_memory_current",
            "id",
            unique=True,
            postgresql_where=text("status IN ('active', 'disabled')"),
        ),
        Index("ix_memory_user_status_type", "user_id", "status", "type"),
        Index("ix_memory_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    user_id: Mapped[str] = mapped_column(String(255))
    previous_version: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(32))
    importance: Mapped[float] = mapped_column(Float, default=0.5, server_default="0.5")
    confidence: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    source: Mapped[str] = mapped_column(String(512))
    creation_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    attributes: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
