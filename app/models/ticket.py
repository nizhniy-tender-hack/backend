import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.enums import ActorType, EscalationReason, SupportLine, TicketStatus
from app.db.base import Base, TimestampMixin

# JSONB в PostgreSQL, обычный JSON в остальных диалектах (SQLite в тестах).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Ticket(TimestampMixin, Base):
    """Обращение пользователя в поддержку."""

    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_status_support_line", "status", "support_line"),
        Index("ix_tickets_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Идентификатор диалога в ML-сервисе (LangGraph thread_id) — связывает тикет с перепиской.
    thread_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    channel: Mapped[str] = mapped_column(String(32), default="web", nullable=False)

    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status", native_enum=False, length=32),
        default=TicketStatus.CREATED,
        nullable=False,
        index=True,
    )
    support_line: Mapped[SupportLine | None] = mapped_column(
        Enum(SupportLine, name="support_line", native_enum=False, length=32),
        nullable=True,
        index=True,
    )

    escalation_reason: Mapped[EscalationReason | None] = mapped_column(
        Enum(EscalationReason, name="escalation_reason", native_enum=False, length=32),
        nullable=True,
    )
    # Саммари диалога, которое ML-сервис передаёт оператору при эскалации.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Произвольные данные от ML-сервиса: confidence, источники ответа и т.п.
    meta: Mapped[dict | None] = mapped_column("metadata", JSONType, nullable=True)

    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["TicketEvent"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketEvent.created_at",
        lazy="selectin",
    )
    # Одна оценка на обращение: пользователь ставит её после закрытия.
    feedback: Mapped["TicketFeedback | None"] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )


class TicketEvent(Base):
    """История изменений обращения — кто и когда перевёл его в новый статус."""

    __tablename__ = "ticket_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True, nullable=False
    )

    from_status: Mapped[TicketStatus | None] = mapped_column(
        Enum(TicketStatus, name="ticket_status", native_enum=False, length=32), nullable=True
    )
    to_status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus, name="ticket_status", native_enum=False, length=32), nullable=False
    )
    actor: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type", native_enum=False, length=32),
        default=ActorType.SYSTEM,
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped[Ticket] = relationship(back_populates="events")


class TicketFeedback(TimestampMixin, Base):
    """Оценка обращения пользователем: звёзды 1-5 и комментарий."""

    __tablename__ = "ticket_feedback"
    __table_args__ = (
        CheckConstraint("score >= 1 AND score <= 5", name="score_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # unique: одно обращение — одна оценка, повторный POST перезаписывает её.
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    ticket: Mapped[Ticket] = relationship(back_populates="feedback")
