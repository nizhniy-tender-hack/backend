"""add training_examples

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-13
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_examples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("support_line", sa.String(length=32), nullable=True),
        sa.Column("score", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 1 AND score <= 5)",
            name=op.f("ck_training_examples_score_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_training_examples")),
    )
    op.create_index(
        op.f("ix_training_examples_ticket_id"), "training_examples", ["ticket_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_training_examples_ticket_id"), table_name="training_examples")
    op.drop_table("training_examples")
