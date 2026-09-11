"""initial tickets schema

Revision ID: 0001
Revises:
Create Date: 2026-09-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ticket_status = sa.Enum(
    "CREATED",
    "IN_PROGRESS",
    "IN_SUPPORT",
    "COMPLETED",
    name="ticket_status",
    native_enum=False,
    length=32,
)
support_line = sa.Enum("FIRST", "SECOND", "THIRD", name="support_line", native_enum=False, length=32)
escalation_reason = sa.Enum(
    "USER_REQUESTED",
    "AGENT_INITIATED",
    "PROFANITY",
    name="escalation_reason",
    native_enum=False,
    length=32,
)
actor_type = sa.Enum(
    "USER", "AGENT", "SPECIALIST", "SYSTEM", name="actor_type", native_enum=False, length=32
)


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", ticket_status, nullable=False),
        sa.Column("support_line", support_line, nullable=True),
        sa.Column("escalation_reason", escalation_reason, nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("assignee", sa.String(length=128), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
    )
    op.create_index(op.f("ix_tickets_thread_id"), "tickets", ["thread_id"])
    op.create_index(op.f("ix_tickets_user_id"), "tickets", ["user_id"])
    op.create_index(op.f("ix_tickets_status"), "tickets", ["status"])
    op.create_index(op.f("ix_tickets_support_line"), "tickets", ["support_line"])
    op.create_index("ix_tickets_status_support_line", "tickets", ["status", "support_line"])
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"])

    op.create_table(
        "ticket_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", ticket_status, nullable=True),
        sa.Column("to_status", ticket_status, nullable=False),
        sa.Column("actor", actor_type, nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticket_id"],
            ["tickets.id"],
            name=op.f("fk_ticket_events_ticket_id_tickets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_events")),
    )
    op.create_index(op.f("ix_ticket_events_ticket_id"), "ticket_events", ["ticket_id"])


def downgrade() -> None:
    op.drop_table("ticket_events")
    op.drop_table("tickets")
