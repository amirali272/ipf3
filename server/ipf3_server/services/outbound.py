"""Outbounds: share link / JSON → Xray outbound, routing rules, validation with xray."""

from __future__ import annotations

import base64
import binascii
import json
import os
import subprocess
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

OUTBOUND_PROTOCOLS = ("vless", "vmess", "trojan", "shadowsocks", "socks", "http", "wireguard", "freedom", "blackhole")
NETWORKS = ("tcp", "raw", "ws", "grpc", "httpupgrade", "xhttp", "kcp")


class LinkError(ValueError):
    pass


def _b64(s: str) -> bytes:
    s = s.strip().replace("-", "+").replace("_", "/")
    try:
        return base64.b64decode(s + "=" * (-len(s) % 4), validate=False)
    except (binascii.Error, ValueError) as e:
        raise LinkError("invalid base64") from e


def _port(v: Any) -> int:
    try:
        p = int(v)
    except (TypeError, ValueError):
        raise LinkError("invalid port") from None
    if not 1 <= p <= 65535:
        raise LinkError("invalid port")
    return p


def _uport(u, default: int | None = None) -> int:
    try:
        p = u.port
    except ValueError:
        raise LinkError("invalid port") from None
    return _port(p if p is not None else default)


def _host(u) -> str:
    if not u.hostname:
        raise LinkError("missing server address")
    return u.hostname


def _stream(q: dict[str, str], default_security: str = "none", address: str = "") -> dict[str, Any]:
    """streamSettings from v2rayN-style query parameters."""
    net = (q.get("type") or q.get("net") or "tcp").lower()
    if net == "raw":
        net = "tcp"
    if net not in NETWORKS:
        raise LinkError(f"transport '{net}' is not supported by Xray")
    sec = (q.get("security") or default_security).lower()
    if sec in ("", "none"):
        sec = "none"
    if sec not in ("none", "tls", "reality"):
        raise LinkError(f"security '{sec}' is not supported")
    out: dict[str, Any] = {"network": net, "security": sec}
    host, path = q.get("host", ""), q.get("path", "")
    if net == "tcp" and q.get("headerType") == "http":
        req: dict[str, Any] = {"path": [path or "/"]}
        if host:
            req["headers"] = {"Host": host.split(",")}
        out["tcpSettings"] = {"header": {"type": "http", "request": req}}
    elif net == "ws":
        out["wsSettings"] = {"path": path or "/", "host": host}
    elif net == "httpupgrade":
        out["httpupgradeSettings"] = {"path": path or "/", "host": host}
    elif net == "xhttp":
        xs: dict[str, Any] = {"path": path or "/", "host": host, "mode": q.get("mode") or "auto"}
        if q.get("extra"):
            try:
                extra = json.loads(q["extra"])
            except ValueError:
                raise LinkError("invalid xhttp extra") from None
            if isinstance(extra, dict):
                xs["extra"] = extra
        out["xhttpSettings"] = xs
    elif net == "grpc":
        gs: dict[str, Any] = {"serviceName": q.get("serviceName") or q.get("path") or "", "multiMode": q.get("mode") == "multi"}
        if q.get("authority"):
            gs["authority"] = q["authority"]
        out["grpcSettings"] = gs
    elif net == "kcp":
        ks: dict[str, Any] = {"header": {"type": q.get("headerType") or "none"}}
        if q.get("seed"):
            ks["seed"] = q["seed"]
        out["kcpSettings"] = ks
    sni = q.get("sni") or q.get("peer") or ""
    fp = q.get("fp") or ""
    if sec == "tls":
        tls: dict[str, Any] = {"serverName": sni or host.split(",")[0] or address}
        if fp:
            tls["fingerprint"] = fp
        if q.get("alpn"):
            tls["alpn"] = [a for a in q["alpn"].split(",") if a]
        if q.get("pcs"):
            tls["pinnedPeerCertSha256"] = q["pcs"]
        out["tlsSettings"] = tls
    elif sec == "reality":
        if not q.get("pbk"):
            raise LinkError("REALITY link has no public key (pbk)")
        rs: dict[str, Any] = {"serverName": sni, "fingerprint": fp or "chrome", "password": q["pbk"], "shortId": q.get("sid", ""), "spiderX": q.get("spx") or "/"}
        if q.get("pqv"):
            rs["mldsa65Verify"] = q["pqv"]
        out["realitySettings"] = rs
    return out


