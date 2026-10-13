"""Xray-core configuration, share links and subscription formats."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode

from ..models import VpnUser, XrayInbound
from ..vpn_schemas import API_PORT, SS_2022


# ----------------------------------------------------------------------------- users ↔ inbounds
def user_has_inbound(user: VpnUser, inbound: XrayInbound) -> bool:
    return user.inbound_ids is None or inbound.id in user.inbound_ids


def ss_user_key(user: VpnUser, method: str) -> str:
    """Per-user Shadowsocks secret. 2022 ciphers need a base64 key of a fixed size,
    derived deterministically from the user's secret."""
    if method in SS_2022:
        raw = hashlib.sha256(f"ss2022:{user.password}".encode()).digest()[: SS_2022[method]]
        return base64.b64encode(raw).decode()
    return user.password


def _client(inbound: XrayInbound, user: VpnUser) -> dict[str, Any]:
    s = inbound.settings or {}
    if inbound.protocol == "vless":
        c = {"id": user.uuid, "email": user.email}
        if s.get("flow"):
            c["flow"] = s["flow"]
        return c
    if inbound.protocol == "vmess":
        return {"id": user.uuid, "email": user.email}
    if inbound.protocol == "trojan":
        return {"password": user.password, "email": user.email}
    method = s.get("ss_method", "chacha20-ietf-poly1305")
    c = {"password": ss_user_key(user, method), "email": user.email}
    if method not in SS_2022:
        c["method"] = method
    return c


def _pem_lines(pem: str) -> list[str]:
    return [line for line in pem.strip().splitlines() if line.strip()]


def stream_settings(inbound: XrayInbound) -> dict[str, Any]:
    s = inbound.settings or {}
    net, sec = inbound.network, inbound.security
    out: dict[str, Any] = {"network": net, "security": sec}
    if net == "tcp":
        out["tcpSettings"] = {"header": {"type": "none"}}
    elif net == "ws":
        out["wsSettings"] = {"path": s.get("path", "/"), "host": s.get("host", "")}
    elif net == "grpc":
        out["grpcSettings"] = {"serviceName": s.get("service_name", "grpc"), "multiMode": False}
    elif net == "httpupgrade":
        out["httpupgradeSettings"] = {"path": s.get("path", "/"), "host": s.get("host", "")}
    elif net == "xhttp":
        out["xhttpSettings"] = {"path": s.get("path", "/"), "host": s.get("host", ""), "mode": s.get("xhttp_mode", "auto")}
    if sec == "tls":
        cert: dict[str, Any]
        if s.get("cert_pem") and s.get("key_pem"):
            cert = {"certificate": _pem_lines(s["cert_pem"]), "key": _pem_lines(s["key_pem"])}
        else:
            cert = {"certificateFile": s.get("cert_file", ""), "keyFile": s.get("key_file", "")}
        tls: dict[str, Any] = {"certificates": [cert], "minVersion": "1.2"}
        if s.get("sni"):
            tls["serverName"] = s["sni"]
        if s.get("alpn"):
            tls["alpn"] = s["alpn"]
        out["tlsSettings"] = tls
    elif sec == "reality":
        out["realitySettings"] = {
            "show": False,
            "target": s.get("target", "www.microsoft.com:443"),
            "xver": 0,
            "serverNames": s.get("server_names") or [],
            "privateKey": s.get("private_key", ""),
            "shortIds": s.get("short_ids") or [""],
        }
    return out


def inbound_config(inbound: XrayInbound, users: list[VpnUser]) -> dict[str, Any]:
    s = inbound.settings or {}
    clients = [_client(inbound, u) for u in users if user_has_inbound(u, inbound)]
    if inbound.protocol in ("vless", "vmess", "trojan"):
        settings: dict[str, Any] = {"clients": clients}
        if inbound.protocol == "vless":
            settings["decryption"] = "none"
    else:
        method = s.get("ss_method", "chacha20-ietf-poly1305")
        settings = {"method": method, "clients": clients, "network": "tcp,udp"}
        if method in SS_2022:
            settings["password"] = s.get("ss_server_password", "")
    cfg: dict[str, Any] = {
        "tag": inbound.tag,
        "listen": inbound.listen or "0.0.0.0",
        "port": inbound.port,
        "protocol": inbound.protocol,
        "settings": settings,
        "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": True},
    }
    if inbound.protocol != "shadowsocks":
        cfg["streamSettings"] = stream_settings(inbound)
    return cfg


