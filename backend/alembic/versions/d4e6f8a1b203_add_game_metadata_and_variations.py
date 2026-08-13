"""add game metadata and engine variations

Revision ID: d4e6f8a1b203
Revises: c3a51d82f904
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "d4e6f8a1b203"
down_revision: str | None = "c3a51d82f904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("games", sa.Column("event_name", sa.String(length=255), nullable=True))
    op.add_column("games", sa.Column("sente_name", sa.String(length=255), nullable=True))
    op.add_column("games", sa.Column("gote_name", sa.String(length=255), nullable=True))
    op.add_column("analysis_results", sa.Column("variations", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_results", "variations")
    op.drop_column("games", "gote_name")
    op.drop_column("games", "sente_name")
    op.drop_column("games", "event_name")
