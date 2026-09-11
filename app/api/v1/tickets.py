import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import TicketServiceDep
from app.core.enums import SupportLine, TicketStatus
from app.schemas.ticket import (
    FeedbackCreate,
    FeedbackRead,
    Page,
    TicketClose,
    TicketCreate,
    TicketDetail,
    TicketEscalate,
    TicketEventRead,
    TicketRead,
    TicketStatusUpdate,
    TicketUpdate,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post(
    "",
    response_model=TicketRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать обращение",
)
async def create_ticket(payload: TicketCreate, service: TicketServiceDep) -> TicketRead:
    """Вызывается фронтом из чата при первом запросе пользователя."""
    ticket = await service.create(payload)
    return TicketRead.model_validate(ticket)


@router.get("", response_model=Page[TicketRead], summary="Список обращений")
async def list_tickets(
    service: TicketServiceDep,
    status_filter: Annotated[TicketStatus | None, Query(alias="status")] = None,
    support_line: SupportLine | None = None,
    thread_id: str | None = None,
    user_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[TicketRead]:
    items, total = await service.list(
        status=status_filter,
        support_line=support_line,
        thread_id=thread_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return Page[TicketRead](
        items=[TicketRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{ticket_id}", response_model=TicketDetail, summary="Обращение с историей статусов")
async def get_ticket(ticket_id: uuid.UUID, service: TicketServiceDep) -> TicketDetail:
    ticket = await service.get(ticket_id)
    return TicketDetail.model_validate(ticket)


@router.patch("/{ticket_id}", response_model=TicketRead, summary="Обновить поля обращения")
async def update_ticket(
    ticket_id: uuid.UUID, payload: TicketUpdate, service: TicketServiceDep
) -> TicketRead:
    ticket = await service.update(ticket_id, payload)
    return TicketRead.model_validate(ticket)


@router.post("/{ticket_id}/status", response_model=TicketRead, summary="Сменить статус обращения")
async def change_status(
    ticket_id: uuid.UUID, payload: TicketStatusUpdate, service: TicketServiceDep
) -> TicketRead:
    """Недопустимый переход (например из closed) отклоняется с кодом 409."""
    ticket = await service.change_status(ticket_id, payload)
    return TicketRead.model_validate(ticket)


@router.post(
    "/{ticket_id}/escalate",
    response_model=TicketRead,
    summary="Вызов сотрудника (эскалация на поддержку)",
)
async def escalate_ticket(
    ticket_id: uuid.UUID, payload: TicketEscalate, service: TicketServiceDep
) -> TicketRead:
    """Переводит обращение в статус in_support и сохраняет саммари диалога для оператора."""
    ticket = await service.escalate(ticket_id, payload)
    return TicketRead.model_validate(ticket)


@router.post("/{ticket_id}/close", response_model=TicketRead, summary="Закрыть обращение")
async def close_ticket(
    ticket_id: uuid.UUID, payload: TicketClose, service: TicketServiceDep
) -> TicketRead:
    """Переводит обращение в терминальный статус `closed`.

    После успешного ответа фронт показывает форму оценки (звёзды 1-5 + комментарий).
    """
    ticket = await service.close(ticket_id, payload)
    return TicketRead.model_validate(ticket)


@router.post(
    "/{ticket_id}/feedback",
    response_model=FeedbackRead,
    status_code=status.HTTP_201_CREATED,
    summary="Оценить обращение (1-5 звёзд + комментарий)",
)
async def set_feedback(
    ticket_id: uuid.UUID, payload: FeedbackCreate, service: TicketServiceDep
) -> FeedbackRead:
    """Доступно только для закрытого обращения, иначе 409. Повторный вызов перезаписывает оценку."""
    feedback = await service.set_feedback(ticket_id, payload)
    return FeedbackRead.model_validate(feedback)


@router.get(
    "/{ticket_id}/feedback",
    response_model=FeedbackRead,
    summary="Получить оценку обращения",
)
async def get_feedback(ticket_id: uuid.UUID, service: TicketServiceDep) -> FeedbackRead:
    feedback = await service.get_feedback(ticket_id)
    return FeedbackRead.model_validate(feedback)


@router.get(
    "/{ticket_id}/events",
    response_model=list[TicketEventRead],
    summary="История изменений обращения",
)
async def list_events(ticket_id: uuid.UUID, service: TicketServiceDep) -> list[TicketEventRead]:
    ticket = await service.get(ticket_id)
    return [TicketEventRead.model_validate(event) for event in ticket.events]


@router.delete(
    "/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить обращение"
)
async def delete_ticket(ticket_id: uuid.UUID, service: TicketServiceDep) -> None:
    await service.delete(ticket_id)
