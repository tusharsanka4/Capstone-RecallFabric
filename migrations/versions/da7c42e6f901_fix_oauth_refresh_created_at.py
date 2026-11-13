"""make oauth refresh creation timestamp non-null

Revision ID: da7c42e6f901
Revises: c9e71a2b8d30
"""

import sqlalchemy as sa
from alembic import op

revision = "da7c42e6f901"
down_revision = "c9e71a2b8d30"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "oauth_refresh_tokens",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        existing_server_default=sa.text("now()"),
    )


def downgrade():
    op.alter_column(
        "oauth_refresh_tokens",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        existing_server_default=sa.text("now()"),
    )
