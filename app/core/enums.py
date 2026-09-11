from enum import StrEnum


class TicketStatus(StrEnum):
    """Жизненный цикл обращения."""

    CREATED = "created"  # создана
    IN_PROGRESS = "in_progress"  # в процессе (обрабатывает ИИ-агент)
    IN_SUPPORT = "in_support"  # в работе у поддержки (эскалация на человека)
    CLOSED = "closed"  # закрыта (завершена)


class SupportLine(StrEnum):
    """Линия поддержки, которой адресовано обращение."""

    FIRST = "first"
    SECOND = "second"
    THIRD = "third"


class EscalationReason(StrEnum):
    """Кто инициировал передачу обращения человеку."""

    USER_REQUESTED = "user_requested"  # пользователь нажал «позвать оператора»
    AGENT_INITIATED = "agent_initiated"  # агент сам эскалировал (низкая уверенность / нет ответа в БЗ)
    PROFANITY = "profanity"  # сработал профанити-фильтр


class ActorType(StrEnum):
    """Кто выполнил действие над обращением — для истории статусов."""

    USER = "user"
    AGENT = "agent"
    SPECIALIST = "specialist"
    SYSTEM = "system"


# Разрешённые переходы статусов. Закрытое обращение — терминальное состояние.
ALLOWED_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.CREATED: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.IN_SUPPORT,
        TicketStatus.CLOSED,
    },
    TicketStatus.IN_PROGRESS: {
        TicketStatus.IN_SUPPORT,
        TicketStatus.CLOSED,
    },
    TicketStatus.IN_SUPPORT: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.CLOSED,
    },
    TicketStatus.CLOSED: set(),
}


def is_transition_allowed(current: TicketStatus, target: TicketStatus) -> bool:
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS[current]
