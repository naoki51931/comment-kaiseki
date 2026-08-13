"""remove duplicate professional hash constraint

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""
from collections.abc import Sequence

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "professional_game_fingerprints_normalized_hash_key",
        "professional_game_fingerprints",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "professional_game_fingerprints_normalized_hash_key",
        "professional_game_fingerprints",
        ["normalized_hash"],
    )
