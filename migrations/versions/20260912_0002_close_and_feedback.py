"""rename completed -> closed, add ticket_feedback

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Статусы хранятся как имена членов перечисления (VARCHAR), поэтому достаточно UPDATE.
    op.execute("UPDATE tickets SET status = 'CLOSED' WHERE status = 'COMPLETED'")
    op.execute("UPDATE ticket_events SET to_status = 'CLOSED' WHERE to_status = 'COMPLETED'")
    op.execute("UPDATE ticket_events SET from_status = 'CLOSED' WHERE from_status = 'COMPLETED'")

    op.create_table(
        "ticket_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("score >= 1 AND score <= 5", name=op.f("ck_ticket_feedback_score_range")),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("fk_ticket_feedback_ticket_id_tickets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_feedback")),
        sa.UniqueConstraint("ticket_id", name=op.f("uq_ticket_feedback_ticket_id")),
    )


def downgrade() -> None:
    op.drop_table("ticket_feedback")
    op.execute("UPDATE tickets SET status = 'COMPLETED' WHERE status = 'CLOSED'")
    op.execute("UPDATE ticket_events SET to_status = 'COMPLETED' WHERE to_status = 'CLOSED'")
    op.execute("UPDATE ticket_events SET from_status = 'COMPLETED' WHERE from_status = 'CLOSED'")
