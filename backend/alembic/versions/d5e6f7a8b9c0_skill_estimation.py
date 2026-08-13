"""add skill estimation data

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analysis_results", sa.Column("pre_move_variations", sa.JSON(), nullable=True))
    op.add_column("analysis_results", sa.Column("best_evaluation_user", sa.Integer(), nullable=True))
    op.add_column("analysis_results", sa.Column("best_mate_in_user", sa.Integer(), nullable=True))
    op.add_column("analysis_results", sa.Column("mate_in_user", sa.Integer(), nullable=True))
    op.create_table(
        "game_skill_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("played_at", sa.Date(), nullable=False),
        sa.Column("estimated_rating", sa.Integer(), nullable=False),
        sa.Column("estimated_rank", sa.String(20), nullable=False),
        sa.Column("average_eval_loss", sa.Integer(), nullable=False),
        sa.Column("best_move_match_rate", sa.Integer(), nullable=False),
        sa.Column("top3_match_rate", sa.Integer(), nullable=False),
        sa.Column("opening_score", sa.Integer(), nullable=False),
        sa.Column("middlegame_score", sa.Integer(), nullable=False),
        sa.Column("endgame_score", sa.Integer(), nullable=False),
        sa.Column("blunder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("major_blunder_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mate_opportunities", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mate_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mate_missed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mate_events", sa.JSON(), nullable=False),
        sa.Column("winning_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winning_positions_converted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winning_position_drops", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recovery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("analyzed_move_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_game_skill_analyses_user_id", "game_skill_analyses", ["user_id"])
    op.create_index("ix_game_skill_analyses_game_id", "game_skill_analyses", ["game_id"], unique=True)
    op.create_index("ix_game_skill_analyses_played_at", "game_skill_analyses", ["played_at"])
    op.create_index("ix_game_skill_user_played", "game_skill_analyses", ["user_id", "played_at"])


def downgrade() -> None:
    op.drop_table("game_skill_analyses")
    op.drop_column("analysis_results", "mate_in_user")
    op.drop_column("analysis_results", "best_mate_in_user")
    op.drop_column("analysis_results", "best_evaluation_user")
    op.drop_column("analysis_results", "pre_move_variations")