def _query(u) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}


def _vmess(link: str) -> tuple[dict[str, Any], str]:
    try:
        v = json.loads(_b64(link[8:]))
    except (ValueError, UnicodeDecodeError):
        raise LinkError("invalid vmess link") from None
    if not isinstance(v, dict) or not v.get("add") or not v.get("id"):
        raise LinkError("invalid vmess link")
    q = {
        "type": str(v.get("net") or "tcp"),
        "security": "tls" if str(v.get("tls", "")).lower() == "tls" else "none",
        "host": str(v.get("host") or ""),
        "path": str(v.get("path") or ""),
        "sni": str(v.get("sni") or ""),
        "alpn": str(v.get("alpn") or ""),
        "fp": str(v.get("fp") or ""),
        "headerType": str(v.get("type") or ""),
        "serviceName": str(v.get("path") or ""),
        "mode": str(v.get("type") or "") if v.get("net") in ("xhttp", "grpc") else "",
    }
    if q["type"] == "xhttp" and q["mode"] in ("", "none"):
        q["mode"] = "auto"
    user = {"id": str(v["id"]), "security": str(v.get("scy") or "auto")}
    cfg = {
        "protocol": "vmess",
        "settings": {"vnext": [{"address": str(v["add"]), "port": _port(v.get("port")), "users": [user]}]},
        "streamSettings": _stream(q, address=str(v["add"])),
    }
    return cfg, str(v.get("ps") or "")


def _ss(link: str) -> tuple[dict[str, Any], str]:
    u = urlsplit(link)
    name = unquote(u.fragment)
    if "@" not in u.netloc:
        # Legacy: ss://base64(method:password@host:port)
        try:
            decoded = _b64(u.netloc).decode()
        except UnicodeDecodeError:
            raise LinkError("invalid shadowsocks link") from None
        u = urlsplit(f"ss://{decoded}")
        userinfo = u.netloc.rsplit("@", 1)[0]
        method, _, password = userinfo.partition(":")
    else:
        userinfo = u.netloc.rsplit("@", 1)[0]
        plain = unquote(userinfo)
        if ":" in plain:
            method, _, password = plain.partition(":")
        else:
            try:
                method, _, password = _b64(userinfo).decode().partition(":")
            except UnicodeDecodeError:
                raise LinkError("invalid shadowsocks link") from None
    if _query(u).get("plugin"):
        raise LinkError("shadowsocks plugins are not supported by Xray")
    if not method or not password:
        raise LinkError("invalid shadowsocks link")
    server = {"address": _host(u), "port": _uport(u), "method": method, "password": password}
    return {"protocol": "shadowsocks", "settings": {"servers": [server]}}, name


def _socks_http(link: str) -> tuple[dict[str, Any], str]:
    u = urlsplit(link)
    scheme = u.scheme.lower()
    protocol = "http" if scheme in ("http", "https") else "socks"
    server: dict[str, Any] = {"address": _host(u), "port": _uport(u, 443 if scheme == "https" else 80 if scheme == "http" else 1080)}
    user = unquote(u.username or "")
    password = unquote(u.password or "")
    if user and not password and protocol == "socks":
        try:  # v2rayN: socks://base64(user:pass)@host:port
            user, _, password = _b64(user).decode().partition(":")
        except (LinkError, UnicodeDecodeError):
            pass
    if user:
        server["users"] = [{"user": user, "pass": password}]
    cfg: dict[str, Any] = {"protocol": protocol, "settings": {"servers": [server]}}
    if scheme == "https":
        cfg["streamSettings"] = {"network": "tcp", "security": "tls", "tlsSettings": {"serverName": server["address"]}}
    return cfg, unquote(u.fragment)


def _wireguard(link: str) -> tuple[dict[str, Any], str]:
    u = urlsplit(link)
    q = _query(u)
    secret = unquote(u.username or "")
    public = q.get("publickey") or q.get("publicKey") or ""
    if not secret or not public:
        raise LinkError("wireguard link needs a private key and publickey")
    peer: dict[str, Any] = {"publicKey": public, "endpoint": f"{_host(u)}:{_uport(u)}"}
    if q.get("presharedkey"):
        peer["preSharedKey"] = q["presharedkey"]
    addresses = [a.strip() for a in (q.get("address") or q.get("ip") or "").split(",") if a.strip()]
    settings: dict[str, Any] = {"secretKey": secret, "address": addresses or ["172.16.0.2/32"], "peers": [peer], "mtu": int(q.get("mtu") or 1420)}
    if q.get("reserved"):
        try:
            settings["reserved"] = [int(x) for x in q["reserved"].split(",")]
        except ValueError:
            raise LinkError("invalid reserved") from None
    return {"protocol": "wireguard", "settings": settings}, unquote(u.fragment)


