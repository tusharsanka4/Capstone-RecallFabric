"""Use application settings without placing credentials in alembic.ini."""

from alembic import context
from pgvector.sqlalchemy import Vector

from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.db.models import Base


def render_item(type_, obj, autogen_context):
    if type_ == "type" and isinstance(obj, Vector):
        return f"Vector({obj.dim!r})"
    return False


def run(connection):
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        render_item=render_item,
        version_table_schema=context.config.attributes.get("schema"),
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(dialect_name="postgresql", target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    run(context.config.attributes["connection"])
else:
    x_args = context.get_x_argument(as_dictionary=True)
    override_url = x_args.get("url")
    settings = Settings(database_url=override_url) if override_url else Settings()
    engine = create_database_engine(settings)
    try:
        with engine.connect() as connection:
            run(connection)
    finally:
        engine.dispose()
