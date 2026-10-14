"""wireguard

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-14 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'wg_inbounds',
        sa.Column('agent_id', sa.String(length=36), nullable=False),
        sa.Column('remark', sa.String(length=128), nullable=False),
        sa.Column('listen_port', sa.Integer(), nullable=False),
        sa.Column('network', sa.String(length=64), nullable=False),
        sa.Column('address', sa.String(length=255), nullable=False),
        sa.Column('dns', sa.String(length=255), nullable=False),
        sa.Column('mtu', sa.Integer(), nullable=False),
        sa.Column('persistent_keepalive', sa.Integer(), nullable=False),
        sa.Column('egress_iface', sa.String(length=32), nullable=False),
        sa.Column('private_key', sa.String(length=64), nullable=False),
        sa.Column('public_key', sa.String(length=64), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('agent_id'),
    )
    op.create_table(
        'wg_peers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('address', sa.String(length=64), nullable=False),
        sa.Column('private_key', sa.String(length=64), nullable=False),
        sa.Column('public_key', sa.String(length=64), nullable=False),
        sa.Column('preshared_key', sa.String(length=64), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('up', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('down', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('last_handshake_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['wg_inbounds.agent_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['vpn_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('agent_id', 'user_id', name='uq_wg_peers_agent_user'),
        sa.UniqueConstraint('agent_id', 'address', name='uq_wg_peers_agent_address'),
    )
    op.create_index(op.f('ix_wg_peers_user_id'), 'wg_peers', ['user_id'], unique=False)
    op.create_table(
        'wg_node_state',
        sa.Column('agent_id', sa.String(length=36), nullable=False),
        sa.Column('applied_hash', sa.String(length=64), nullable=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('running', sa.Boolean(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('agent_id'),
    )


def downgrade() -> None:
    op.drop_table('wg_node_state')
    op.drop_index(op.f('ix_wg_peers_user_id'), table_name='wg_peers')
    op.drop_table('wg_peers')
    op.drop_table('wg_inbounds')