def build_config(inbounds: list[XrayInbound], users: list[VpnUser], now: datetime | None = None) -> dict[str, Any]:
    """Full Xray config for one node. Only active users and enabled inbounds are
    included, so expiry and data limits are enforced by regeneration."""
    active = sorted((u for u in users if u.status(now) == "active"), key=lambda u: u.id)
    return {
        "log": {"loglevel": "warning", "access": "none"},
        "api": {"tag": "api", "services": ["StatsService"]},
        "stats": {},
        "policy": {
            "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True, "statsUserOnline": True}},
            "system": {"statsInboundUplink": True, "statsInboundDownlink": True},
        },
        "inbounds": [
            {"tag": "api", "listen": "127.0.0.1", "port": API_PORT, "protocol": "dokodemo-door", "settings": {"address": "127.0.0.1"}},
            *[inbound_config(i, active) for i in sorted(inbounds, key=lambda i: i.id) if i.enabled],
        ],
        "outbounds": [
            {"tag": "direct", "protocol": "freedom", "settings": {"domainStrategy": "UseIP"}},
            {"tag": "blocked", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
                # Never let VPN users reach the node's own private networks or localhost services.
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "blocked"},
                {"type": "field", "protocol": ["bittorrent"], "outboundTag": "blocked"},
            ],
        },
    }


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ----------------------------------------------------------------------------- share links
def _remark(inbound: XrayInbound, user: VpnUser) -> str:
    return f"{inbound.remark}-{user.username}"


def _transport_params(inbound: XrayInbound) -> dict[str, str]:
    s = inbound.settings or {}
    p: dict[str, str] = {"type": inbound.network}
    if inbound.network in ("ws", "httpupgrade", "xhttp"):
        p["path"] = s.get("path", "/")
        if s.get("host"):
            p["host"] = s["host"]
        if inbound.network == "xhttp":
            p["mode"] = s.get("xhttp_mode", "auto")
    elif inbound.network == "grpc":
        p["serviceName"] = s.get("service_name", "grpc")
        p["mode"] = "gun"
    elif inbound.network == "tcp":
        p["headerType"] = "none"
    p["security"] = inbound.security
    if inbound.security == "tls":
        if s.get("sni"):
            p["sni"] = s["sni"]
        p["fp"] = s.get("fingerprint", "chrome")
        if s.get("alpn"):
            p["alpn"] = ",".join(s["alpn"])
    elif inbound.security == "reality":
        names = s.get("server_names") or [""]
        p["sni"] = names[0]
        p["fp"] = s.get("fingerprint", "chrome")
        p["pbk"] = s.get("public_key", "")
        p["sid"] = (s.get("short_ids") or [""])[0]
        p["spx"] = s.get("spider_x", "/")
    return p


def _host(addr: str) -> str:
    return f"[{addr}]" if ":" in addr else addr


def share_link(inbound: XrayInbound, user: VpnUser) -> str:
    s = inbound.settings or {}
    remark = quote(_remark(inbound, user))
    host = _host(inbound.address)
    if inbound.protocol == "vless":
        p = {"encryption": "none", **_transport_params(inbound)}
        if s.get("flow"):
            p["flow"] = s["flow"]
        return f"vless://{user.uuid}@{host}:{inbound.port}?{urlencode(p, quote_via=quote)}#{remark}"
    if inbound.protocol == "trojan":
        p = _transport_params(inbound)
        return f"trojan://{quote(user.password, safe='')}@{host}:{inbound.port}?{urlencode(p, quote_via=quote)}#{remark}"
    if inbound.protocol == "vmess":
        tp = _transport_params(inbound)
        obj = {
            "v": "2",
            "ps": _remark(inbound, user),
            "add": inbound.address,
            "port": str(inbound.port),
            "id": user.uuid,
            "aid": "0",
            "scy": "auto",
            "net": inbound.network,
            "type": "none",
            "host": tp.get("host", ""),
            "path": tp.get("serviceName", tp.get("path", "")),
            "tls": "tls" if inbound.security == "tls" else "",
            "sni": tp.get("sni", ""),
            "alpn": tp.get("alpn", ""),
            "fp": tp.get("fp", ""),
        }
        return "vmess://" + base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()
    # shadowsocks
    method = s.get("ss_method", "chacha20-ietf-poly1305")
    if method in SS_2022:
        secret = f"{s.get('ss_server_password', '')}:{ss_user_key(user, method)}"
        userinfo = f"{quote(method, safe='')}:{quote(secret, safe='')}"
    else:
        userinfo = base64.urlsafe_b64encode(f"{method}:{user.password}".encode()).decode().rstrip("=")
    return f"ss://{userinfo}@{host}:{inbound.port}#{remark}"


