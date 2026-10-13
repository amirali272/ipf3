"""inbound traffic

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13 20:53:44.662118
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('xray_inbounds', sa.Column('up', sa.BigInteger(), server_default='0', nullable=False))
    op.add_column('xray_inbounds', sa.Column('down', sa.BigInteger(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('xray_inbounds', 'down')
    op.drop_column('xray_inbounds', 'up')
