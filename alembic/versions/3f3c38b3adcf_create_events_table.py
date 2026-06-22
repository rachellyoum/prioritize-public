"""create_events_table

Revision ID: 3f3c38b3adcf
Revises: 728ce7c03e17
Create Date: 2025-10-30 11:48:39.514248

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '3f3c38b3adcf'
down_revision: Union[str, Sequence[str], None] = 'a3435daf0ab3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create events table for analytics tracking."""
    op.create_table(
        'events',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('when', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True)
    )
    
    # Indexes for fast queries
    op.create_index('ix_events_when', 'events', ['when'])
    op.create_index('ix_events_source', 'events', ['source'])
    op.create_index('ix_events_type', 'events', ['type'])
    op.create_index('ix_events_user_id', 'events', ['user_id'])
    op.create_index('ix_events_when_user', 'events', ['when', 'user_id'])


def downgrade() -> None:
    """Drop events table."""
    op.drop_table('events')