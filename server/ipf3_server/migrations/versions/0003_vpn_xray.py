"""vpn xray

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13 16:42:19.585015
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('vpn_users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('uuid', sa.String(length=36), nullable=False),
    sa.Column('password', sa.String(length=64), nullable=False),
    sa.Column('sub_token', sa.String(length=64), nullable=False),
    sa.Column('data_limit', sa.BigInteger(), nullable=False),
    sa.Column('used_up', sa.BigInteger(), nullable=False),
    sa.Column('used_down', sa.BigInteger(), nullable=False),
    sa.Column('lifetime_used', sa.BigInteger(), nullable=False),
    sa.Column('expire_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('inbound_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_online_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('traffic_reset_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vpn_users_sub_token'), 'vpn_users', ['sub_token'], unique=True)
    op.create_index(op.f('ix_vpn_users_username'), 'vpn_users', ['username'], unique=True)
    op.create_table('vpn_user_traffic_daily',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('up', sa.BigInteger(), nullable=False),
    sa.Column('down', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['vpn_users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'day')
    )
    op.create_table('xray_inbounds',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=False),
    sa.Column('remark', sa.String(length=128), nullable=False),
    sa.Column('protocol', sa.String(length=16), nullable=False),
    sa.Column('port', sa.Integer(), nullable=False),
    sa.Column('listen', sa.String(length=64), nullable=False),
    sa.Column('network', sa.String(length=16), nullable=False),
    sa.Column('security', sa.String(length=16), nullable=False),
    sa.Column('address', sa.String(length=255), nullable=False),
    sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('agent_id', 'port', name='uq_xray_inbounds_agent_port')
    )
    op.create_table('xray_node_state',
    sa.Column('agent_id', sa.String(length=36), nullable=False),
    sa.Column('applied_hash', sa.String(length=64), nullable=True),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('xray_version', sa.String(length=64), nullable=True),
    sa.Column('running', sa.Boolean(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('online_users', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('agent_id')
    )


def downgrade() -> None:
    op.drop_table('xray_node_state')
    op.drop_table('xray_inbounds')
    op.drop_table('vpn_user_traffic_daily')
    op.drop_index(op.f('ix_vpn_users_username'), table_name='vpn_users')
    op.drop_index(op.f('ix_vpn_users_sub_token'), table_name='vpn_users')
    op.drop_table('vpn_users')
