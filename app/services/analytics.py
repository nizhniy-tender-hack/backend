from datetime import UTC, datetime

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EscalationReason, SupportLine, TicketStatus
from app.models.ticket import Ticket, TicketFeedback
from app.schemas.analytics import (
    AnalyticsOverview,
    EscalationReasonStats,
    RatingBreakdown,
    RatingStats,
    ResolutionStats,
    StatusTotals,
    SupportLineStats,
)

SCORES = (1, 2, 3, 4, 5)


def _rate(part: int, whole: int) -> float:
    """Доля с округлением до 4 знаков; ноль вместо деления на ноль."""
    return round(part / whole, 4) if whole else 0.0


def _rating(distribution: dict[int, int]) -> RatingStats:
    count = sum(distribution.values())
    total = sum(score * number for score, number in distribution.items())
    return RatingStats(
        count=count,
        average=round(total / count, 2) if count else None,
        distribution=distribution,
    )


def _empty_distribution() -> dict[int, int]:
    return {score: 0 for score in SCORES}


class AnalyticsService:
    """Агрегаты по обращениям для админки.

    Ключевое деление — «закрыла ML» против «ушло на поддержку». Признак
    эскалации берём по `escalated_at`, а не по текущему статусу: обращение
    может побывать у оператора и закрыться, и тогда статус уже ничего об этом
    не говорит. Считаем в SQL — на проде обращений много, тянуть их в питон
    ради счётчиков незачем.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        # Период запроса; выставляется в `overview` и читается срезами ниже.
        self._date_from: datetime | None = None
        self._date_to: datetime | None = None

    async def overview(
        self, *, date_from: datetime | None = None, date_to: datetime | None = None
    ) -> AnalyticsOverview:
        self._date_from = date_from
        self._date_to = date_to

        totals = await self._status_totals()
        resolution = await self._resolution(totals)
        ratings = await self._ratings()
        by_support_line = await self._by_support_line()
        by_escalation_reason = await self._by_escalation_reason()

        return AnalyticsOverview(
            generated_at=datetime.now(UTC),
            date_from=date_from,
            date_to=date_to,
            totals=totals,
            resolution=resolution,
            ratings=ratings,
            by_support_line=by_support_line,
            by_escalation_reason=by_escalation_reason,
        )

    # --- вспомогательное ---

    def _period(self, query: Select) -> Select:
        """Ограничение периода по времени создания обращения."""
        if self._date_from is not None:
            query = query.where(Ticket.created_at >= self._date_from)
        if self._date_to is not None:
            query = query.where(Ticket.created_at <= self._date_to)
        return query

    @staticmethod
    def _count_if(condition) -> object:
        return func.count(case((condition, 1)))

    # --- срезы ---

    async def _status_totals(self) -> StatusTotals:
        rows = await self.session.execute(
            self._period(select(Ticket.status, func.count()).group_by(Ticket.status))
        )
        counts = {status: 0 for status in TicketStatus}
        for status, number in rows:
            counts[TicketStatus(status)] = int(number)

        return StatusTotals(
            total=sum(counts.values()),
            created=counts[TicketStatus.CREATED],
            in_progress=counts[TicketStatus.IN_PROGRESS],
            in_support=counts[TicketStatus.IN_SUPPORT],
            closed=counts[TicketStatus.CLOSED],
        )

    async def _resolution(self, totals: StatusTotals) -> ResolutionStats:
        is_closed = Ticket.status == TicketStatus.CLOSED
        escalated = Ticket.escalated_at.is_not(None)

        row = (
            await self.session.execute(
                self._period(
                    select(
                        self._count_if(is_closed & ~escalated),
                        self._count_if(is_closed & escalated),
                        self._count_if(escalated),
                        self._count_if(escalated & ~is_closed),
                    ).select_from(Ticket)
                )
            )
        ).one()
        closed_by_ml, closed_after_escalation, escalated_total, escalated_open = (
            int(value) for value in row
        )

        # Знаменатель доли ML — обращения с понятным исходом: закрытые и те,
        # что сейчас разбирает поддержка. Висящие created/in_progress ещё
        # ничего не решили, их учитывать нечестно в обе стороны.
        handled = totals.closed + escalated_open
        return ResolutionStats(
            closed_total=totals.closed,
            closed_by_ml=closed_by_ml,
            closed_after_escalation=closed_after_escalation,
            escalated_total=escalated_total,
            escalated_open=escalated_open,
            ml_resolution_rate=_rate(closed_by_ml, handled),
            escalation_rate=_rate(escalated_total, totals.total),
        )

    async def _ratings(self) -> RatingBreakdown:
        rows = await self.session.execute(
            self._period(
                select(
                    TicketFeedback.score,
                    Ticket.escalated_at.is_not(None).label("escalated"),
                    func.count(),
                )
                .select_from(TicketFeedback)
                .join(Ticket, Ticket.id == TicketFeedback.ticket_id)
                .group_by(TicketFeedback.score, "escalated")
            )
        )

        overall = _empty_distribution()
        ml_closed = _empty_distribution()
        escalated_dist = _empty_distribution()
        for score, escalated, number in rows:
            number = int(number)
            overall[score] = overall.get(score, 0) + number
            target = escalated_dist if escalated else ml_closed
            target[score] = target.get(score, 0) + number

        return RatingBreakdown(
            overall=_rating(overall),
            ml_closed=_rating(ml_closed),
            escalated=_rating(escalated_dist),
        )

    async def _by_support_line(self) -> list[SupportLineStats]:
        is_closed = Ticket.status == TicketStatus.CLOSED
        escalated = Ticket.escalated_at.is_not(None)

        rows = await self.session.execute(
            self._period(
                select(
                    Ticket.support_line,
                    func.count(),
                    self._count_if(is_closed),
                    self._count_if(is_closed & ~escalated),
                    self._count_if(escalated),
                )
                .select_from(Ticket)
                .group_by(Ticket.support_line)
            )
        )
        counters = {
            line: (int(total), int(closed), int(by_ml), int(escalated_count))
            for line, total, closed, by_ml, escalated_count in rows
        }

        score_rows = await self.session.execute(
            self._period(
                select(Ticket.support_line, TicketFeedback.score, func.count())
                .select_from(TicketFeedback)
                .join(Ticket, Ticket.id == TicketFeedback.ticket_id)
                .group_by(Ticket.support_line, TicketFeedback.score)
            )
        )
        distributions: dict[str | None, dict[int, int]] = {}
        for line, score, number in score_rows:
            distributions.setdefault(line, _empty_distribution())[score] = int(number)

        # Порядок: линии по возрастанию, «без линии» в конце — так проще читать в таблице.
        order = [*SupportLine, None]
        stats = []
        for line in order:
            key = line.value if line is not None else None
            if key not in counters:
                continue
            total, closed, by_ml, escalated_count = counters[key]
            stats.append(
                SupportLineStats(
                    support_line=line,
                    total=total,
                    closed=closed,
                    closed_by_ml=by_ml,
                    escalated=escalated_count,
                    rating=_rating(distributions.get(key, _empty_distribution())),
                )
            )
        return stats

    async def _by_escalation_reason(self) -> list[EscalationReasonStats]:
        rows = await self.session.execute(
            self._period(
                select(Ticket.escalation_reason, func.count())
                .where(Ticket.escalated_at.is_not(None))
                .group_by(Ticket.escalation_reason)
            )
        )
        counts = {reason: int(number) for reason, number in rows}
        return [
            EscalationReasonStats(reason=reason, count=counts[key])
            for reason, key in ((item, item.value) for item in EscalationReason)
            if key in counts
        ] + (
            [EscalationReasonStats(reason=None, count=counts[None])] if None in counts else []
        )
