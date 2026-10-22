import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.metadata import version

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from recallfabric.api.auth import router as auth_router
from recallfabric.api.chat import router as chat_router
from recallfabric.api.embeddings import router as embeddings_router
from recallfabric.api.extraction import router as extraction_router
from recallfabric.api.health import router as health_router
from recallfabric.api.ingest import router as ingest_router
from recallfabric.api.memories import router as memories_router
from recallfabric.api.provenance import router as provenance_router
from recallfabric.api.providers import router as providers_router
from recallfabric.api.proxy import router as proxy_router
from recallfabric.api.users import router as users_router
from recallfabric.api.v1_tools import router as v1_tools_router
from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from recallfabric.db.models import ApiKey
from recallfabric.embeddings.service import (
    EmbeddingUnavailable,
    create_embedding_provider,
)
from recallfabric.mcp_server import create_mcp_server, current_mcp_user_id
from recallfabric.providers import (
    ProviderBadResponse,
    ProviderTimeout,
    ProviderUnavailable,
)
from recallfabric.security.audit import record_audit_event
from recallfabric.security.auth import extract_token_from_request, hash_api_key
from recallfabric.security.rate_limiter import rate_limiter

logger = logging.getLogger("recallfabric.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings()
    # Explicitly ensure production settings safety validation runs
    settings.validate_production_settings()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mcp_server = create_mcp_server(settings=settings)
    mcp_subapp = mcp_server.streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_database_engine(settings)
        app.state.database_engine = engine
        if hasattr(app.state, "mcp_tools") and app.state.mcp_tools is not None:
            app.state.mcp_tools.engine = engine
            app.state.mcp_tools.embedder = app.state.embedding_provider

        # If session_manager already ran in a prior lifespan (e.g. repeated TestClient(app)),
        # refresh StreamableHTTPSessionManager so it can run again cleanly.
        if mcp_server.session_manager._has_started:
            from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

            old_sm = mcp_server.session_manager
            new_sm = StreamableHTTPSessionManager(
                app=mcp_server._lowlevel_server,
                event_store=old_sm.event_store,
                json_response=old_sm.json_response,
                stateless=old_sm.stateless,
                retry_interval=old_sm.retry_interval,
                max_request_body_size=old_sm.max_request_body_size,
                session_idle_timeout=old_sm.session_idle_timeout,
                max_sessions=old_sm.max_sessions,
                security_settings=old_sm.security_settings,
            )
            mcp_server._lowlevel_server._session_manager = new_sm
            if hasattr(mcp_subapp, "routes") and mcp_subapp.routes:
                mcp_subapp.routes[0].endpoint.session_manager = new_sm

        async with mcp_server.session_manager.run():
            try:
                yield
            finally:
                engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        description="Persistent, structured, portable memory for AI applications.",
        version=version("recallfabric"),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.embedding_provider = create_embedding_provider(settings)
    app.state.mcp_server = mcp_server
    app.state.mcp_tools = getattr(mcp_server, "tools_wrapper", None)

    # Trusted proxy headers (X-Forwarded-For, X-Forwarded-Proto) for reverse proxies
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging without bodies (prevents logging sensitive payloads)
    @app.middleware("http")
    async def log_requests_without_bodies(request: Request, call_next):
        start_time = time.perf_counter()
        client_ip = request.headers.get("x-forwarded-for") or (
            request.client.host if request.client else "unknown"
        )
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()

        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        logger.info(
            "request method=%s path=%s status=%d duration_ms=%.2f client_ip=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            client_ip,
        )
        return response

    http_code_names = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        422: "VALIDATION_ERROR",
        500: "INTERNAL_SERVER_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }

    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def custom_http_exception_handler(
        request: Request, exc: HTTPException | StarletteHTTPException
    ):
        if request.url.path.startswith("/v1"):
            code = http_code_names.get(exc.status_code, f"HTTP_{exc.status_code}")
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": code, "message": str(exc.detail)}},
                headers=getattr(exc, "headers", None),
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/v1"):
            errors = exc.errors()
            formatted_errors = []
            for err in errors:
                loc_str = " -> ".join(str(loc) for loc in err.get("loc", []))
                err_msg = err.get("msg", "Invalid")
                formatted_errors.append(f"{loc_str}: {err_msg}")
            msg = "; ".join(formatted_errors)
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "VALIDATION_ERROR", "message": msg}},
            )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.exception_handler(EmbeddingUnavailable)
    async def embedding_unavailable(request: Request, exc: EmbeddingUnavailable):
        if request.url.path.startswith("/v1"):
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "EMBEDDING_UNAVAILABLE",
                        "message": "Embedding model unavailable",
                    }
                },
            )
        return JSONResponse(status_code=503, content={"detail": "Embedding model unavailable"})

    @app.exception_handler(ProviderUnavailable)
    async def provider_unavailable(request: Request, exc: ProviderUnavailable):
        msg = str(exc) or "LLM service unreachable"
        if request.url.path.startswith("/v1"):
            return JSONResponse(
                status_code=503,
                content={"error": {"code": "PROVIDER_UNAVAILABLE", "message": msg}},
            )
        return JSONResponse(status_code=503, content={"detail": msg})

    @app.exception_handler(ProviderTimeout)
    async def provider_timeout(request: Request, exc: ProviderTimeout):
        msg = str(exc) or "LLM request timed out"
        if request.url.path.startswith("/v1"):
            return JSONResponse(
                status_code=504,
                content={"error": {"code": "PROVIDER_TIMEOUT", "message": msg}},
            )
        return JSONResponse(status_code=504, content={"detail": msg})

    @app.exception_handler(ProviderBadResponse)
    async def provider_bad_response(request: Request, exc: ProviderBadResponse):
        msg = str(exc) or "LLM request failed"
        if request.url.path.startswith("/v1"):
            return JSONResponse(
                status_code=502,
                content={"error": {"code": "PROVIDER_BAD_RESPONSE", "message": msg}},
            )
        return JSONResponse(status_code=502, content={"detail": msg})

    @app.middleware("http")
    async def limit_request_size(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
                if length > settings.max_request_size_bytes:
                    if request.url.path.startswith("/v1") or request.url.path.startswith("/mcp"):
                        return JSONResponse(
                            status_code=413,
                            content={
                                "error": {
                                    "code": "PAYLOAD_TOO_LARGE",
                                    "message": "Request payload exceeds maximum allowed size",
                                }
                            },
                        )
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request payload exceeds maximum allowed size"},
                    )
            except ValueError:
                pass
        return await call_next(request)

    _mcp_sessions: dict[str, str] = {}

    @app.middleware("http")
    async def mcp_streamable_http_middleware(request: Request, call_next):
        path = request.url.path
        if path == "/mcp":
            request.scope["path"] = "/mcp/"
            path = "/mcp/"

        if path.startswith("/mcp"):
            # Handle CORS preflight
            if request.method == "OPTIONS":
                return await call_next(request)

            engine = getattr(request.app.state, "database_engine", None)
            client_ip = request.client.host if request.client else None
            raw_key = extract_token_from_request(request, ("x-api-key",))

            if settings.auth_enabled:
                if not raw_key:
                    if engine is not None:
                        try:
                            with Session(engine, expire_on_commit=False) as auth_sess:
                                record_audit_event(
                                    auth_sess,
                                    "auth_failure",
                                    ip_address=client_ip,
                                    detail={"reason": "missing_api_key", "path": path},
                                )
                                auth_sess.commit()
                        except Exception:
                            pass
                    return JSONResponse(
                        status_code=401,
                        content={"error": {"code": "UNAUTHORIZED", "message": "Missing API key"}},
                    )

                key_hash = hash_api_key(raw_key)
                if engine is None:
                    return JSONResponse(
                        status_code=503,
                        content={
                            "error": {
                                "code": "SERVICE_UNAVAILABLE",
                                "message": "Database unavailable",
                            }
                        },
                    )

                with Session(engine, expire_on_commit=False) as auth_sess:
                    api_key = auth_sess.scalar(
                        select(ApiKey).where(
                            ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None)
                        )
                    )
                    if api_key is None:
                        record_audit_event(
                            auth_sess,
                            "auth_failure",
                            ip_address=client_ip,
                            detail={"reason": "invalid_or_revoked_key", "path": path},
                        )
                        auth_sess.commit()
                        return JSONResponse(
                            status_code=401,
                            content={
                                "error": {
                                    "code": "UNAUTHORIZED",
                                    "message": "Invalid or revoked API key",
                                }
                            },
                        )

                    if not rate_limiter.check_rate_limit(
                        api_key.key_hash, settings.rate_limit_rps, settings.rate_limit_burst
                    ):
                        return JSONResponse(
                            status_code=429,
                            content={
                                "error": {
                                    "code": "RATE_LIMIT_EXCEEDED",
                                    "message": "Rate limit exceeded",
                                }
                            },
                        )

                    sess_id = request.headers.get("mcp-session-id")
                    if sess_id:
                        sess_owner = _mcp_sessions.get(sess_id)
                        if sess_owner and sess_owner != api_key.user_id:
                            return JSONResponse(
                                status_code=403,
                                content={
                                    "error": {
                                        "code": "FORBIDDEN",
                                        "message": "Session belongs to another user",
                                    }
                                },
                            )
                        _mcp_sessions[sess_id] = api_key.user_id

                    api_key.last_used_at = datetime.now(UTC)
                    auth_sess.commit()
                    resolved_uid = api_key.user_id
            else:
                if raw_key and engine is not None:
                    key_hash = hash_api_key(raw_key)
                    with Session(engine, expire_on_commit=False) as auth_sess:
                        api_key = auth_sess.scalar(
                            select(ApiKey).where(
                                ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None)
                            )
                        )
                        resolved_uid = (
                            api_key.user_id if api_key else (settings.mcp_user_id or "default_user")
                        )
                else:
                    resolved_uid = settings.mcp_user_id or "default_user"

                rate_key = raw_key or client_ip or resolved_uid
                if not rate_limiter.check_rate_limit(
                    rate_key, settings.rate_limit_rps, settings.rate_limit_burst
                ):
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": {
                                "code": "RATE_LIMIT_EXCEEDED",
                                "message": "Rate limit exceeded",
                            }
                        },
                    )

            token = current_mcp_user_id.set(resolved_uid)
            try:
                response = await call_next(request)
                resp_sess_id = response.headers.get("mcp-session-id")
                if resp_sess_id:
                    _mcp_sessions[resp_sess_id] = resolved_uid
                return response
            finally:
                current_mcp_user_id.reset(token)

        return await call_next(request)

    # 1. Canonical /v1 API Surface (documented in OpenAPI)
    v1_router = APIRouter(prefix="/v1")
    v1_router.include_router(v1_tools_router)
    v1_router.include_router(memories_router)
    v1_router.include_router(extraction_router)
    v1_router.include_router(chat_router)
    v1_router.include_router(embeddings_router)
    v1_router.include_router(auth_router)
    v1_router.include_router(users_router)
    v1_router.include_router(provenance_router)
    v1_router.include_router(providers_router)
    v1_router.include_router(proxy_router)
    v1_router.include_router(ingest_router)
    app.include_router(v1_router)

    # 2. Health and readiness liveness checks
    app.include_router(health_router)

    # 3. Unversioned Route Aliases (working aliases, hidden from schema to prevent duplicates)
    app.include_router(v1_tools_router, include_in_schema=False)
    app.include_router(memories_router, include_in_schema=False)
    app.include_router(extraction_router, include_in_schema=False)
    app.include_router(chat_router, include_in_schema=False)
    app.include_router(embeddings_router, include_in_schema=False)
    app.include_router(auth_router, include_in_schema=False)
    app.include_router(users_router, include_in_schema=False)
    app.include_router(provenance_router, include_in_schema=False)
    app.include_router(providers_router, include_in_schema=False)
    app.include_router(proxy_router, include_in_schema=False)
    app.include_router(ingest_router, include_in_schema=False)

    # 4. Streamable HTTP MCP server mounted at /mcp
    app.mount("/mcp", mcp_subapp)
    return app
