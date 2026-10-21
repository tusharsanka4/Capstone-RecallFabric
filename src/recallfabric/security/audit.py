from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from recallfabric.db.models import AuditLog


def record_audit_event(
    db: Session,
    event_type: str,
    user_id: str | None = None,
    ip_address: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    log_entry = AuditLog(
        id=uuid4(),
        user_id=user_id,
        event_type=event_type,
        ip_address=ip_address,
        detail=detail or {},
    )
    db.add(log_entry)
    try:
        db.flush()
    except Exception:
        pass
    return log_entry
