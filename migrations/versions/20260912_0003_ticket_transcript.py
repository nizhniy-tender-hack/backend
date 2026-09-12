"""add tickets.transcript

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("transcript", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "transcript")
