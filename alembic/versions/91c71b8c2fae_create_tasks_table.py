"""create tasks table

Revision ID: 91c71b8c2fae
Revises: 3f3c38b3adcf
Create Date: 2025-11-13 00:14:05.307654

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psql


# revision identifiers, used by Alembic.
revision: str = '91c71b8c2fae'
down_revision: Union[str, Sequence[str], None] = '3f3c38b3adcf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    op.create_table(
        'tasks',
        sa.Column('id', psql.UUID(as_uuid=True), primary_key=True),
        sa.Column('owner_email', sa.String(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('deadline', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('weight_pct', sa.Numeric(5, 2), nullable=False),
        sa.Column('difficulty', sa.Enum('easy', 'medium', 'hard', name='difficulty'), nullable=False),
        sa.Column('estimated_hours', sa.Numeric(6, 2), nullable=False),
        sa.Column('status', sa.String(), server_default='open', nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False)
    )

    # 3. Index tasks.owner_email
    op.create_index('ix_tasks_owner_email', 'tasks', ['owner_email'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_tasks_owner_email', table_name='tasks')
    op.drop_table('tasks')
    sa.Enum(name='difficulty').drop(op.get_bind(), checkfirst=True)
