from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator

from .models import AlertState, JobStatus, JobType, Role, Severity

_HOST_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def validate_host(value: str) -> str:
    """Accept an IPv4/IPv6 literal or an RFC 1123 hostname. Rejects anything that
    could be interpreted as a command-line option or contains shell metacharacters."""
    v = value.strip()
    if not v or len(v) > 253:
        raise ValueError("invalid host")
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        pass
    name = v[:-1] if v.endswith(".") else v
    labels = name.split(".")
    if not all(_HOST_LABEL.match(label) for label in labels):
        raise ValueError("invalid hostname")
    if labels[-1].isdigit():
        raise ValueError("invalid hostname")
    return v.lower()


Host = Annotated[str, AfterValidator(validate_host)]


def validate_dns_name(value: str) -> str:
    v = value.strip()
    if not v or len(v) > 253:
        raise ValueError("invalid DNS name")
    try:
        return str(ipaddress.ip_address(v))  # allowed for PTR lookups
    except ValueError:
        pass
    name = v[:-1] if v.endswith(".") else v
    for label in name.split("."):
        if not re.match(r"^(?!-)[A-Za-z0-9_-]{1,63}$", label):
            raise ValueError("invalid DNS name")
    return v.lower()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- job params
class Iperf3Params(_Strict):
    target: Host
    port: int = Field(5201, ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"
    duration: int = Field(10, ge=1, le=300)
    parallel: int = Field(1, ge=1, le=32)
    reverse: bool = False
    bidir: bool = False
    bitrate_bps: int | None = Field(None, ge=1000, le=400_000_000_000)
    omit: int = Field(0, ge=0, le=10)
    ipv6: bool = False

    @field_validator("bidir")
    @classmethod
    def _no_both(cls, v, info):
        if v and info.data.get("reverse"):
            raise ValueError("reverse and bidir are mutually exclusive")
        return v


class PingParams(_Strict):
    target: Host
    count: int = Field(20, ge=1, le=1000)
    interval: float = Field(1.0, ge=0.2, le=10.0)
    packet_size: int = Field(56, ge=16, le=65000)
    ipv6: bool = False


class TracerouteParams(_Strict):
    target: Host
    max_hops: int = Field(30, ge=1, le=64)
    queries: int = Field(3, ge=1, le=5)
    protocol: Literal["udp", "icmp", "tcp"] = "udp"
    ipv6: bool = False


class MtrParams(_Strict):
    target: Host
    count: int = Field(10, ge=1, le=200)
    max_hops: int = Field(30, ge=1, le=64)
    protocol: Literal["udp", "icmp", "tcp"] = "icmp"
    ipv6: bool = False


class DnsParams(_Strict):
    name: Annotated[str, AfterValidator(validate_dns_name)]
    record_type: Literal["A", "AAAA", "MX", "TXT", "NS", "CNAME", "SOA", "PTR", "SRV", "CAA"] = "A"
    server: str | None = None
    protocol: Literal["udp", "tcp"] = "udp"
    timeout: float = Field(5.0, ge=0.5, le=30.0)

    @field_validator("server")
    @classmethod
    def _server_ip(cls, v):
        if v in (None, ""):
            return None
        return str(ipaddress.ip_address(v.strip()))


PARAM_MODELS: dict[JobType, type[BaseModel]] = {
    JobType.iperf3: Iperf3Params,
    JobType.ping: PingParams,
    JobType.traceroute: TracerouteParams,
    JobType.mtr: MtrParams,
    JobType.dns: DnsParams,
}


def validate_job_params(job_type: JobType, params: dict[str, Any]) -> dict[str, Any]:
    model = PARAM_MODELS[job_type].model_validate(params)
    return model.model_dump()


def job_target(job_type: JobType, params: dict[str, Any]) -> str:
    return params.get("name") if job_type == JobType.dns else params.get("target", "")


# --------------------------------------------------------------------------- auth / users
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str | None
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    locked_until: datetime | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr | None = None
    password: str
    role: Role = Role.viewer


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = None
    unlock: bool | None = None


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


# --------------------------------------------------------------------------- agents
class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    hostname: str
    os_name: str
    kernel: str
    agent_version: str
    cpu_count: int | None
    capabilities: dict
    tags: list
    remote_addr: str | None
    disabled: bool
    created_at: datetime
    last_seen_at: datetime | None
    online: bool = False
    latest: dict | None = None


class AgentUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    tags: list[Annotated[str, Field(max_length=64)]] | None = None
    disabled: bool | None = None


class EnrollmentTokenCreate(BaseModel):
    note: str = Field("", max_length=255)
    ttl_hours: int | None = Field(None, ge=1, le=24 * 30)


class EnrollmentTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    note: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    agent_id: str | None
    token: str | None = None


# --------------------------------------------------------------------------- agent protocol
class SystemInfo(BaseModel):
    hostname: str = Field("", max_length=255)
    os_name: str = Field("", max_length=255)
    kernel: str = Field("", max_length=255)
    agent_version: str = Field("", max_length=32)
    cpu_count: int | None = None
    capabilities: dict[str, Any] = {}


class EnrollIn(BaseModel):
    enrollment_token: str = Field(min_length=10, max_length=256)
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.@-]+$")
    system: SystemInfo


