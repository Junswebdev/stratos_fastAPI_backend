"""add lesson_progress table

Revision ID: f2a1b3c4d5e6
Revises: c7488439efa2
Create Date: 2026-05-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f2a1b3c4d5e6'
down_revision: Union[str, None] = 'c7488439efa2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('lesson_progress',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('student_id', sa.UUID(), nullable=False),
        sa.Column('lesson_id', sa.UUID(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'lesson_id', name='_student_lesson_uc'),
    )
    op.create_index(op.f('ix_lesson_progress_id'), 'lesson_progress', ['id'], unique=False)
    op.create_index(op.f('ix_lesson_progress_lesson_id'), 'lesson_progress', ['lesson_id'], unique=False)
    op.create_index(op.f('ix_lesson_progress_student_id'), 'lesson_progress', ['student_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_lesson_progress_student_id'), table_name='lesson_progress')
    op.drop_index(op.f('ix_lesson_progress_lesson_id'), table_name='lesson_progress')
    op.drop_index(op.f('ix_lesson_progress_id'), table_name='lesson_progress')
    op.drop_table('lesson_progress')