def parse_link(link: str) -> tuple[dict[str, Any], str]:
    """Share link → (Xray outbound without tag, remark from the link)."""
    link = link.strip()
    scheme = link.split("://", 1)[0].lower() if "://" in link else ""
    if scheme == "vmess":
        return _vmess(link)
    if scheme == "ss":
        return _ss(link)
    if scheme in ("socks", "socks5", "http", "https"):
        return _socks_http(link)
    if scheme in ("wireguard", "wg"):
        return _wireguard(link)
    if scheme not in ("vless", "trojan"):
        raise LinkError("unsupported link — use vless://, vmess://, trojan://, ss://, socks://, http(s):// or wireguard://")
    u = urlsplit(link)
    q = _query(u)
    secret = unquote(u.username or "")
    if not secret:
        raise LinkError("link has no user id / password")
    address, port = _host(u), _uport(u)
    stream = _stream(q, default_security="tls" if scheme == "trojan" else "none", address=address)
    if scheme == "vless":
        user: dict[str, Any] = {"id": secret, "encryption": q.get("encryption") or "none"}
        if q.get("flow"):
            user["flow"] = q["flow"]
        settings: dict[str, Any] = {"vnext": [{"address": address, "port": port, "users": [user]}]}
    else:
        settings = {"servers": [{"address": address, "port": port, "password": secret}]}
    return {"protocol": scheme, "settings": settings, "streamSettings": stream}, unquote(u.fragment)


def from_json(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept an outbound object, or a full config and take its first proxy outbound."""
    if "outbounds" in raw and "protocol" not in raw:
        obs = [o for o in raw.get("outbounds") or [] if isinstance(o, dict) and o.get("protocol") not in ("freedom", "blackhole", "dns")]
        if not obs:
            raise LinkError("config has no proxy outbound")
        raw = obs[0]
    if raw.get("protocol") not in OUTBOUND_PROTOCOLS:
        raise LinkError(f"protocol must be one of {', '.join(OUTBOUND_PROTOCOLS)}")
    cfg = {k: v for k, v in raw.items() if k in ("protocol", "settings", "streamSettings", "mux", "sendThrough", "targetStrategy")}
    return cfg


def summary(cfg: dict[str, Any]) -> dict[str, Any]:
    """Address / port / transport for display."""
    s = cfg.get("settings") or {}
    server = (s.get("vnext") or s.get("servers") or [{}])[0] if isinstance(s, dict) else {}
    address, port = server.get("address", ""), server.get("port")
    if cfg.get("protocol") == "wireguard":
        ep = ((s.get("peers") or [{}])[0].get("endpoint") or "")
        address, _, p = ep.rpartition(":")
        port = int(p) if p.isdigit() else None
    st = cfg.get("streamSettings") or {}
    return {"address": address, "port": port, "network": st.get("network", "tcp" if cfg.get("protocol") in ("vless", "vmess", "trojan") else ""), "security": st.get("security", "none")}


# ----------------------------------------------------------------------------- validation
def xray_test(config: dict[str, Any], xray_bin: str, assets: str) -> str | None:
    """Run `xray run -test` on a config. Returns an error message, or None when it is
    valid or no xray binary is available on the panel (the node validates again)."""
    if not (os.path.isfile(xray_bin) and os.access(xray_bin, os.X_OK)):
        return None
    env = {"PATH": "/usr/bin:/bin", "XRAY_LOCATION_ASSET": assets}
    try:
        p = subprocess.run([xray_bin, "run", "-test", "-c", "stdin:"], input=json.dumps(config).encode(), capture_output=True, timeout=20, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode == 0:
        return None
    out = (p.stdout + p.stderr).decode(errors="replace").strip().splitlines()
    lines = [line for line in out if "Reading config" not in line]
    msg = (lines[-1] if lines else "invalid configuration").split("> ")[-1]
    return msg[-400:]
