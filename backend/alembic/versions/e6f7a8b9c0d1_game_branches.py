"""add saved game branches

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "game_branches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("base_move_number", sa.Integer(), nullable=False),
        sa.Column("usi_moves", sa.JSON(), nullable=False),
        sa.Column("japanese_moves", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("game_id", "name", name="uq_game_branch_name"),
    )
    op.create_index("ix_game_branches_game_id", "game_branches", ["game_id"])
    op.create_index("ix_game_branches_user_id", "game_branches", ["user_id"])

def downgrade() -> None:
    op.drop_table("game_branches")
