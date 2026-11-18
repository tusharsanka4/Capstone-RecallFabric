"""Bind opaque OAuth credentials to their protected resource; legacy grants must reconnect."""

import sqlalchemy as sa
from alembic import op

revision = "e1a2b3c4d501"
down_revision = "da7c42e6f901"
branch_labels = None
depends_on = None
TABLES = (
    "oauth_authorization_codes",
    "oauth_access_tokens",
    "oauth_refresh_tokens",
    "oauth_authorization_requests",
)


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column("resource", sa.String(2048), nullable=True))


def downgrade():
    for table in reversed(TABLES):
        op.drop_column(table, "resource")
