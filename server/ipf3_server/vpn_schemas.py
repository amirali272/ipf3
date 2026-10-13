from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schemas import validate_host

Protocol = Literal["vless", "vmess", "trojan", "shadowsocks"]
Network = Literal["tcp", "ws", "grpc", "httpupgrade", "xhttp"]
Security = Literal["none", "tls", "reality"]
Fingerprint = Literal["chrome", "firefox", "safari", "ios", "android", "edge", "360", "qq", "random", "randomized"]

SS_AEAD = ("aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305", "xchacha20-ietf-poly1305")
SS_2022 = {"2022-blake3-aes-128-gcm": 16, "2022-blake3-aes-256-gcm": 32, "2022-blake3-chacha20-poly1305": 32}
SS_METHODS = (*SS_AEAD, *SS_2022)

API_PORT = 10085
_SHORT_ID = re.compile(r"^[0-9a-f]{0,16}$")
_PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")
_SERVICE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class InboundSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # transport
    path: str = "/"
    host: str = ""
    service_name: str = "grpc"
    xhttp_mode: Literal["auto", "packet-up", "stream-up", "stream-one"] = "auto"
    # protocol
    flow: Literal["", "xtls-rprx-vision"] = ""
    ss_method: str = "chacha20-ietf-poly1305"
    ss_server_password: str = ""
    # tls
    sni: str = ""
    alpn: list[Literal["h2", "http/1.1", "h3"]] = []
    fingerprint: Fingerprint = "chrome"
    cert_pem: str = ""
    key_pem: str = ""
    cert_file: str = ""
    key_file: str = ""
    # reality
    target: str = "www.microsoft.com:443"
    server_names: list[str] = ["www.microsoft.com"]
    private_key: str = ""
    public_key: str = ""
    short_ids: list[str] = [""]
    spider_x: str = "/"

    @field_validator("path", "spider_x")
    @classmethod
    def _path(cls, v: str) -> str:
        v = v or "/"
        if not _PATH.match(v) or len(v) > 256:
            raise ValueError("path must start with / and contain only URL-safe characters")
        return v

    @field_validator("host", "sni")
    @classmethod
    def _host(cls, v: str) -> str:
        return validate_host(v) if v else ""

    @field_validator("service_name")
    @classmethod
    def _service(cls, v: str) -> str:
        if not _SERVICE.match(v):
            raise ValueError("gRPC service name: letters, digits, . _ -")
        return v

    @field_validator("server_names")
    @classmethod
    def _names(cls, v: list[str]) -> list[str]:
        return [validate_host(n) for n in v if n.strip()][:20]

    @field_validator("short_ids")
    @classmethod
    def _sids(cls, v: list[str]) -> list[str]:
        out = []
        for s in v[:20]:
            s = s.strip().lower()
            if not _SHORT_ID.match(s) or len(s) % 2:
                raise ValueError("short IDs are hex strings with an even length of 0–16")
            out.append(s)
        return out or [""]

    @field_validator("target")
    @classmethod
    def _target(cls, v: str) -> str:
        host, _, port = v.rpartition(":")
        if not host or not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ValueError("target must be host:port, e.g. www.microsoft.com:443")
        validate_host(host)
        return v

    @field_validator("cert_file", "key_file")
    @classmethod
    def _file(cls, v: str) -> str:
        if v and not re.match(r"^/[A-Za-z0-9._/@+-]+$", v):
            raise ValueError("must be an absolute file path")
        return v


