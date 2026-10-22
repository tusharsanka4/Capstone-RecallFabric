#!/usr/bin/env python3
"""Migrate data from local Docker database to a managed cloud PostgreSQL instance.

Copies all tables (memories, memory_events, api_keys, audit_logs) in batches,
preserving UUIDs, revision versions, timestamps, JSON metadata, and vector embeddings.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from dataclasses import dataclass, field

from sqlalchemy import MetaData, Table, create_engine, func, make_url, select
from sqlalchemy.engine import Engine

from recallfabric.core.config import Settings, normalize_database_url
from recallfabric.db.models import Base

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_local_to_cloud")

TABLE_ORDER = ["memories", "memory_events", "api_keys", "audit_logs"]


@dataclass
class MigrationReport:
    dry_run: bool
    source_counts: dict[str, int] = field(default_factory=dict)
    target_counts: dict[str, int] = field(default_factory=dict)
    verified_vectors: int = 0
    success: bool = True
    error_message: str | None = None


def get_table_def(table_name: str, schema: str | None = None) -> Table:
    """Get SQLAlchemy Table definition bound to the optional schema."""
    base_table = Base.metadata.tables.get(table_name)
    if base_table is None:
        raise ValueError(f"Table '{table_name}' not defined in models.")
    if schema:
        meta = MetaData()
        return base_table.to_metadata(meta, schema=schema)
    return base_table


def get_row_count(engine: Engine, table: Table) -> int:
    """Get current row count for a given table."""
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def verify_vectors(
    source_engine: Engine,
    target_engine: Engine,
    source_table: Table,
    target_table: Table,
    sample_size: int = 5,
) -> int:
    """Sample vectors from source and verify exact/approximate match in target."""
    with source_engine.connect() as src_conn, target_engine.connect() as dst_conn:
        stmt = (
            select(source_table.c.id, source_table.c.version, source_table.c.embedding)
            .where(source_table.c.embedding.is_not(None))
            .limit(sample_size)
        )
        sample_rows = src_conn.execute(stmt).all()
        if not sample_rows:
            logger.info("No vectors found to sample for verification.")
            return 0

        verified = 0
        for mem_id, version, src_embedding in sample_rows:
            target_stmt = select(target_table.c.embedding).where(
                target_table.c.id == mem_id, target_table.c.version == version
            )
            dst_embedding = dst_conn.execute(target_stmt).scalar_one_or_none()
            if dst_embedding is None:
                raise ValueError(
                    f"Vector verification failed: memory {mem_id} (version {version}) "
                    "not found in target."
                )

            src_list = list(src_embedding)
            dst_list = list(dst_embedding)
            if len(src_list) != len(dst_list):
                raise ValueError(
                    f"Vector dimension mismatch for memory {mem_id}: "
                    f"source={len(src_list)}, target={len(dst_list)}"
                )

            for i, (a, b) in enumerate(zip(src_list, dst_list, strict=True)):
                if not math.isclose(a, b, abs_tol=1e-4):
                    raise ValueError(
                        f"Vector element mismatch at index {i} for memory {mem_id}: {a} != {b}"
                    )

            verified += 1

        logger.info("Verified %d vector embeddings successfully.", verified)
        return verified


def migrate_database(
    source_url: str,
    target_url: str,
    dry_run: bool = False,
    force: bool = False,
    batch_size: int = 500,
    sample_size: int = 5,
    source_schema: str | None = None,
    target_schema: str | None = None,
) -> MigrationReport:
    """Execute the database migration from source to target."""
    norm_source = normalize_database_url(source_url)
    norm_target = normalize_database_url(target_url)

    src_parsed = make_url(norm_source)
    dst_parsed = make_url(norm_target)
    logger.info("Source database: %s", src_parsed.render_as_string(hide_password=True))
    logger.info("Target database: %s", dst_parsed.render_as_string(hide_password=True))

    src_engine = create_engine(norm_source)
    dst_engine = create_engine(norm_target)

    report = MigrationReport(dry_run=dry_run)

    try:
        # Check target memories row count
        target_memories_table = get_table_def("memories", schema=target_schema)
        source_memories_table = get_table_def("memories", schema=source_schema)

        target_memory_count = get_row_count(dst_engine, target_memories_table)
        if target_memory_count > 0 and not force:
            err = (
                f"Refusing to migrate: target database already contains {target_memory_count} "
                "memory rows. Use --force to proceed anyway."
            )
            logger.error(err)
            report.success = False
            report.error_message = err
            return report

        # Read source counts
        for table_name in TABLE_ORDER:
            src_tbl = get_table_def(table_name, schema=source_schema)
            count = get_row_count(src_engine, src_tbl)
            report.source_counts[table_name] = count
            logger.info("Source table '%s': %d rows", table_name, count)

        if dry_run:
            logger.info("DRY-RUN mode enabled. No data was written to target database.")
            return report

        # Copy each table in dependency order
        for table_name in TABLE_ORDER:
            src_tbl = get_table_def(table_name, schema=source_schema)
            dst_tbl = get_table_def(table_name, schema=target_schema)
            total_rows = report.source_counts[table_name]

            if total_rows == 0:
                logger.info("Table '%s' is empty in source; skipping.", table_name)
                report.target_counts[table_name] = get_row_count(dst_engine, dst_tbl)
                continue

            logger.info(
                "Migrating table '%s' (%d rows) in batches of %d...",
                table_name,
                total_rows,
                batch_size,
            )

            # For memories, ensure version order so foreign keys on previous_version resolve
            order_cols = []
            if table_name == "memories":
                order_cols = [src_tbl.c.version.asc(), src_tbl.c.created_at.asc()]
            elif "created_at" in src_tbl.c:
                order_cols = [src_tbl.c.created_at.asc()]

            offset = 0
            while offset < total_rows:
                stmt = select(src_tbl).limit(batch_size).offset(offset)
                if order_cols:
                    stmt = stmt.order_by(*order_cols)

                with src_engine.connect() as src_conn:
                    batch_rows = [dict(r) for r in src_conn.execute(stmt).mappings().all()]

                if batch_rows:
                    with dst_engine.begin() as dst_conn:
                        dst_conn.execute(dst_tbl.insert(), batch_rows)

                offset += len(batch_rows)
                logger.info(
                    "Migrated %d / %d rows for '%s'",
                    min(offset, total_rows),
                    total_rows,
                    table_name,
                )

            dst_count = get_row_count(dst_engine, dst_tbl)
            report.target_counts[table_name] = dst_count
            logger.info("Table '%s' migration complete: %d rows in target", table_name, dst_count)

            if dst_count < report.source_counts[table_name]:
                raise RuntimeError(
                    f"Row count mismatch for '{table_name}': "
                    f"expected {report.source_counts[table_name]}, got {dst_count}"
                )

        # Vector verification
        verified = verify_vectors(
            src_engine,
            dst_engine,
            source_memories_table,
            target_memories_table,
            sample_size=sample_size,
        )
        report.verified_vectors = verified
        logger.info("Database migration finished successfully!")
        return report

    finally:
        src_engine.dispose()
        dst_engine.dispose()


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate RecallFabric database from local Docker to managed cloud PostgreSQL."
    )
    parser.add_argument(
        "--source",
        dest="source_url",
        default=None,
        help="Source PostgreSQL database URL (defaults to local settings)",
    )
    parser.add_argument(
        "--target",
        dest="target_url",
        default=None,
        help="Target PostgreSQL database URL (defaults to RECALLFABRIC_DATABASE_URL env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate migration and report row counts without writing changes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow migration even if target database already contains memories rows",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of rows to copy per batch (default: 500)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5,
        help="Number of vector embeddings to sample and verify (default: 5)",
    )
    parser.add_argument(
        "--source-schema",
        default=None,
        help="Source database schema name (default: public)",
    )
    parser.add_argument(
        "--target-schema",
        default=None,
        help="Target database schema name (default: public)",
    )
    return parser.parse_args(args)


def main() -> None:
    args = parse_args()

    # Resolve source URL
    if args.source_url:
        source_url = args.source_url
    else:
        # Construct from local settings without database_url override
        settings = Settings(database_url=None)
        source_url = settings.get_database_url()

    # Resolve target URL
    target_url = args.target_url or os.environ.get("RECALLFABRIC_DATABASE_URL")
    if not target_url:
        settings = Settings()
        if settings.database_url and settings.database_url.get_secret_value().strip():
            target_url = settings.database_url.get_secret_value()

    if not target_url:
        logger.error(
            "Target database URL not provided. Set RECALLFABRIC_DATABASE_URL or pass --target."
        )
        sys.exit(1)

    try:
        report = migrate_database(
            source_url=source_url,
            target_url=target_url,
            dry_run=args.dry_run,
            force=args.force,
            batch_size=args.batch_size,
            sample_size=args.sample_size,
            source_schema=args.source_schema,
            target_schema=args.target_schema,
        )
        if not report.success:
            logger.error("Migration failed: %s", report.error_message)
            sys.exit(1)
    except Exception as exc:
        logger.exception("Migration encountered an unhandled error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
