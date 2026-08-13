"""add ai access subscriptions

Revision ID: c3a51d82f904
Revises: 9b7d4e21c8a0
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c3a51d82f904"
down_revision: str | None = "9b7d4e21c8a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_access_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("checkout_session_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ai_access_subscriptions_user_id"), "ai_access_subscriptions", ["user_id"], unique=True)
    op.create_index(op.f("ix_ai_access_subscriptions_checkout_session_id"), "ai_access_subscriptions", ["checkout_session_id"], unique=True)
    op.create_index(op.f("ix_ai_access_subscriptions_stripe_subscription_id"), "ai_access_subscriptions", ["stripe_subscription_id"], unique=True)
    op.create_index(op.f("ix_ai_access_subscriptions_stripe_customer_id"), "ai_access_subscriptions", ["stripe_customer_id"], unique=False)
    op.create_index(op.f("ix_ai_access_subscriptions_status"), "ai_access_subscriptions", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_access_subscriptions_status"), table_name="ai_access_subscriptions")
    op.drop_index(op.f("ix_ai_access_subscriptions_stripe_customer_id"), table_name="ai_access_subscriptions")
    op.drop_index(op.f("ix_ai_access_subscriptions_stripe_subscription_id"), table_name="ai_access_subscriptions")
    op.drop_index(op.f("ix_ai_access_subscriptions_checkout_session_id"), table_name="ai_access_subscriptions")
    op.drop_index(op.f("ix_ai_access_subscriptions_user_id"), table_name="ai_access_subscriptions")
    op.drop_table("ai_access_subscriptions")
