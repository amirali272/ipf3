"""connected IPs and subscription apps

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-14 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('xray_node_state', sa.Column('online_ips', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))
    op.create_table(
        'vpn_user_apps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('user_agent', sa.String(length=256), nullable=False),
        sa.Column('app', sa.String(length=64), nullable=False),
        sa.Column('version', sa.String(length=32), nullable=False),
        sa.Column('last_ip', sa.String(length=64), nullable=False),
        sa.Column('first_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('fetches', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['vpn_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'user_agent', name='uq_vpn_user_apps_user_ua'),
    )
    op.create_index(op.f('ix_vpn_user_apps_user_id'), 'vpn_user_apps', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_vpn_user_apps_user_id'), table_name='vpn_user_apps')
    op.drop_table('vpn_user_apps')
    op.drop_column('xray_node_state', 'online_ips')
