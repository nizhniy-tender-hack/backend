import uuid
from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    STATUS_WEIGHT,
    ActorType,
    SupportLine,
    TicketSort,
    TicketStatus,
    is_transition_allowed,
)
from app.core.exceptions import (
    FeedbackNotFoundError,
    InvalidStatusTransitionError,
    TicketNotClosedError,
    TicketNotFoundError,
)
from app.models.ticket import Ticket, TicketEvent, TicketFeedback
from app.schemas.ticket import (
    FeedbackCreate,
    TicketClose,
    TicketCreate,
    TicketEscalate,
    TicketStatusUpdate,
    TicketUpdate,
)


class TicketService:
    """Вся бизнес-логика работы с обращениями. Роутеры остаются тонкими."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: TicketCreate) -> Ticket:
        ticket = Ticket(
            thread_id=payload.thread_id,
            user_id=payload.user_id,
            channel=payload.channel,
            subject=payload.subject,
            question=payload.question,
            status=payload.status,
            support_line=payload.support_line,
            meta=payload.metadata,
        )
        ticket.events.append(
            TicketEvent(
                from_status=None,
                to_status=payload.status,
                actor=ActorType.USER,
                comment="Обращение создано",
            )
        )
        self._apply_status_side_effects(ticket, payload.status)

        self.session.add(ticket)
        await self.session.commit()
        await self.session.refresh(ticket)
        return ticket

    async def get(self, ticket_id: uuid.UUID) -> Ticket:
        ticket = await self.session.get(Ticket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(ticket_id)
        return ticket

    async def list(
        self,
        *,
        status: TicketStatus | None = None,
        support_line: SupportLine | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        sort: TicketSort = TicketSort.CREATED_DESC,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Ticket], int]:
        query = select(Ticket)
        if status is not None:
            query = query.where(Ticket.status == status)
        if support_line is not None:
            query = query.where(Ticket.support_line == support_line)
        if thread_id is not None:
            query = query.where(Ticket.thread_id == thread_id)
        if user_id is not None:
            query = query.where(Ticket.user_id == user_id)

        total = await self.session.scalar(
            select(func.count()).select_from(query.order_by(None).subquery())
        )

        # `id` в конце — тайбрейкер: без него обращения с одинаковым created_at
        # выдаются в произвольном порядке, и постраничная выдача начинает
        # дублировать либо терять строки между limit/offset-запросами.
        if sort is TicketSort.STATUS_PRIORITY:
            # Наверху обращения, ждущие человека; закрытые уходят в конец.
            # Внутри одного статуса — сначала свежие.
            # Сравнения строим явно: словарная форма case(..., value=...) не приводит
            # ключи к типу колонки и подставляет значения перечисления вместо имён,
            # которыми оно хранится в БД — тогда ни одно WHEN не срабатывает.
            weight = case(
                *[(Ticket.status == item, order) for item, order in STATUS_WEIGHT.items()],
                else_=len(STATUS_WEIGHT),
            )
            ordering = (weight.asc(), Ticket.created_at.desc(), Ticket.id.desc())
        else:
            ordering = (Ticket.created_at.desc(), Ticket.id.desc())

        result = await self.session.scalars(query.order_by(*ordering).limit(limit).offset(offset))
        return list(result.all()), int(total or 0)

    async def update(self, ticket_id: uuid.UUID, payload: TicketUpdate) -> Ticket:
        ticket = await self.get(ticket_id)
        data = payload.model_dump(exclude_unset=True)
        if "metadata" in data:
            ticket.meta = data.pop("metadata")
        for field, value in data.items():
            setattr(ticket, field, value)

        await self.session.commit()
        await self.session.refresh(ticket)
        return ticket

    async def change_status(self, ticket_id: uuid.UUID, payload: TicketStatusUpdate) -> Ticket:
        ticket = await self.get(ticket_id)
        if not is_transition_allowed(ticket.status, payload.status):
            raise InvalidStatusTransitionError(ticket.status, payload.status)

        previous = ticket.status
        ticket.status = payload.status
        if payload.resolution is not None:
            ticket.resolution = payload.resolution
        self._apply_status_side_effects(ticket, payload.status)

        if previous != payload.status:
            ticket.events.append(
                TicketEvent(
                    from_status=previous,
                    to_status=payload.status,
                    actor=payload.actor,
                    comment=payload.comment,
                )
            )

        await self.session.commit()
        await self.session.refresh(ticket)
        return ticket

    async def escalate(self, ticket_id: uuid.UUID, payload: TicketEscalate) -> Ticket:
        """Вызов сотрудника: перевод обращения в статус «в работе у поддержки»."""
        ticket = await self.get(ticket_id)
        if not is_transition_allowed(ticket.status, TicketStatus.IN_SUPPORT):
            raise InvalidStatusTransitionError(ticket.status, TicketStatus.IN_SUPPORT)

        previous = ticket.status
        ticket.status = TicketStatus.IN_SUPPORT
        ticket.escalation_reason = payload.reason
        ticket.escalated_at = datetime.now(UTC)
        if payload.support_line is not None:
            ticket.support_line = payload.support_line
        if payload.summary is not None:
            ticket.summary = payload.summary
        if payload.assignee is not None:
            ticket.assignee = payload.assignee

        ticket.events.append(
            TicketEvent(
                from_status=previous,
                to_status=TicketStatus.IN_SUPPORT,
                actor=(
                    ActorType.USER if payload.reason.value == "user_requested" else ActorType.AGENT
                ),
                comment=payload.comment or f"Эскалация: {payload.reason.value}",
            )
        )

        await self.session.commit()
        await self.session.refresh(ticket)
        return ticket

    async def close(self, ticket_id: uuid.UUID, payload: TicketClose) -> Ticket:
        """Закрытие обращения: перевод в терминальный статус closed."""
        ticket = await self.get(ticket_id)
        if not is_transition_allowed(ticket.status, TicketStatus.CLOSED):
            raise InvalidStatusTransitionError(ticket.status, TicketStatus.CLOSED)

        previous = ticket.status
        ticket.status = TicketStatus.CLOSED
        if payload.resolution is not None:
            ticket.resolution = payload.resolution
        self._apply_status_side_effects(ticket, TicketStatus.CLOSED)

        if previous != TicketStatus.CLOSED:
            ticket.events.append(
                TicketEvent(
                    from_status=previous,
                    to_status=TicketStatus.CLOSED,
                    actor=payload.actor,
                    comment=payload.comment or "Обращение закрыто",
                )
            )

        await self.session.commit()
        await self.session.refresh(ticket)
        return ticket

    async def set_feedback(self, ticket_id: uuid.UUID, payload: FeedbackCreate) -> TicketFeedback:
        """Оценка обращения после закрытия. Повторный вызов перезаписывает оценку."""
        ticket = await self.get(ticket_id)
        if ticket.status != TicketStatus.CLOSED:
            raise TicketNotClosedError(ticket.status)

        if ticket.feedback is None:
            ticket.feedback = TicketFeedback(score=payload.score, comment=payload.comment)
        else:
            ticket.feedback.score = payload.score
            ticket.feedback.comment = payload.comment

        await self.session.commit()
        await self.session.refresh(ticket)
        return ticket.feedback

    async def get_feedback(self, ticket_id: uuid.UUID) -> TicketFeedback:
        ticket = await self.get(ticket_id)
        if ticket.feedback is None:
            raise FeedbackNotFoundError(ticket_id)
        return ticket.feedback

    async def delete(self, ticket_id: uuid.UUID) -> None:
        ticket = await self.get(ticket_id)
        await self.session.delete(ticket)
        await self.session.commit()

    @staticmethod
    def _apply_status_side_effects(ticket: Ticket, status: TicketStatus) -> None:
        """Поля-отметки времени, зависящие от нового статуса."""
        if status == TicketStatus.CLOSED:
            ticket.closed_at = ticket.closed_at or datetime.now(UTC)
        else:
            ticket.closed_at = None
        if status == TicketStatus.IN_SUPPORT and ticket.escalated_at is None:
            ticket.escalated_at = datetime.now(UTC)
