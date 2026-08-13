"""add game visibility

Revision ID: a1b2c3d4e5f6
Revises: f7b8c9d0e1a2
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f7b8c9d0e1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "games",
        sa.Column("is_public", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index("ix_games_is_public", "games", ["is_public"], unique=False)
    op.alter_column("games", "is_public", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_games_is_public", table_name="games")
    op.drop_column("games", "is_public")
