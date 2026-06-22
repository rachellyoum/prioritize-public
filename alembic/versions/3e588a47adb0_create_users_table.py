"""create users table

Revision ID: 3e588a47adb0
Revises: 
Create Date: 2025-09-26 01:45:57.067024

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3e588a47adb0'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create users table with authentication fields.
    
    Changes from original schema:
    - Added 'id' as auto-increment primary key (was 'name' before)
    - Added 'email' field with unique constraint
    - Added 'hashed_password' field for secure password storage
    - Added indexes on 'name' and 'email' for query performance
    """
    op.create_table('users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False), # Primary key
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('email')
    )
    # Create indexes for faster lookups by email and name
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_name'), 'users', ['name'], unique=True)

def downgrade() -> None:
    """
    Rollback: Drop the users table and its indexes.
    """
    op.drop_index(op.f('ix_users_name'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')

