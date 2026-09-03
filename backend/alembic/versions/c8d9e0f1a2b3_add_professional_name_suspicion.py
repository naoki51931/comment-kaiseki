"""add professional player name suspicion

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
"""

from alembic import op
import sqlalchemy as sa

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("games", sa.Column("professional_name_suspected", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("games", sa.Column("professional_name_matches", sa.JSON(), nullable=False, server_default="[]"))
    op.create_index("ix_games_professional_name_suspected", "games", ["professional_name_suspected"])


def downgrade() -> None:
    op.drop_index("ix_games_professional_name_suspected", table_name="games")
    op.drop_column("games", "professional_name_matches")
    op.drop_column("games", "professional_name_suspected")
