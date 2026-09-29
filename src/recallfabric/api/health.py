"""Separate process liveness from database readiness."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from recallfabric.db.connection import database_is_ready, get_database_engine

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str = "ok"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@router.get("/ready", response_model=HealthResponse, responses={503: {"description": "Not ready"}})
def readiness(engine: Annotated[Engine, Depends(get_database_engine)]) -> HealthResponse:
    try:
        ready = database_is_ready(engine)
    except SQLAlchemyError:
        # Do not expose connection details or credentials in HTTP responses.
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    if not ready:
        raise HTTPException(status_code=503, detail="Vector extension unavailable")
    return HealthResponse()
