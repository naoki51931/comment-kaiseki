"""add refresh token admin authentication

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("admin_authenticated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.alter_column("refresh_tokens", "admin_authenticated", server_default=None)


def downgrade() -> None:
    op.drop_column("refresh_tokens", "admin_authenticated")
