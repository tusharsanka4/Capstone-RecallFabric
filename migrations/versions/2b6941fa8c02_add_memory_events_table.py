import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "2b6941fa8c02"
down_revision = "1a5850fbea5e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("memory_version", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=512), nullable=True),
        sa.Column("actor", sa.String(length=255), server_default="system", nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('created', 'consolidated', 'superseded', 'disabled', "
            "'enabled', 'deleted', 'accessed')",
            name="ck_memory_events_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_events_user_memory_created",
        "memory_events",
        ["user_id", "memory_id", "created_at"],
    )
    op.create_index(
        "ix_memory_events_user_created",
        "memory_events",
        ["user_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_memory_events_user_created", table_name="memory_events")
    op.drop_index("ix_memory_events_user_memory_created", table_name="memory_events")
    op.drop_table("memory_events")
