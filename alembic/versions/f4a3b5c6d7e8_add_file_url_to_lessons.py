"""add file_url to lessons

Revision ID: f4a3b5c6d7e8
Revises: f3a2b4c5d6e7
Create Date: 2026-05-31 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f4a3b5c6d7e8'
down_revision: Union[str, None] = 'f3a2b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('lessons', sa.Column('file_url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('lessons', 'file_url')
