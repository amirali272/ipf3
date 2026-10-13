"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-13 14:17:10.010487
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('agents',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('hostname', sa.String(length=255), nullable=False),
    sa.Column('os_name', sa.String(length=255), nullable=False),
    sa.Column('kernel', sa.String(length=255), nullable=False),
    sa.Column('agent_version', sa.String(length=32), nullable=False),
    sa.Column('cpu_count', sa.Integer(), nullable=True),
    sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('remote_addr', sa.String(length=64), nullable=True),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('disabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('admin', 'operator', 'viewer', name='user_role'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('failed_logins', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('session_version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('agent_inventory',
    sa.Column('agent_id', sa.String(length=36), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('interfaces', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('routes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('routes6', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('connections', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('dns', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('system', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('agent_id')
    )
    op.create_table('alert_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('metric', sa.String(length=64), nullable=False),
    sa.Column('operator', sa.String(length=4), nullable=False),
    sa.Column('threshold', sa.Float(), nullable=False),
    sa.Column('for_seconds', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=True),
    sa.Column('iface', sa.String(length=64), nullable=True),
    sa.Column('target', sa.String(length=255), nullable=True),
    sa.Column('severity', sa.Enum('info', 'warning', 'critical', name='severity'), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('webhook_url', sa.String(length=1024), nullable=True),
    sa.Column('email_to', sa.String(length=1024), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target', sa.String(length=255), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_log_ts', 'audit_log', ['ts'], unique=False)
    op.create_table('enrollment_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=128), nullable=False),
    sa.Column('note', sa.String(length=255), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('agent_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_table('interface_samples',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('iface', sa.String(length=64), nullable=False),
    sa.Column('rx_bps', sa.Float(), nullable=False),
    sa.Column('tx_bps', sa.Float(), nullable=False),
    sa.Column('rx_pps', sa.Float(), nullable=False),
    sa.Column('tx_pps', sa.Float(), nullable=False),
    sa.Column('rx_errs', sa.BigInteger(), nullable=False),
    sa.Column('tx_errs', sa.BigInteger(), nullable=False),
    sa.Column('rx_drops', sa.BigInteger(), nullable=False),
    sa.Column('tx_drops', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_interface_samples_agent_iface_ts', 'interface_samples', ['agent_id', 'iface', 'ts'], unique=False)
    op.create_table('metric_samples',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=False),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('cpu_percent', sa.Float(), nullable=True),
    sa.Column('load1', sa.Float(), nullable=True),
    sa.Column('load5', sa.Float(), nullable=True),
    sa.Column('load15', sa.Float(), nullable=True),
    sa.Column('mem_total', sa.BigInteger(), nullable=True),
    sa.Column('mem_used', sa.BigInteger(), nullable=True),
    sa.Column('mem_percent', sa.Float(), nullable=True),
    sa.Column('swap_percent', sa.Float(), nullable=True),
    sa.Column('disk_percent', sa.Float(), nullable=True),
    sa.Column('uptime_seconds', sa.BigInteger(), nullable=True),
    sa.Column('tcp_established', sa.Integer(), nullable=True),
    sa.Column('tcp_listen', sa.Integer(), nullable=True),
    sa.Column('tcp_time_wait', sa.Integer(), nullable=True),
    sa.Column('udp_sockets', sa.Integer(), nullable=True),
    sa.Column('tcp_retrans_segs', sa.BigInteger(), nullable=True),
    sa.Column('rx_bps', sa.Float(), nullable=True),
    sa.Column('tx_bps', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_metric_samples_agent_ts', 'metric_samples', ['agent_id', 'ts'], unique=False)
    op.create_table('schedules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=False),
    sa.Column('type', sa.Enum('iperf3', 'ping', 'traceroute', 'mtr', 'dns', name='job_type'), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('interval_seconds', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('alert_events',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('rule_id', sa.Integer(), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=True),
    sa.Column('state', sa.Enum('firing', 'resolved', name='alert_state'), nullable=False),
    sa.Column('severity', sa.Enum('info', 'warning', 'critical', name='severity'), nullable=False),
    sa.Column('value', sa.Float(), nullable=True),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acknowledged_by', sa.Integer(), nullable=True),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_alert_events_rule_agent_state', 'alert_events', ['rule_id', 'agent_id', 'state'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=False),
    sa.Column('type', sa.Enum('iperf3', 'ping', 'traceroute', 'mtr', 'dns', name='job_type'), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('target', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('queued', 'running', 'completed', 'failed', 'cancelled', 'expired', name='job_status'), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('schedule_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('raw', sa.Text(), nullable=True),
    sa.Column('bps', sa.Float(), nullable=True),
    sa.Column('rtt_avg_ms', sa.Float(), nullable=True),
    sa.Column('loss_percent', sa.Float(), nullable=True),
    sa.Column('jitter_ms', sa.Float(), nullable=True),
    sa.Column('retransmits', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['schedule_id'], ['schedules.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_agent_status', 'jobs', ['agent_id', 'status'], unique=False)
    op.create_index('ix_jobs_schedule_created', 'jobs', ['schedule_id', 'created_at'], unique=False)
    op.create_index('ix_jobs_type_created', 'jobs', ['type', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_jobs_type_created', table_name='jobs')
    op.drop_index('ix_jobs_schedule_created', table_name='jobs')
    op.drop_index('ix_jobs_agent_status', table_name='jobs')
    op.drop_table('jobs')
    op.drop_index('ix_alert_events_rule_agent_state', table_name='alert_events')
    op.drop_table('alert_events')
    op.drop_table('schedules')
    op.drop_index('ix_metric_samples_agent_ts', table_name='metric_samples')
    op.drop_table('metric_samples')
    op.drop_index('ix_interface_samples_agent_iface_ts', table_name='interface_samples')
    op.drop_table('interface_samples')
    op.drop_table('enrollment_tokens')
    op.drop_index('ix_audit_log_ts', table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_table('alert_rules')
    op.drop_table('agent_inventory')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
    op.drop_table('agents')
    for enum_name in ("alert_state", "severity", "job_status", "job_type", "user_role"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
