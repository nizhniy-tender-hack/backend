import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrainingExampleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    question: str
    summary: str | None
    transcript: str | None
    support_line: str | None
    score: int | None
    created_at: datetime
    updated_at: datetime
