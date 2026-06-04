"""add chat attachments and dm read state

Revision ID: a2d4e6f8b9c1
Revises: a1b2c3d4e5f6
Create Date: 2026-06-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2d4e6f8b9c1'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('attachment_url', sa.Text(), nullable=True))
    op.add_column('messages', sa.Column('attachment_name', sa.String(), nullable=True))
    op.add_column('messages', sa.Column('attachment_type', sa.String(), nullable=True))

    op.add_column('message_read_states', sa.Column('peer_user_id', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_message_read_states_peer_user_id'), 'message_read_states', ['peer_user_id'], unique=False)
    op.create_foreign_key('fk_message_read_states_peer_user_id_users', 'message_read_states', 'users', ['peer_user_id'], ['id'])
    op.create_index(
        'ix_message_read_states_unique_dm',
        'message_read_states',
        ['user_id', 'peer_user_id'],
        unique=True,
        postgresql_where=sa.text('course_id IS NULL AND peer_user_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_message_read_states_unique_dm', table_name='message_read_states')
    op.drop_constraint('fk_message_read_states_peer_user_id_users', 'message_read_states', type_='foreignkey')
    op.drop_index(op.f('ix_message_read_states_peer_user_id'), table_name='message_read_states')
    op.drop_column('message_read_states', 'peer_user_id')

    op.drop_column('messages', 'attachment_type')
    op.drop_column('messages', 'attachment_name')
    op.drop_column('messages', 'attachment_url')
