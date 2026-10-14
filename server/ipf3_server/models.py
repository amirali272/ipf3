from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


TS = DateTime(timezone=True)


class Role(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class JobType(str, enum.Enum):
    iperf3 = "iperf3"
    ping = "ping"
    traceroute = "traceroute"
    mtr = "mtr"
    dns = "dns"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    expired = "expired"


class Severity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class AlertState(str, enum.Enum):
    firing = "firing"
    resolved = "resolved"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"), default=Role.viewer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(TS)
    # Bumped on password change / deactivation to invalidate existing sessions.
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(TS)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    hostname: Mapped[str] = mapped_column(String(255), default="")
    os_name: Mapped[str] = mapped_column(String(255), default="")
    kernel: Mapped[str] = mapped_column(String(255), default="")
    agent_version: Mapped[str] = mapped_column(String(32), default="")
    cpu_count: Mapped[int | None] = mapped_column(Integer)
    capabilities: Mapped[dict] = mapped_column(JSONB, default=dict)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    remote_addr: Mapped[str | None] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(128))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(TS)


class EnrollmentToken(Base):
    __tablename__ = "enrollment_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(TS)
    used_at: Mapped[datetime | None] = mapped_column(TS)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))


class MetricSample(Base):
    __tablename__ = "metric_samples"
    __table_args__ = (Index("ix_metric_samples_agent_ts", "agent_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TS)
    cpu_percent: Mapped[float | None] = mapped_column(Float)
    load1: Mapped[float | None] = mapped_column(Float)
    load5: Mapped[float | None] = mapped_column(Float)
    load15: Mapped[float | None] = mapped_column(Float)
    mem_total: Mapped[int | None] = mapped_column(BigInteger)
    mem_used: Mapped[int | None] = mapped_column(BigInteger)
    mem_percent: Mapped[float | None] = mapped_column(Float)
    swap_percent: Mapped[float | None] = mapped_column(Float)
    disk_percent: Mapped[float | None] = mapped_column(Float)
    uptime_seconds: Mapped[int | None] = mapped_column(BigInteger)
    tcp_established: Mapped[int | None] = mapped_column(Integer)
    tcp_listen: Mapped[int | None] = mapped_column(Integer)
    tcp_time_wait: Mapped[int | None] = mapped_column(Integer)
    udp_sockets: Mapped[int | None] = mapped_column(Integer)
    tcp_retrans_segs: Mapped[int | None] = mapped_column(BigInteger)
    rx_bps: Mapped[float | None] = mapped_column(Float)
    tx_bps: Mapped[float | None] = mapped_column(Float)
    # Bytes transferred on primary interfaces during the sample interval.
    rx_bytes: Mapped[int | None] = mapped_column(BigInteger)
    tx_bytes: Mapped[int | None] = mapped_column(BigInteger)


class InterfaceSample(Base):
    __tablename__ = "interface_samples"
    __table_args__ = (Index("ix_interface_samples_agent_iface_ts", "agent_id", "iface", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(TS)
    iface: Mapped[str] = mapped_column(String(64))
    rx_bps: Mapped[float] = mapped_column(Float, default=0)
    tx_bps: Mapped[float] = mapped_column(Float, default=0)
    rx_pps: Mapped[float] = mapped_column(Float, default=0)
    tx_pps: Mapped[float] = mapped_column(Float, default=0)
    rx_errs: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_errs: Mapped[int] = mapped_column(BigInteger, default=0)
    rx_drops: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_drops: Mapped[int] = mapped_column(BigInteger, default=0)
    rx_bytes: Mapped[int | None] = mapped_column(BigInteger)
    tx_bytes: Mapped[int | None] = mapped_column(BigInteger)
    primary: Mapped[bool | None] = mapped_column(Boolean)


class TrafficDaily(Base):
    """Bytes consumed per agent, interface and calendar day (in the configured
    usage timezone). iface '*' holds the host total over primary interfaces.
    Kept much longer than raw samples so monthly usage survives retention."""

    __tablename__ = "traffic_daily"

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    iface: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)


class LiveRate(Base):
    """Most recent fast (≈2 s) rate sample per agent for the live view.
    One row per agent, overwritten on every report; UNLOGGED in PostgreSQL."""

    __tablename__ = "live_rates"
    __table_args__ = {"prefixes": ["UNLOGGED"]}

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(TS)
    rx_bps: Mapped[float] = mapped_column(Float, default=0)
    tx_bps: Mapped[float] = mapped_column(Float, default=0)
    interfaces: Mapped[list] = mapped_column(JSONB, default=list)


class AgentInventory(Base):
    __tablename__ = "agent_inventory"

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    interfaces: Mapped[list] = mapped_column(JSONB, default=list)
    routes: Mapped[list] = mapped_column(JSONB, default=list)
    routes6: Mapped[list] = mapped_column(JSONB, default=list)
    connections: Mapped[list] = mapped_column(JSONB, default=list)
    dns: Mapped[dict] = mapped_column(JSONB, default=dict)
    system: Mapped[dict] = mapped_column(JSONB, default=dict)


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    type: Mapped[JobType] = mapped_column(_enum(JobType, "job_type"))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    interval_seconds: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(TS)

    agent: Mapped[Agent] = relationship(lazy="selectin")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_agent_status", "agent_id", "status"),
        Index("ix_jobs_type_created", "type", "created_at"),
        Index("ix_jobs_schedule_created", "schedule_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    type: Mapped[JobType] = mapped_column(_enum(JobType, "job_type"))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    target: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.queued
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedules.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    raw: Mapped[str | None] = mapped_column(Text)
    # Denormalised numeric summary for fast analytics/alerting.
    bps: Mapped[float | None] = mapped_column(Float)
    rtt_avg_ms: Mapped[float | None] = mapped_column(Float)
    loss_percent: Mapped[float | None] = mapped_column(Float)
    jitter_ms: Mapped[float | None] = mapped_column(Float)
    retransmits: Mapped[int | None] = mapped_column(Integer)

    agent: Mapped[Agent] = relationship(lazy="selectin")


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    metric: Mapped[str] = mapped_column(String(64))
    operator: Mapped[str] = mapped_column(String(4))
    threshold: Mapped[float] = mapped_column(Float)
    for_seconds: Mapped[int] = mapped_column(Integer, default=60)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    iface: Mapped[str | None] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(255))
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"), default=Severity.warning)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    webhook_url: Mapped[str | None] = mapped_column(String(1024))
    email_to: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_rule_agent_state", "rule_id", "agent_id", "state"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"))
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    state: Mapped[AlertState] = mapped_column(_enum(AlertState, "alert_state"))
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"))
    value: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(TS)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(TS)

    rule: Mapped[AlertRule] = relationship(lazy="selectin")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_ts", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, default=utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))


# ============================================================================ VPN (Xray)
class XrayInbound(Base):
    """An Xray inbound running on a node (an enrolled agent with Xray installed)."""

    __tablename__ = "xray_inbounds"
    __table_args__ = (UniqueConstraint("agent_id", "port", name="uq_xray_inbounds_agent_port"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    remark: Mapped[str] = mapped_column(String(128))
    protocol: Mapped[str] = mapped_column(String(16))  # vless | vmess | trojan | shadowsocks
    port: Mapped[int] = mapped_column(Integer)
    listen: Mapped[str] = mapped_column(String(64), default="")
    network: Mapped[str] = mapped_column(String(16), default="tcp")  # tcp | ws | grpc | httpupgrade | xhttp
    security: Mapped[str] = mapped_column(String(16), default="none")  # none | tls | reality
    # Host clients connect to (domain or IP of the node).
    address: Mapped[str] = mapped_column(String(255))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    up: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    down: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")

    @property
    def tag(self) -> str:
        return f"in-{self.id}"


class VpnUserApp(Base):
    """A client app that fetched a user's subscription (one row per User-Agent)."""

    __tablename__ = "vpn_user_apps"
    __table_args__ = (UniqueConstraint("user_id", "user_agent", name="uq_vpn_user_apps_user_ua"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("vpn_users.id", ondelete="CASCADE"), index=True)
    user_agent: Mapped[str] = mapped_column(String(256))
    app: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32), default="")
    last_ip: Mapped[str] = mapped_column(String(64), default="")
    first_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    fetches: Mapped[int] = mapped_column(Integer, default=1)


class XrayOutbound(Base):
    """An Xray outbound (upstream proxy) that routing rules can send traffic to."""

    __tablename__ = "xray_outbounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    remark: Mapped[str] = mapped_column(String(128))
    protocol: Mapped[str] = mapped_column(String(16))
    # Share link it was created from (empty when pasted as JSON).
    link: Mapped[str] = mapped_column(Text, default="")
    # Xray outbound object without "tag".
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Nodes that get this outbound; NULL = every node.
    agent_ids: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    up: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    down: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")

    @property
    def tag(self) -> str:
        return f"out-{self.id}"

    def on_node(self, agent_id: str) -> bool:
        return self.agent_ids is None or agent_id in self.agent_ids


class XrayRoutingRule(Base):
    """An ordered routing rule; the first matching rule decides the outbound."""

    __tablename__ = "xray_routing_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)
    remark: Mapped[str] = mapped_column(String(128), default="")
    action: Mapped[str] = mapped_column(String(16))  # direct | block | outbound
    outbound_id: Mapped[int | None] = mapped_column(ForeignKey("xray_outbounds.id", ondelete="RESTRICT"), nullable=True)
    inbound_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    user_ids: Mapped[list[int]] = mapped_column(JSONB, default=list)
    domains: Mapped[list[str]] = mapped_column(JSONB, default=list)
    ips: Mapped[list[str]] = mapped_column(JSONB, default=list)
    port: Mapped[str] = mapped_column(String(128), default="")
    network: Mapped[str] = mapped_column(String(8), default="")
    protocols: Mapped[list[str]] = mapped_column(JSONB, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class VpnUser(Base):
    __tablename__ = "vpn_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    uuid: Mapped[str] = mapped_column(String(36), default=new_uuid)
    password: Mapped[str] = mapped_column(String(64))  # trojan / shadowsocks secret
    sub_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    data_limit: Mapped[int] = mapped_column(BigInteger, default=0)  # bytes; 0 = unlimited
    used_up: Mapped[int] = mapped_column(BigInteger, default=0)
    used_down: Mapped[int] = mapped_column(BigInteger, default=0)
    lifetime_used: Mapped[int] = mapped_column(BigInteger, default=0)
    expire_at: Mapped[datetime | None] = mapped_column(TS)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # None = every enabled inbound; otherwise a list of inbound ids.
    inbound_ids: Mapped[list | None] = mapped_column(JSONB)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
    last_online_at: Mapped[datetime | None] = mapped_column(TS)
    traffic_reset_at: Mapped[datetime | None] = mapped_column(TS)

    @property
    def email(self) -> str:
        """Stable identifier used inside Xray configs and statistics."""
        return f"u{self.id}"

    @property
    def used(self) -> int:
        return (self.used_up or 0) + (self.used_down or 0)

    def status(self, now: datetime | None = None) -> str:
        now = now or utcnow()
        if not self.enabled:
            return "disabled"
        if self.expire_at is not None and self.expire_at <= now:
            return "expired"
        if self.data_limit and self.used >= self.data_limit:
            return "limited"
        return "active"


class VpnUserTrafficDaily(Base):
    __tablename__ = "vpn_user_traffic_daily"

    user_id: Mapped[int] = mapped_column(ForeignKey("vpn_users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    up: Mapped[int] = mapped_column(BigInteger, default=0)
    down: Mapped[int] = mapped_column(BigInteger, default=0)


class XrayNodeState(Base):
    """What each node last reported about its Xray process."""

    __tablename__ = "xray_node_state"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    applied_hash: Mapped[str | None] = mapped_column(String(64))
    applied_at: Mapped[datetime | None] = mapped_column(TS)
    xray_version: Mapped[str | None] = mapped_column(String(64))
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    online_users: Mapped[list] = mapped_column(JSONB, default=list)
    # {"u12": {"203.0.113.7": <unix ts last seen>}} from Xray's online IP list.
    online_ips: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class WgInbound(Base):
    """A WireGuard server interface on a node. One per node in this version — the
    node's single `wg0`. A real network interface, not an Xray inbound: a separate
    privileged systemd unit on the node brings it up with `wg-quick`/`wg syncconf`."""

    __tablename__ = "wg_inbounds"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    remark: Mapped[str] = mapped_column(String(128))
    listen_port: Mapped[int] = mapped_column(Integer)
    network: Mapped[str] = mapped_column(String(64))             # peer pool, e.g. "10.70.0.0/24"
    address: Mapped[str] = mapped_column(String(255))            # host/IP clients connect to
    dns: Mapped[str] = mapped_column(String(255), default="")    # comma-separated, pushed to clients
    mtu: Mapped[int] = mapped_column(Integer, default=1420)
    persistent_keepalive: Mapped[int] = mapped_column(Integer, default=25)
    egress_iface: Mapped[str] = mapped_column(String(32), default="")  # for the NAT PostUp/PostDown rules
    private_key: Mapped[str] = mapped_column(String(64))
    public_key: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)

    interface = "wg0"


class WgPeer(Base):
    """A WireGuard client (one VPN user on one node's wg0). Both keys are generated by
    the panel so a ready-to-use client config can be shown immediately — unlike Xray,
    WireGuard has no concept of a server-only secret the client derives a config from."""

    __tablename__ = "wg_peers"
    __table_args__ = (
        UniqueConstraint("agent_id", "user_id", name="uq_wg_peers_agent_user"),
        UniqueConstraint("agent_id", "address", name="uq_wg_peers_agent_address"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("wg_inbounds.agent_id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("vpn_users.id", ondelete="CASCADE"))
    address: Mapped[str] = mapped_column(String(64))              # allocated client IP, no mask
    private_key: Mapped[str] = mapped_column(String(64))
    public_key: Mapped[str] = mapped_column(String(64))
    preshared_key: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    up: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    down: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    last_handshake_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, default=utcnow)


class WgNodeState(Base):
    """What each node last reported about its wg0 interface."""

    __tablename__ = "wg_node_state"

    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    applied_hash: Mapped[str | None] = mapped_column(String(64))
    applied_at: Mapped[datetime | None] = mapped_column(TS)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(TS, default=utcnow)
