"""Request sessions; handlers commit transactions before returning responses."""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError, TimeoutError
from sqlalchemy.orm import Session

from recallfabric.db.connection import get_database_engine


def get_session(engine: Annotated[Engine, Depends(get_database_engine)]):
    try:
        with Session(engine) as session:
            yield session
    except IntegrityError:
        raise HTTPException(409, "Memory conflicts with stored data") from None
    except (OperationalError, TimeoutError):
        raise HTTPException(503, "Database unavailable") from None
    except SQLAlchemyError:
        raise HTTPException(500, "Database operation failed") from None
