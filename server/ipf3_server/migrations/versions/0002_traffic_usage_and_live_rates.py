"""traffic usage and live rates

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13 15:43:06.415981
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('live_rates',
    sa.Column('agent_id', sa.String(length=36), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('rx_bps', sa.Float(), nullable=False),
    sa.Column('tx_bps', sa.Float(), nullable=False),
    sa.Column('interfaces', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('agent_id'),
    prefixes=['UNLOGGED']
    )
    op.create_table('traffic_daily',
    sa.Column('agent_id', sa.String(length=36), nullable=False),
    sa.Column('iface', sa.String(length=64), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('rx_bytes', sa.BigInteger(), nullable=False),
    sa.Column('tx_bytes', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('agent_id', 'iface', 'day')
    )
    op.add_column('interface_samples', sa.Column('rx_bytes', sa.BigInteger(), nullable=True))
    op.add_column('interface_samples', sa.Column('tx_bytes', sa.BigInteger(), nullable=True))
    op.add_column('interface_samples', sa.Column('primary', sa.Boolean(), nullable=True))
    op.add_column('metric_samples', sa.Column('rx_bytes', sa.BigInteger(), nullable=True))
    op.add_column('metric_samples', sa.Column('tx_bytes', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('metric_samples', 'tx_bytes')
    op.drop_column('metric_samples', 'rx_bytes')
    op.drop_column('interface_samples', 'primary')
    op.drop_column('interface_samples', 'tx_bytes')
    op.drop_column('interface_samples', 'rx_bytes')
    op.drop_table('traffic_daily')
    op.drop_table('live_rates')
