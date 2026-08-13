"""add AI comments and correction feedback

Revision ID: e5f7a9b2c304
Revises: d4e6f8a1b203
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "e5f7a9b2c304"
down_revision: str | None = "d4e6f8a1b203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table("ai_comments", sa.Column("id", sa.Integer(), nullable=False), sa.Column("critical_position_id", sa.Integer(), nullable=False), sa.Column("move_number", sa.Integer(), nullable=False), sa.Column("generated_text", sa.Text(), nullable=False), sa.Column("current_text", sa.Text(), nullable=False), sa.Column("source_answer_ids", sa.JSON(), nullable=False), sa.Column("model_version", sa.String(100), nullable=False), sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["critical_position_id"], ["critical_positions.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"))
    op.create_index(op.f("ix_ai_comments_critical_position_id"), "ai_comments", ["critical_position_id"], unique=True)
    op.create_index(op.f("ix_ai_comments_move_number"), "ai_comments", ["move_number"], unique=False)
    op.create_table("ai_comment_feedback", sa.Column("id", sa.Integer(), nullable=False), sa.Column("ai_comment_id", sa.Integer(), nullable=False), sa.Column("user_id", sa.Integer(), nullable=False), sa.Column("move_number", sa.Integer(), nullable=False), sa.Column("before_text", sa.Text(), nullable=False), sa.Column("after_text", sa.Text(), nullable=False), sa.Column("diff", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["ai_comment_id"], ["ai_comments.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_index(op.f("ix_ai_comment_feedback_ai_comment_id"), "ai_comment_feedback", ["ai_comment_id"], unique=False)
    op.create_index(op.f("ix_ai_comment_feedback_user_id"), "ai_comment_feedback", ["user_id"], unique=False)
    op.create_index(op.f("ix_ai_comment_feedback_move_number"), "ai_comment_feedback", ["move_number"], unique=False)

def downgrade() -> None:
    op.drop_table("ai_comment_feedback")
    op.drop_table("ai_comments")
