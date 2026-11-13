"""add oauth browser transactions and rotating refresh tokens

Revision ID: c9e71a2b8d30
Revises: 4d8c4a3e1f21
"""

import sqlalchemy as sa
from alembic import op

revision = "c9e71a2b8d30"
down_revision = "4d8c4a3e1f21"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_oauth_refresh_tokens_hash"),
    )
    op.create_index("ix_oauth_refresh_tokens_hash", "oauth_refresh_tokens", ["token_hash"])
    op.create_index("ix_oauth_refresh_tokens_family", "oauth_refresh_tokens", ["family_id"])
    op.create_table(
        "oauth_authorization_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("redirect_uri", sa.String(2048), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(512), nullable=False),
        sa.Column("state", sa.String(2048)),
        sa.Column("csrf_token", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_oauth_authorization_requests_expires", "oauth_authorization_requests", ["expires_at"]
    )
    op.create_table(
        "oauth_browser_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_oauth_browser_sessions_hash"),
    )
    op.create_index("ix_oauth_browser_sessions_hash", "oauth_browser_sessions", ["token_hash"])


def downgrade():
    op.drop_index("ix_oauth_browser_sessions_hash", table_name="oauth_browser_sessions")
    op.drop_table("oauth_browser_sessions")
    op.drop_index(
        "ix_oauth_authorization_requests_expires", table_name="oauth_authorization_requests"
    )
    op.drop_table("oauth_authorization_requests")
    op.drop_index("ix_oauth_refresh_tokens_family", table_name="oauth_refresh_tokens")
    op.drop_index("ix_oauth_refresh_tokens_hash", table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")
