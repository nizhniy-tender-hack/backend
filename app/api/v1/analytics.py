from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import AnalyticsServiceDep
from app.schemas.analytics import AnalyticsOverview

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=AnalyticsOverview, summary="Сводка по обращениям")
async def overview(
    service: AnalyticsServiceDep,
    date_from: datetime | None = Query(
        default=None, description="Начало периода по времени создания обращения (ISO 8601)"
    ),
    date_to: datetime | None = Query(default=None, description="Конец периода, включительно"),
) -> AnalyticsOverview:
    """Метрики админки: сколько обращений закрыл ИИ-агент, сколько ушло на поддержку и с какими оценками.

    «Закрыла ML» = обращение дошло до `closed`, ни разу не побывав у человека
    (`escalated_at` пуст). Оценки — те же звёзды 1-5 из `POST /tickets/{id}/feedback`.
    """
    return await service.overview(date_from=date_from, date_to=date_to)
