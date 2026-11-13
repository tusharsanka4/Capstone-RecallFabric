"""Webhook transcript ingestion endpoints."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from recallfabric.core.config import Settings, get_settings
from recallfabric.schemas.ingest import IngestJobResponse, IngestJobStatus, IngestRequest
from recallfabric.security.auth import get_current_api_key
from recallfabric.services.ingest_service import (
    default_ingest_job_store,
    process_ingest_job_sync,
)

router = APIRouter(tags=["ingest"])


def _resolve_user(
    requested_user_id: str | None,
    api_key: Any,
    settings: Settings,
) -> str:
    if settings.auth_enabled:
        if api_key is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        if api_key.user_id:
            if requested_user_id and requested_user_id != api_key.user_id:
                raise HTTPException(
                    status_code=403,
                    detail=f"API key is restricted to user '{api_key.user_id}'.",
                )
            return api_key.user_id
        if requested_user_id:
            return requested_user_id
        raise HTTPException(status_code=400, detail="user_id must be provided")
    if requested_user_id and requested_user_id.strip():
        return requested_user_id.strip()
    return "default_user"


@router.post(
    "/ingest",
    response_model=IngestJobResponse,
    status_code=202,
    summary="Ingest conversation transcript for asynchronous memory extraction",
    description=(
        "Accepts a full conversation transcript (list of messages) from external apps "
        "and triggers asynchronous batch fact extraction and memory consolidation. "
        "Returns a job ID and a status URL to poll for results."
    ),
)
def ingest_transcript(
    payload: IngestRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    api_key: Annotated[Any, Depends(get_current_api_key)],
) -> IngestJobResponse:
    user_id = _resolve_user(payload.user_id, api_key, settings)
    job_id = str(uuid4())

    # Format transcript items
    transcript_dicts = []
    for turn in payload.transcript:
        if isinstance(turn, dict):
            transcript_dicts.append(turn)
        else:
            transcript_dicts.append({"role": turn.role, "content": turn.content})

    default_ingest_job_store.create_job(
        job_id=job_id,
        user_id=user_id,
        message_count=len(transcript_dicts),
    )

    engine = getattr(request.app.state, "database_engine", None)
    embedder = getattr(request.app.state, "embedding_provider", None)

    background_tasks.add_task(
        process_ingest_job_sync,
        job_id=job_id,
        user_id=user_id,
        transcript=transcript_dicts,
        source=payload.source,
        settings=settings,
        engine=engine,
        embedder=embedder,
        job_store=default_ingest_job_store,
    )

    status_path = f"/v1/ingest/jobs/{job_id}"
    return IngestJobResponse(
        job_id=job_id,
        status="pending",
        message="Transcript ingestion job queued successfully",
        status_url=status_path,
    )


@router.get(
    "/ingest/jobs/{job_id}",
    response_model=IngestJobStatus,
    summary="Get transcript ingestion job status",
    description=(
        "Check the current processing status, extracted memory count, and results for a job."
    ),
)
def get_ingest_job_status(
    job_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    api_key: Annotated[Any, Depends(get_current_api_key)],
) -> IngestJobStatus:
    job = default_ingest_job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Ingestion job '{job_id}' not found")

    if settings.auth_enabled and api_key is not None and api_key.user_id:
        if job["user_id"] != api_key.user_id:
            raise HTTPException(
                status_code=403,
                detail="Forbidden: Cannot view another user's job",
            )

    return IngestJobStatus(**job)
