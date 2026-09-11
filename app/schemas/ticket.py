import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ActorType, EscalationReason, SupportLine, TicketStatus

T = TypeVar("T")


class TicketCreate(BaseModel):
    """Тело запроса на создание обращения (вызывается фронтом из чата)."""

    thread_id: str = Field(max_length=128, description="ID диалога в ML-сервисе (LangGraph thread_id)")
    question: str = Field(min_length=1, description="Текст обращения пользователя")
    user_id: str | None = Field(default=None, max_length=128)
    subject: str | None = Field(default=None, max_length=255)
    channel: str = Field(default="web", max_length=32)
    support_line: SupportLine | None = Field(
        default=None, description="Линия поддержки, если ML уже классифицировал обращение"
    )
    status: TicketStatus = Field(default=TicketStatus.CREATED)
    metadata: dict | None = Field(default=None, description="Произвольные данные от ML-сервиса")


class TicketUpdate(BaseModel):
    """Частичное обновление обращения. Передаются только изменяемые поля."""

    subject: str | None = Field(default=None, max_length=255)
    support_line: SupportLine | None = None
    summary: str | None = None
    resolution: str | None = None
    assignee: str | None = Field(default=None, max_length=128)
    metadata: dict | None = None


class TicketStatusUpdate(BaseModel):
    """Явная смена статуса обращения."""

    status: TicketStatus
    actor: ActorType = ActorType.SYSTEM
    comment: str | None = None
    resolution: str | None = Field(
        default=None, description="Итог обработки, имеет смысл при переводе в completed"
    )


class TicketEscalate(BaseModel):
    """Вызов сотрудника: обращение переводится в статус «в работе у поддержки»."""

    reason: EscalationReason = EscalationReason.USER_REQUESTED
    support_line: SupportLine | None = Field(
        default=None, description="Линия поддержки; если не передана — остаётся текущая"
    )
    summary: str | None = Field(default=None, description="Саммари диалога для оператора")
    assignee: str | None = Field(default=None, max_length=128)
    comment: str | None = None


class TicketEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_status: TicketStatus | None
    to_status: TicketStatus
    actor: ActorType
    comment: str | None
    created_at: datetime


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: str
    user_id: str | None
    channel: str
    subject: str | None
    question: str
    status: TicketStatus
    support_line: SupportLine | None
    escalation_reason: EscalationReason | None
    summary: str | None
    resolution: str | None
    assignee: str | None
    metadata: dict | None = Field(default=None, validation_alias="meta")
    escalated_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TicketDetail(TicketRead):
    events: list[TicketEventRead] = Field(default_factory=list)


class Page(BaseModel, Generic[T]):
    """Постраничный ответ со списком элементов."""

    items: list[T]
    total: int
    limit: int
    offset: int
