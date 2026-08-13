"""add analysis job outbox

Revision ID: 9b7d4e21c8a0
Revises: 7105aa2c5092
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "9b7d4e21c8a0"
down_revision: str | None = "7105aa2c5092"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_job_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analysis_job_outbox_game_id"), "analysis_job_outbox", ["game_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_analysis_job_outbox_game_id"), table_name="analysis_job_outbox")
    op.drop_table("analysis_job_outbox")