def user_links(user: VpnUser, inbounds: list[XrayInbound]) -> list[str]:
    return [share_link(i, user) for i in sorted(inbounds, key=lambda i: i.id) if i.enabled and user_has_inbound(user, i)]


# ----------------------------------------------------------------------------- Clash Meta (mihomo)
def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(str(v), ensure_ascii=False)  # JSON strings are valid YAML


def _yaml(obj: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(_yaml(v, indent + 1))
            elif isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}: {'{}' if isinstance(v, dict) else '[]'}")
            else:
                lines.append(f"{pad}{k}: {_yaml_scalar(v)}")
        return "\n".join(lines)
    if isinstance(obj, list):
        lines = []
        for v in obj:
            if isinstance(v, dict):
                inner = _yaml(v, indent + 1).splitlines()
                lines.append(f"{pad}- {inner[0].strip()}")
                lines.extend(inner[1:])
            else:
                lines.append(f"{pad}- {_yaml_scalar(v)}")
        return "\n".join(lines)
    return f"{pad}{_yaml_scalar(obj)}"


def clash_proxy(inbound: XrayInbound, user: VpnUser) -> dict[str, Any] | None:
    s = inbound.settings or {}
    if inbound.network == "xhttp":
        return None  # not supported by mihomo
    p: dict[str, Any] = {"name": _remark(inbound, user), "server": inbound.address, "port": inbound.port, "udp": True}
    if inbound.protocol == "shadowsocks":
        method = s.get("ss_method", "chacha20-ietf-poly1305")
        pw = f"{s.get('ss_server_password', '')}:{ss_user_key(user, method)}" if method in SS_2022 else user.password
        p.update({"type": "ss", "cipher": method, "password": pw})
        return p
    if inbound.protocol == "vless":
        p.update({"type": "vless", "uuid": user.uuid})
        if s.get("flow"):
            p["flow"] = s["flow"]
    elif inbound.protocol == "vmess":
        p.update({"type": "vmess", "uuid": user.uuid, "alterId": 0, "cipher": "auto"})
    else:
        p.update({"type": "trojan", "password": user.password})
    p["network"] = {"httpupgrade": "ws"}.get(inbound.network, inbound.network)
    if inbound.network in ("ws", "httpupgrade"):
        opts: dict[str, Any] = {"path": s.get("path", "/")}
        if s.get("host"):
            opts["headers"] = {"Host": s["host"]}
        if inbound.network == "httpupgrade":
            opts["v2ray-http-upgrade"] = True
        p["ws-opts"] = opts
    elif inbound.network == "grpc":
        p["grpc-opts"] = {"grpc-service-name": s.get("service_name", "grpc")}
    if inbound.security in ("tls", "reality"):
        if inbound.protocol != "trojan":
            p["tls"] = True
        p["client-fingerprint"] = s.get("fingerprint", "chrome")
        sni = s.get("sni") if inbound.security == "tls" else (s.get("server_names") or [""])[0]
        if sni:
            p["sni" if inbound.protocol == "trojan" else "servername"] = sni
        if inbound.security == "tls" and s.get("alpn"):
            p["alpn"] = s["alpn"]
        if inbound.security == "reality":
            p["reality-opts"] = {"public-key": s.get("public_key", ""), "short-id": (s.get("short_ids") or [""])[0]}
    return p


def clash_config(user: VpnUser, inbounds: list[XrayInbound]) -> str:
    proxies = [p for i in sorted(inbounds, key=lambda i: i.id) if i.enabled and user_has_inbound(user, i) for p in [clash_proxy(i, user)] if p]
    names = [p["name"] for p in proxies]
    cfg = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "proxies": proxies,
        "proxy-groups": [
            {"name": "Proxy", "type": "select", "proxies": ["Auto", *names] if names else ["DIRECT"]},
            {"name": "Auto", "type": "url-test", "url": "https://www.gstatic.com/generate_204", "interval": 300, "proxies": names or ["DIRECT"]},
        ],
        "rules": ["GEOIP,private,DIRECT,no-resolve", "MATCH,Proxy"],
    }
    return _yaml(cfg) + "\n"
