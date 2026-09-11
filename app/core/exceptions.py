from fastapi import HTTPException, status

from app.core.enums import TicketStatus


class TicketNotFoundError(HTTPException):
    def __init__(self, ticket_id: object) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Обращение {ticket_id} не найдено",
        )


class InvalidStatusTransitionError(HTTPException):
    def __init__(self, current: TicketStatus, target: TicketStatus) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Недопустимый переход статуса: {current.value} -> {target.value}",
        )