class EnrollOut(BaseModel):
    agent_id: str
    agent_token: str


class SystemSample(BaseModel):
    cpu_percent: float | None = None
    load1: float | None = None
    load5: float | None = None
    load15: float | None = None
    mem_total: int | None = None
    mem_used: int | None = None
    mem_percent: float | None = None
    swap_percent: float | None = None
    disk_percent: float | None = None
    uptime_seconds: int | None = None
    tcp_established: int | None = None
    tcp_listen: int | None = None
    tcp_time_wait: int | None = None
    udp_sockets: int | None = None
    tcp_retrans_segs: int | None = None


class InterfaceRate(BaseModel):
    iface: str = Field(max_length=64)
    rx_bps: float = Field(ge=0)
    tx_bps: float = Field(ge=0)
    rx_pps: float = Field(0, ge=0)
    tx_pps: float = Field(0, ge=0)
    rx_errs: int = Field(0, ge=0)
    tx_errs: int = Field(0, ge=0)
    rx_drops: int = Field(0, ge=0)
    tx_drops: int = Field(0, ge=0)


class MetricsIn(BaseModel):
    ts: datetime
    system: SystemSample
    interfaces: list[InterfaceRate] = Field(default_factory=list, max_length=256)


class InventoryIn(BaseModel):
    interfaces: list[dict[str, Any]] = Field(default_factory=list, max_length=512)
    routes: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    routes6: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    connections: list[dict[str, Any]] = Field(default_factory=list, max_length=20000)
    dns: dict[str, Any] = {}
    system: dict[str, Any] = {}


class HeartbeatIn(BaseModel):
    system: SystemInfo


class AgentJobOut(BaseModel):
    id: str
    type: JobType
    params: dict


class JobResultIn(BaseModel):
    status: Literal["completed", "failed"]
    result: dict[str, Any] | None = None
    raw: str | None = Field(None, max_length=2_000_000)
    error: str | None = Field(None, max_length=10000)
    started_at: datetime | None = None
    finished_at: datetime | None = None


# --------------------------------------------------------------------------- jobs
class JobCreate(BaseModel):
    agent_id: str
    type: JobType
    params: dict[str, Any]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    agent_id: str
    agent_name: str | None = None
    type: JobType
    params: dict
    target: str
    status: JobStatus
    created_by: int | None
    schedule_id: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    bps: float | None
    rtt_avg_ms: float | None
    loss_percent: float | None
    jitter_ms: float | None
    retransmits: int | None


class JobDetailOut(JobOut):
    result: dict | None
    raw: str | None


