import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import parse_qs, urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from recallfabric.core.config import Settings, get_settings
from recallfabric.db.models import (
    ApiKey,
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthRefreshToken,
)
from recallfabric.db.session import get_session
from recallfabric.schemas.auth import (
    ApiKeyCreatedResponse,
    ApiKeyInfoResponse,
    CreateApiKeyRequest,
    SignupRequest,
    SignupResponse,
)
from recallfabric.security.audit import record_audit_event
from recallfabric.security.auth import (
    generate_api_key,
    generate_oauth_token,
    hash_api_key,
    hash_oauth_token,
    require_admin_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
SessionDep = Annotated[Session, Depends(get_session)]
AdminDep = Annotated[str, Depends(require_admin_token)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _oauth_error(error: str, description: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": error, "error_description": description})


def _valid_redirect_uri(uri: str) -> bool:
    return (
        uri.startswith("https://")
        or uri.startswith("http://127.0.0.1")
        or uri.startswith("http://localhost")
    )


def _allowed_scopes(scope: str, settings: Settings) -> set[str]:
    requested = set(scope.split())
    supported = set(settings.oauth_scopes.split()) | {"offline_access"}
    if not requested or not requested.issubset(supported):
        raise _oauth_error("invalid_scope", "Requested scope is unsupported")
    return requested


def _issue_tokens(
    db: Session, settings: Settings, client_id: str, user_id: str, scope: str
) -> dict[str, object]:
    now = datetime.now(UTC)
    access_token, access_hash = generate_oauth_token("rf_at")
    refresh_token, refresh_hash = generate_oauth_token("rf_rt")
    db.add(
        OAuthAccessToken(
            token_hash=access_hash,
            client_id=client_id,
            user_id=user_id,
            scope=scope,
            expires_at=now + timedelta(minutes=settings.oauth_access_token_minutes),
        )
    )
    db.add(
        OAuthRefreshToken(
            token_hash=refresh_hash,
            client_id=client_id,
            user_id=user_id,
            scope=scope,
            expires_at=now + timedelta(days=settings.oauth_refresh_token_days),
        )
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": settings.oauth_access_token_minutes * 60,
        "scope": scope,
    }


@router.post("/oauth/register", status_code=status.HTTP_201_CREATED)
@router.post("/oauth/clients", status_code=status.HTTP_201_CREATED)
def register_oauth_client(payload: dict[str, object], db: SessionDep) -> dict[str, object]:
    """RFC 7591 public-client registration; PKCE is mandatory for every client."""
    redirect_uris = payload.get("redirect_uris") or [payload.get("redirect_uri", "")]
    if not isinstance(redirect_uris, list) or len(redirect_uris) != 1:
        raise _oauth_error("invalid_client_metadata", "Exactly one redirect URI is required")
    redirect_uri = str(redirect_uris[0]).strip()
    client_name = str(payload.get("client_name") or "RecallFabric MCP client").strip()
    if not client_name or not _valid_redirect_uri(redirect_uri):
        raise _oauth_error(
            "invalid_client_metadata", "A HTTPS (or loopback) redirect URI is required"
        )
    client_id = f"rf_client_{secrets.token_urlsafe(24)}"
    db.add(
        OAuthClient(client_id=client_id, client_name=client_name[:255], redirect_uri=redirect_uri)
    )
    db.commit()
    return {
        "client_id": client_id,
        "client_id_issued_at": int(datetime.now(UTC).timestamp()),
        "redirect_uris": [redirect_uri],
        "token_endpoint_auth_method": "none",
    }


@router.get("/oauth/authorize", response_class=HTMLResponse)
def authorize_oauth_client(
    db: SessionDep,
    settings: SettingsDep,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    code_challenge: str,
    code_challenge_method: str = "",
    scope: str = "memory:read memory:write",
    state: str | None = None,
) -> HTMLResponse:
    client = db.scalar(
        select(OAuthClient).where(
            OAuthClient.client_id == client_id, OAuthClient.revoked_at.is_(None)
        )
    )
    if client is None or client.redirect_uri != redirect_uri or response_type != "code":
        raise _oauth_error("invalid_request", "Unknown client or redirect URI")
    if code_challenge_method != "S256" or len(code_challenge) != 43:
        raise _oauth_error("invalid_request", "PKCE S256 code_challenge is required")
    requested = _allowed_scopes(scope, settings)
    transaction = OAuthAuthorizationRequest(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        scope=" ".join(sorted(requested)),
        state=state,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    db.add(transaction)
    db.commit()
    # The API key is a previously-issued credential: its possession is the account proof.
    body = (
        "<html><body><h1>Connect RecallFabric</h1><p>Authorize "
        f"{client.client_name}? Enter a RecallFabric API key for the account to link.</p>"
        '<form method="post" action="/auth/oauth/authorize/approve">'
        f'<input type="hidden" name="request_id" value="{transaction.id}">'
        f'<input type="hidden" name="csrf_token" value="{transaction.csrf_token}">'
        "<label>RecallFabric API key "
        '<input type="password" name="api_key" required autocomplete="off"></label>'
        '<button type="submit">Authorize</button></form></body></html>'
    )
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/oauth/authorize/approve")
def approve_oauth_client(
    db: SessionDep,
    settings: SettingsDep,
    request_id: Annotated[UUID, Form()],
    csrf_token: Annotated[str, Form()],
    api_key: Annotated[str, Form()],
) -> RedirectResponse:
    now = datetime.now(UTC)
    transaction = db.get(OAuthAuthorizationRequest, request_id)
    key = db.scalar(
        select(ApiKey).where(
            ApiKey.key_hash == hash_api_key(api_key.strip()), ApiKey.revoked_at.is_(None)
        )
    )
    if (
        transaction is None
        or transaction.expires_at <= now
        or transaction.approved_at is not None
        or not secrets.compare_digest(transaction.csrf_token, csrf_token)
        or key is None
    ):
        raise _oauth_error("access_denied", "Authorization could not be approved")
    raw_code, code_hash = generate_oauth_token("rf_code")
    transaction.approved_at = now
    db.add(
        OAuthAuthorizationCode(
            code_hash=code_hash,
            client_id=transaction.client_id,
            user_id=key.user_id,
            redirect_uri=transaction.redirect_uri,
            code_challenge=transaction.code_challenge,
            scope=transaction.scope,
            expires_at=now + timedelta(minutes=5),
        )
    )
    db.commit()
    params = {"code": raw_code}
    if transaction.state:
        params["state"] = transaction.state
    return RedirectResponse(f"{transaction.redirect_uri}?{urlencode(params)}", status_code=303)


@router.post("/oauth/token")
async def exchange_oauth_token(
    request: Request, db: SessionDep, settings: SettingsDep
) -> dict[str, object]:
    form = {key: values[0] for key, values in parse_qs((await request.body()).decode()).items()}
    now = datetime.now(UTC)
    client_id, grant_type = form.get("client_id", ""), form.get("grant_type", "")
    if grant_type == "authorization_code":
        code = db.scalar(
            select(OAuthAuthorizationCode).where(
                OAuthAuthorizationCode.code_hash == hash_oauth_token(form.get("code", ""))
            )
        )
        if (
            code is None
            or code.used_at is not None
            or code.expires_at <= now
            or code.client_id != client_id
            or code.redirect_uri != form.get("redirect_uri")
            or len(form.get("code_verifier", "")) < 43
            or not secrets.compare_digest(
                code.code_challenge, _pkce_s256(form.get("code_verifier", ""))
            )
        ):
            raise _oauth_error(
                "invalid_grant", "Invalid, expired, or already-used authorization code"
            )
        code.used_at = now
        response = _issue_tokens(db, settings, client_id, code.user_id, code.scope)
        db.commit()
        return response
    if grant_type == "refresh_token":
        refresh = db.scalar(
            select(OAuthRefreshToken).where(
                OAuthRefreshToken.token_hash == hash_oauth_token(form.get("refresh_token", ""))
            )
        )
        if (
            refresh is None
            or refresh.client_id != client_id
            or refresh.expires_at <= now
            or refresh.revoked_at is not None
        ):
            raise _oauth_error("invalid_grant", "Invalid or expired refresh token")
        if refresh.used_at is not None:
            db.execute(
                update(OAuthRefreshToken)
                .where(OAuthRefreshToken.family_id == refresh.family_id)
                .values(revoked_at=now)
            )
            db.commit()
            raise _oauth_error("invalid_grant", "Refresh-token reuse detected")
        refresh.used_at = now
        response = _issue_tokens(db, settings, client_id, refresh.user_id, refresh.scope)
        db.commit()
        return response
    raise _oauth_error(
        "unsupported_grant_type", "Supported grants are authorization_code and refresh_token"
    )


@router.post("/oauth/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_oauth_token(request: Request, db: SessionDep) -> None:
    form = {key: values[0] for key, values in parse_qs((await request.body()).decode()).items()}
    digest, now = hash_oauth_token(form.get("token", "")), datetime.now(UTC)
    for model in (OAuthAccessToken, OAuthRefreshToken):
        token = db.scalar(
            select(model).where(model.token_hash == digest, model.revoked_at.is_(None))
        )
        if token:
            token.revoked_at = now
            if isinstance(token, OAuthRefreshToken):
                db.execute(
                    update(OAuthRefreshToken)
                    .where(OAuthRefreshToken.family_id == token.family_id)
                    .values(revoked_at=now)
                )
    db.commit()


@router.post(
    "/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_api_key",
)
def create_api_key(
    payload: CreateApiKeyRequest,
    request: Request,
    db: SessionDep,
    _admin: AdminDep,
) -> ApiKeyCreatedResponse:
    raw_key, key_hash = generate_api_key()
    key_record = ApiKey(
        id=uuid4(),
        user_id=payload.user_id,
        name=payload.name,
        key_hash=key_hash,
    )
    db.add(key_record)
    db.commit()
    db.refresh(key_record)

    record_audit_event(
        db,
        "key_created",
        user_id=payload.user_id,
        ip_address=request.client.host if request.client else None,
        detail={"key_id": str(key_record.id), "name": payload.name},
    )
    db.commit()

    return ApiKeyCreatedResponse(
        id=key_record.id,
        user_id=key_record.user_id,
        name=key_record.name,
        key=raw_key,
        created_at=key_record.created_at,
    )


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="signup_user",
    summary="Self-serve onboarding for new users",
    description="Registers a user and issues an active API key when public signup is enabled.",
)
def signup(
    payload: SignupRequest,
    request: Request,
    db: SessionDep,
    settings: SettingsDep,
) -> SignupResponse:
    if settings.auth_enabled and not settings.allow_public_signup:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public signup is currently disabled. Contact your administrator.",
        )

    raw_key, key_hash = generate_api_key()
    key_record = ApiKey(
        id=uuid4(),
        user_id=payload.user_id,
        name=payload.name or "default",
        key_hash=key_hash,
    )
    db.add(key_record)
    db.commit()
    db.refresh(key_record)

    record_audit_event(
        db,
        "user_signup",
        user_id=payload.user_id,
        ip_address=request.client.host if request.client else None,
        detail={"key_id": str(key_record.id), "name": key_record.name},
    )
    db.commit()

    return SignupResponse(
        user_id=payload.user_id,
        api_key=raw_key,
        name=key_record.name,
        message="User onboarded successfully. Keep this API key safe.",
    )


@router.get("/keys", response_model=list[ApiKeyInfoResponse], operation_id="list_api_keys")
def list_api_keys(
    db: SessionDep,
    _admin: AdminDep,
    user_id: str | None = Query(default=None),
) -> list[ApiKeyInfoResponse]:
    stmt = select(ApiKey).order_by(ApiKey.created_at.desc())
    if user_id:
        stmt = stmt.where(ApiKey.user_id == user_id)
    records = db.scalars(stmt).all()
    return [
        ApiKeyInfoResponse(
            id=r.id,
            user_id=r.user_id,
            name=r.name,
            created_at=r.created_at,
            last_used_at=r.last_used_at,
            revoked_at=r.revoked_at,
        )
        for r in records
    ]


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="revoke_api_key",
)
def revoke_api_key(
    key_id: UUID,
    request: Request,
    db: SessionDep,
    _admin: AdminDep,
) -> None:
    key_record = db.get(ApiKey, key_id)
    if key_record is None:
        raise HTTPException(status_code=404, detail="API key not found")

    if key_record.revoked_at is None:
        key_record.revoked_at = datetime.now(UTC)
        record_audit_event(
            db,
            "key_revoked",
            user_id=key_record.user_id,
            ip_address=request.client.host if request.client else None,
            detail={"key_id": str(key_record.id)},
        )
        db.commit()
