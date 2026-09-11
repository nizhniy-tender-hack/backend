from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import SessionDep
from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="Живость сервиса")
async def health() -> dict:
    return {"status": "ok", "environment": settings.environment}


@router.get("/health/db", summary="Доступность PostgreSQL")
async def health_db(session: SessionDep) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
