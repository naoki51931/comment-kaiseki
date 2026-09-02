"""add permanent access codes

Revision ID: f8a9b0c1d2e3
Revises: e6f7a8b9c0d1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "access_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_access_codes_code"), "access_codes", ["code"], unique=True)
    op.create_index(op.f("ix_access_codes_is_active"), "access_codes", ["is_active"], unique=False)
    op.create_table(
        "access_code_redemptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("access_code_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["access_code_id"], ["access_codes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_access_code_redemptions_access_code_id"), "access_code_redemptions", ["access_code_id"], unique=False)
    op.create_index(op.f("ix_access_code_redemptions_user_id"), "access_code_redemptions", ["user_id"], unique=True)
    access_codes = sa.table(
        "access_codes",
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(access_codes, [
        {"code": "サポートホーム", "description": "永久無料サポートコード", "is_active": True},
        {"code": "般若", "description": "永久無料サポートコード", "is_active": True},
    ])


def downgrade() -> None:
    op.drop_index(op.f("ix_access_code_redemptions_user_id"), table_name="access_code_redemptions")
    op.drop_index(op.f("ix_access_code_redemptions_access_code_id"), table_name="access_code_redemptions")
    op.drop_table("access_code_redemptions")
    op.drop_index(op.f("ix_access_codes_is_active"), table_name="access_codes")
    op.drop_index(op.f("ix_access_codes_code"), table_name="access_codes")
    op.drop_table("access_codes")
