"""Shared locking order for revision updates and deletion."""

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from recallfabric.db.models import Memory


class MemoryNotFound(ValueError):
    pass


class MemoryConflict(ValueError):
    pass


def lock_memory_revision(session: Session, user_id: str, memory_id: UUID) -> None:
    # Same account lock as remember/deduplication; then the stable first revision.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"dedupe:{user_id}"},
    )
    root = session.scalar(
        select(Memory)
        .where(Memory.id == memory_id, Memory.user_id == user_id, Memory.version == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if root is None:
        raise MemoryNotFound("Memory not found")
