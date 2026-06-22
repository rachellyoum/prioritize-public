"""add_user_tier

Revision ID: a3435daf0ab3
Revises: 728ce7c03e17
Create Date: 2025-10-29 08:26:24.056661

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3435daf0ab3'
down_revision: Union[str, Sequence[str], None] = '728ce7c03e17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add tier column with default value of 1
    op.add_column('users', sa.Column('tier', sa.Integer(), nullable=False, server_default='1'))
    
    # Add check constraint to ensure tier >= 1
    op.create_check_constraint('tier_minimum', 'users', 'tier >= 1')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('tier_minimum', 'users', type_='check')
    op.drop_column('users', 'tier')