class InboundIn(BaseModel):
    agent_id: str
    remark: str = Field(min_length=1, max_length=128)
    protocol: Protocol
    port: int = Field(ge=1, le=65535)
    listen: str = ""
    network: Network = "tcp"
    security: Security = "none"
    address: str = Field(min_length=1, max_length=255)
    settings: InboundSettings = InboundSettings()
    enabled: bool = True

    @field_validator("address")
    @classmethod
    def _addr(cls, v: str) -> str:
        return validate_host(v)

    @field_validator("listen")
    @classmethod
    def _listen(cls, v: str) -> str:
        if not v:
            return ""
        import ipaddress

        return str(ipaddress.ip_address(v))

    @model_validator(mode="after")
    def _combos(self):
        s = self.settings
        if self.port == API_PORT:
            raise ValueError(f"port {API_PORT} is reserved for the Xray API")
        if self.protocol == "shadowsocks":
            if self.network != "tcp" or self.security != "none":
                raise ValueError("Shadowsocks inbounds use plain TCP/UDP: network tcp, security none")
            if s.ss_method not in SS_METHODS:
                raise ValueError(f"unsupported Shadowsocks method; choose one of {', '.join(SS_METHODS)}")
            if s.ss_method in SS_2022:
                try:
                    key = base64.b64decode(s.ss_server_password, validate=True)
                except ValueError:
                    key = b""
                if len(key) != SS_2022[s.ss_method]:
                    raise ValueError(f"{s.ss_method} needs a base64 server key of {SS_2022[s.ss_method]} bytes (use Generate)")
        if self.security == "reality":
            if self.protocol not in ("vless", "trojan"):
                raise ValueError("REALITY works with VLESS or Trojan")
            if self.network not in ("tcp", "grpc", "xhttp"):
                raise ValueError("REALITY works with TCP, gRPC or XHTTP transports")
            if not s.private_key or not s.public_key:
                raise ValueError("REALITY needs a key pair (use Generate)")
            if not s.server_names:
                raise ValueError("REALITY needs at least one server name (SNI)")
        if self.security == "tls":
            has_pem = bool(s.cert_pem.strip() and s.key_pem.strip())
            has_files = bool(s.cert_file and s.key_file)
            if not (has_pem or has_files):
                raise ValueError("TLS needs a certificate and key (paste PEM or give file paths on the node)")
            if has_pem and ("BEGIN" not in s.cert_pem or "PRIVATE KEY" not in s.key_pem):
                raise ValueError("certificate/key must be PEM encoded")
        if s.flow:
            if not (self.protocol == "vless" and self.network == "tcp" and self.security in ("tls", "reality")):
                raise ValueError("xtls-rprx-vision needs VLESS over TCP with TLS or REALITY")
        if self.network == "grpc" and self.security == "none":
            pass  # allowed (behind a CDN/proxy that terminates TLS)
        return self


class InboundUpdate(InboundIn):
    agent_id: str | None = None  # type: ignore[assignment]


class InboundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    agent_id: str
    agent_name: str | None = None
    remark: str
    protocol: str
    port: int
    listen: str
    network: str
    security: str
    address: str
    settings: dict
    enabled: bool
    created_at: datetime
    tag: str
    users: int = 0
    up: int = 0
    down: int = 0
    online: int = 0


_USERNAME = r"^[A-Za-z0-9_.-]{2,64}$"


class VpnUserIn(BaseModel):
    username: str = Field(pattern=_USERNAME)
    data_limit_gb: float = Field(0, ge=0, le=1_000_000)
    expire_at: datetime | None = None
    expire_days: int | None = Field(None, ge=1, le=36500)
    enabled: bool = True
    inbound_ids: list[int] | None = None
    note: str = Field("", max_length=500)


class VpnUserUpdate(BaseModel):
    username: str | None = Field(None, pattern=_USERNAME)
    data_limit_gb: float | None = Field(None, ge=0, le=1_000_000)
    expire_at: datetime | None = None
    clear_expire: bool = False
    expire_days: int | None = Field(None, ge=1, le=36500)
    enabled: bool | None = None
    inbound_ids: list[int] | None = None
    all_inbounds: bool = False
    note: str | None = Field(None, max_length=500)


class VpnUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    status: str
    data_limit: int
    used_up: int
    used_down: int
    used: int
    lifetime_used: int
    expire_at: datetime | None
    enabled: bool
    inbound_ids: list | None
    note: str
    created_at: datetime
    last_online_at: datetime | None
    online: bool = False
    sub_token: str
    sub_url: str = ""


# ---------------------------------------------------------------------------- agent protocol
class XrayStateIn(BaseModel):
    applied_hash: str | None = Field(None, max_length=64)
    version: str | None = Field(None, max_length=64)
    running: bool = False
    error: str | None = Field(None, max_length=4000)
    online_users: list[str] = Field(default_factory=list, max_length=100000)


class XrayTraffic(BaseModel):
    up: int = Field(0, ge=0)
    down: int = Field(0, ge=0)


class XrayStatsIn(BaseModel):
    users: dict[str, XrayTraffic] = Field(default_factory=dict, max_length=100000)
    inbounds: dict[str, XrayTraffic] = Field(default_factory=dict, max_length=10000)
