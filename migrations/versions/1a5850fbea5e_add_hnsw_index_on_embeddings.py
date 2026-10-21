import sqlalchemy as sa
from alembic import op

revision = "1a5850fbea5e"
down_revision = "0631ddfc0397"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_memories_embedding_hnsw_384",
        "memories",
        [sa.literal_column("(embedding::vector(384)) vector_cosine_ops")],
        unique=False,
        postgresql_using="hnsw",
        postgresql_where=sa.text("embedding_dimensions = 384"),
    )


def downgrade():
    op.drop_index(
        "ix_memories_embedding_hnsw_384",
        table_name="memories",
        postgresql_using="hnsw",
        postgresql_where=sa.text("embedding_dimensions = 384"),
    )
