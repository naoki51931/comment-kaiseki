"""add professional game fingerprints

Revision ID: f7b8c9d0e1a2
Revises: e5f7a9b2c304
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "f7b8c9d0e1a2"
down_revision: str | None = "e5f7a9b2c304"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "professional_game_fingerprints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("normalized_hash", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("source_reference", sa.String(length=512), nullable=True),
        sa.Column("event_name", sa.String(length=255), nullable=True),
        sa.Column("sente_name", sa.String(length=255), nullable=True),
        sa.Column("gote_name", sa.String(length=255), nullable=True),
        sa.Column("played_at", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("normalized_hash"),
    )
    op.create_index("ix_professional_game_fingerprints_normalized_hash", "professional_game_fingerprints", ["normalized_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_professional_game_fingerprints_normalized_hash", table_name="professional_game_fingerprints")
    op.drop_table("professional_game_fingerprints")
