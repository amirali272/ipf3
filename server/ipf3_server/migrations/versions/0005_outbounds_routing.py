"""outbounds and routing rules

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-13 21:20:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'xray_outbounds',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('remark', sa.String(length=128), nullable=False),
        sa.Column('protocol', sa.String(length=16), nullable=False),
        sa.Column('link', sa.Text(), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('agent_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('up', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('down', sa.BigInteger(), server_default='0', nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'xray_routing_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('remark', sa.String(length=128), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('outbound_id', sa.Integer(), nullable=True),
        sa.Column('inbound_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('user_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('domains', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('ips', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('port', sa.String(length=128), nullable=False),
        sa.Column('network', sa.String(length=8), nullable=False),
        sa.Column('protocols', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['outbound_id'], ['xray_outbounds.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_xray_routing_rules_position'), 'xray_routing_rules', ['position'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_xray_routing_rules_position'), table_name='xray_routing_rules')
    op.drop_table('xray_routing_rules')
    op.drop_table('xray_outbounds')