# --------------------------------------------------------------------------- schedules
class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    agent_id: str
    type: JobType
    params: dict[str, Any]
    interval_seconds: int = Field(ge=30, le=7 * 86400)
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    params: dict[str, Any] | None = None
    interval_seconds: int | None = Field(None, ge=30, le=7 * 86400)
    enabled: bool | None = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    agent_id: str
    type: JobType
    params: dict
    interval_seconds: int
    enabled: bool
    created_at: datetime
    last_run_at: datetime | None


# --------------------------------------------------------------------------- alerts
ALERT_METRICS = {
    "cpu_percent": "CPU utilisation (%)",
    "mem_percent": "Memory utilisation (%)",
    "disk_percent": "Root filesystem utilisation (%)",
    "load1": "1-minute load average",
    "iface_rx_bps": "Interface receive rate (bit/s)",
    "iface_tx_bps": "Interface transmit rate (bit/s)",
    "iface_errors": "Interface errors+drops per interval",
    "agent_offline": "Agent offline (seconds since last contact)",
    "ping_loss_percent": "Ping packet loss (%)",
    "ping_rtt_ms": "Ping average RTT (ms)",
    "ping_jitter_ms": "Ping jitter (ms)",
    "iperf3_bps": "iperf3 throughput (bit/s)",
    "iperf3_loss_percent": "iperf3 UDP loss (%)",
    "dns_time_ms": "DNS resolution time (ms)",
    "job_failed": "Scheduled test failures in window (count)",
}

Operator = Literal[">", ">=", "<", "<=", "=="]


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    metric: str
    operator: Operator
    threshold: float
    for_seconds: int = Field(60, ge=0, le=86400)
    agent_id: str | None = None
    iface: str | None = Field(None, max_length=64)
    target: str | None = Field(None, max_length=255)
    severity: Severity = Severity.warning
    enabled: bool = True
    webhook_url: str | None = Field(None, max_length=1024, pattern=r"^https?://")
    email_to: str | None = Field(None, max_length=1024)

    @field_validator("metric")
    @classmethod
    def _metric(cls, v):
        if v not in ALERT_METRICS:
            raise ValueError(f"unknown metric; choose one of {sorted(ALERT_METRICS)}")
        return v

    @field_validator("email_to")
    @classmethod
    def _emails(cls, v):
        if not v:
            return None
        from email_validator import validate_email

        addrs = [a.strip() for a in v.split(",") if a.strip()]
        for a in addrs:
            validate_email(a, check_deliverability=False)
        return ",".join(addrs)


class AlertRuleUpdate(AlertRuleCreate):
    name: str | None = Field(None, min_length=1, max_length=128)  # type: ignore[assignment]
    metric: str | None = None  # type: ignore[assignment]
    operator: Operator | None = None  # type: ignore[assignment]
    threshold: float | None = None  # type: ignore[assignment]
    for_seconds: int | None = Field(None, ge=0, le=86400)  # type: ignore[assignment]
    severity: Severity | None = None  # type: ignore[assignment]
    enabled: bool | None = None  # type: ignore[assignment]

    @field_validator("metric")
    @classmethod
    def _metric(cls, v):
        if v is not None and v not in ALERT_METRICS:
            raise ValueError("unknown metric")
        return v


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    metric: str
    operator: str
    threshold: float
    for_seconds: int
    agent_id: str | None
    iface: str | None
    target: str | None
    severity: Severity
    enabled: bool
    webhook_url: str | None
    email_to: str | None
    created_at: datetime


class AlertEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: int
    rule_name: str | None = None
    metric: str | None = None
    agent_id: str | None
    agent_name: str | None = None
    state: AlertState
    severity: Severity
    value: float | None
    message: str
    started_at: datetime
    resolved_at: datetime | None
    acknowledged_by: int | None
    acknowledged_at: datetime | None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ts: datetime
    user_id: int | None
    username: str
    action: str
    target: str
    details: dict
    ip: str | None
