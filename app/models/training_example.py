import uuid

from sqlalchemy import CheckConstraint, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TrainingExample(TimestampMixin, Base):
    """Снимок решённого обращения: вопрос, саммари, история переписки, оценка.

    Не хранится как FK на `tickets` и не удаляется вместе с ним: обращение
    можно удалить (`DELETE /tickets/{id}`), а этот пример — данные для
    будущего анализа/обучения — должен пережить удаление. `ticket_id` здесь
    просто значение для связи и дедупликации (уникален), без внешнего ключа.

    Пишется автоматически сервисом (`TicketService.close`/`set_feedback`),
    отдельной ручки на запись нет: `summary`/`transcript` появляются при
    закрытии, `score` — позже, когда пользователь поставит оценку, если
    вообще поставит. Один и тот же тикет обновляет одну и ту же строку.
    """

    __tablename__ = "training_examples"
    __table_args__ = (
        CheckConstraint("score IS NULL OR (score >= 1 AND score <= 5)", name="score_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(index=True, unique=True, nullable=False)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_line: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # NULL, пока не появится оценка — на момент закрытия её ещё нет.
    score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
