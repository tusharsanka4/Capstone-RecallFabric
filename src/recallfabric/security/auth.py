import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from recallfabric.core.config import Settings, get_settings
from recallfabric.db.models import ApiKey
from recallfabric.db.session import get_session
from recallfabric.security.audit import record_audit_event
from recallfabric.security.rate_limiter import rate_limiter

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def generate_api_key() -> tuple[str, str]:
    token = f"rf_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token, key_hash


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


def extract_token_from_request(
    request: Request, header_names: tuple[str, ...] = ("x-api-key",)
) -> str | None:
    auth_header = request.headers.get("authorization")
    if auth_header:
        parts = auth_header.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        if len(parts) == 1:
            return parts[0].strip()
    for name in header_names:
        val = request.headers.get(name)
        if val:
            return val.strip()
    return None


def get_current_api_key(
    request: Request,
    settings: SettingsDep,
) -> ApiKey | None:
    if not settings.auth_enabled:
        return None

    raw_key = extract_token_from_request(request, ("x-api-key",))
    client_ip = request.client.host if request.client else None

    engine = getattr(request.app.state, "database_engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    with Session(engine, expire_on_commit=False) as auth_session:
        if not raw_key:
            record_audit_event(
                auth_session,
                "auth_failure",
                ip_address=client_ip,
                detail={"reason": "missing_api_key", "path": request.url.path},
            )
            auth_session.commit()
            raise HTTPException(status_code=401, detail="Missing API key")

        key_hash = hash_api_key(raw_key)
        api_key = auth_session.scalars(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        ).first()

        if api_key is None:
            record_audit_event(
                auth_session,
                "auth_failure",
                ip_address=client_ip,
                detail={"reason": "invalid_or_revoked_key", "path": request.url.path},
            )
            auth_session.commit()
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")

        if not rate_limiter.check_rate_limit(
            api_key.key_hash, settings.rate_limit_rps, settings.rate_limit_burst
        ):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        api_key.last_used_at = datetime.now(UTC)
        auth_session.commit()

    return api_key


def verify_user_access(
    target_user_id: str,
    api_key: ApiKey | None,
    settings: Settings,
) -> None:
    if not settings.auth_enabled:
        return
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing API key")
    if api_key.user_id != target_user_id:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Authenticated user cannot access data of another user",
        )


def require_admin_token(
    request: Request,
    settings: SettingsDep,
) -> str:
    raw_token = extract_token_from_request(request, ("x-admin-token",))
    client_ip = request.client.host if request.client else None
    expected = settings.admin_token.get_secret_value()

    if not expected or not raw_token or not hmac.compare_digest(raw_token, expected):
        engine = getattr(request.app.state, "database_engine", None)
        if engine is not None:
            try:
                with Session(engine) as auth_session:
                    record_audit_event(
                        auth_session,
                        "auth_failure",
                        ip_address=client_ip,
                        detail={"reason": "invalid_admin_token", "path": request.url.path},
                    )
                    auth_session.commit()
            except Exception:
                pass
        raise HTTPException(status_code=401, detail="Invalid or missing admin token")

    return raw_token
