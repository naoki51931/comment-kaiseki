"""add Google login identity

Revision ID: b7c8d9e0f1a2
Revises: a9c1e4f2b7d0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a9c1e4f2b7d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_subject", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_users_google_subject"), "users", ["google_subject"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_google_subject"), table_name="users")
    op.drop_column("users", "google_subject")
