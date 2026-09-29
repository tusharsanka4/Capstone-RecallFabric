"""initial_memory_schema"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0631ddfc0397"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("previous_version", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("importance", sa.Float(), server_default="0.5", nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1", nullable=False),
        sa.Column("source", sa.String(length=512), nullable=False),
        sa.Column("creation_reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "(embedding IS NULL AND embedding_model IS NULL AND embedding_dimensions IS NULL) OR "
            "(embedding IS NOT NULL AND embedding_model IS NOT NULL "
            "AND btrim(embedding_model) <> '' AND embedding_dimensions IS NOT NULL "
            "AND embedding_dimensions BETWEEN 1 AND 16000 "
            "AND vector_dims(embedding) = embedding_dimensions)",
            name="ck_memory_embedding",
        ),
        sa.CheckConstraint("btrim(content) <> ''", name="ck_memory_content"),
        sa.CheckConstraint("btrim(source) <> ''", name="ck_memory_source"),
        sa.CheckConstraint("btrim(user_id) <> ''", name="ck_memory_user"),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_memory_metadata"),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'superseded')", name="ck_memory_status"
        ),
        sa.CheckConstraint(
            "type IN ('preference', 'goal', 'skill', 'profile', 'fact', 'other')",
            name="ck_memory_type",
        ),
        sa.CheckConstraint(
            "(version = 1 AND previous_version IS NULL) OR "
            "(version > 1 AND previous_version IS NOT NULL AND previous_version = version - 1)",
            name="ck_memory_version",
        ),
        sa.CheckConstraint("access_count >= 0", name="ck_memory_access_count"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_memory_confidence"),
        sa.CheckConstraint("importance BETWEEN 0 AND 1", name="ck_memory_importance"),
        sa.CheckConstraint("updated_at >= created_at", name="ck_memory_timestamps"),
        sa.ForeignKeyConstraint(
            ["user_id", "id", "previous_version"],
            ["memories.user_id", "memories.id", "memories.version"],
            name="fk_memory_previous_revision",
        ),
        sa.PrimaryKeyConstraint("id", "version"),
        sa.UniqueConstraint("user_id", "id", "version", name="uq_memory_owner_revision"),
    )
    op.create_index("ix_memory_user_created", "memories", ["user_id", "created_at"], unique=False)
    op.create_index(
        "ix_memory_user_status_type", "memories", ["user_id", "status", "type"], unique=False
    )
    op.create_index(
        "uq_memory_current",
        "memories",
        ["id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'disabled')"),
    )
    op.execute("""
        CREATE FUNCTION set_memory_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER memory_updated_at BEFORE UPDATE ON memories
        FOR EACH ROW EXECUTE FUNCTION set_memory_updated_at()
    """)


def downgrade():
    op.drop_index(
        "uq_memory_current",
        table_name="memories",
        postgresql_where=sa.text("status IN ('active', 'disabled')"),
    )
    op.drop_index("ix_memory_user_status_type", table_name="memories")
    op.drop_index("ix_memory_user_created", table_name="memories")
    op.drop_table("memories")
    op.execute("DROP FUNCTION set_memory_updated_at()")
