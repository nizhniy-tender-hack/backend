import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ActorType, EscalationReason, MessageRole, SupportLine, TicketStatus

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
        default=None, description="Итог обработки, имеет смысл при переводе в closed"
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


class TicketClose(BaseModel):
    """Закрытие обращения: перевод в терминальный статус closed."""

    actor: ActorType = ActorType.USER
    resolution: str | None = Field(default=None, description="Итог обработки обращения")
    comment: str | None = Field(default=None, description="Комментарий к записи в истории")
    transcript: str | None = Field(
        default=None, description="Полный текст диалога, накопленный на фронте к моменту закрытия"
    )


class FeedbackCreate(BaseModel):
    """Оценка обращения пользователем после закрытия: звёзды + комментарий."""

    score: int = Field(ge=1, le=5, description="Оценка от 1 до 5 звёзд")
    comment: str | None = Field(default=None, max_length=4000)


class MessageIn(BaseModel):
    """Реплика диалога, которую фронт присылает при завершении обращения."""

    role: MessageRole
    content: str = Field(min_length=1, max_length=20000)


class TicketComplete(BaseModel):
    """Завершение обращения одним запросом: закрытие + оценка + саммари + все сообщения.

    Заменяет связку `close` + `feedback`: фронт присылает всё, что накопил к
    моменту завершения, одним вызовом.
    """

    actor: ActorType = ActorType.USER
    resolution: str | None = Field(default=None, description="Итог обработки обращения")
    comment: str | None = Field(default=None, description="Комментарий к записи в истории")
    summary: str | None = Field(
        default=None, description="Саммари диалога; не передано — сохранённое не меняется"
    )
    feedback: FeedbackCreate | None = Field(
        default=None, description="Оценка 1-5 и комментарий; не передана — оценка не ставится"
    )
    messages: list[MessageIn] | None = Field(
        default=None,
        max_length=500,
        description="Все сообщения диалога; перезаписывают сохранённые ранее. "
        "Не переданы — сохранённые не меняются",
    )


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    position: int
    role: MessageRole
    content: str
    created_at: datetime


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    score: int
    comment: str | None
    created_at: datetime
    updated_at: datetime


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
    transcript: str | None = None
    metadata: dict | None = Field(default=None, validation_alias="meta")
    escalated_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    feedback: FeedbackRead | None = None


class TicketDetail(TicketRead):
    events: list[TicketEventRead] = Field(default_factory=list)


class Page(BaseModel, Generic[T]):
    """Постраничный ответ со списком элементов."""

    items: list[T]
    total: int
    limit: int
    offset: int
