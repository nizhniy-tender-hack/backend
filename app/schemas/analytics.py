from datetime import datetime

from pydantic import BaseModel, Field

from app.core.enums import EscalationReason, SupportLine


class StatusTotals(BaseModel):
    """Сколько обращений в каждом статусе на момент запроса."""

    total: int
    created: int
    in_progress: int
    in_support: int
    closed: int


class ResolutionStats(BaseModel):
    """Кто довёл обращение до конца: ИИ-агент или живая поддержка.

    Признак «закрыла ML» — обращение дошло до `closed`, ни разу не побывав у
    человека (`escalated_at IS NULL`). Как только обращение эскалировали, оно
    считается ушедшим на поддержку, даже если закрыл его потом сам пользователь.
    """

    closed_total: int
    closed_by_ml: int = Field(description="Закрыты без единой эскалации — заслуга ИИ-агента")
    closed_after_escalation: int = Field(description="Закрыты, но успели побывать у поддержки")
    escalated_total: int = Field(description="Все эскалированные обращения, включая ещё открытые")
    escalated_open: int = Field(description="Эскалированные и до сих пор не закрытые")
    ml_resolution_rate: float = Field(
        description="Доля закрытых силами ML среди всех обработанных (закрытые + висящие у поддержки)"
    )
    escalation_rate: float = Field(description="Доля эскалированных среди всех обращений")


class RatingStats(BaseModel):
    """Распределение оценок 1-5 по срезу обращений."""

    count: int = Field(description="Сколько обращений среза получили оценку")
    average: float | None = Field(description="Средний балл, null — оценок нет")
    distribution: dict[int, int] = Field(description="Ключи 1..5, значения — число оценок")


class RatingBreakdown(BaseModel):
    """Оценки целиком и в разрезе «закрыла ML» / «была эскалация»."""

    overall: RatingStats
    ml_closed: RatingStats
    escalated: RatingStats


class SupportLineStats(BaseModel):
    """Срез по линии поддержки. `support_line = null` — ML линию не проставил."""

    support_line: SupportLine | None
    total: int
    closed: int
    closed_by_ml: int
    escalated: int
    rating: RatingStats


class EscalationReasonStats(BaseModel):
    reason: EscalationReason | None
    count: int


class AnalyticsOverview(BaseModel):
    """Сводка для админки: объём обращений, доля ML и оценки."""

    generated_at: datetime
    date_from: datetime | None
    date_to: datetime | None
    totals: StatusTotals
    resolution: ResolutionStats
    ratings: RatingBreakdown
    by_support_line: list[SupportLineStats]
    by_escalation_reason: list[EscalationReasonStats]
