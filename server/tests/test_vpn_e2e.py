"""End-to-end: a real Xray server runs the generated config, a real Xray client is
built from each subscription link, and HTTP traffic must flow through it. Traffic
statistics must then appear in Xray's StatsService under the user's identifier."""

import base64
import http.server
import json
import os
import socket
import subprocess
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest
from conftest import enroll_agent
from test_vpn import HAVE_XRAY, XRAY, _selfsigned

pytestmark = pytest.mark.skipif(not HAVE_XRAY, reason="xray binary not available")


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(port: int, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise TimeoutError(f"port {port} not listening")


PINNED = {"sha256": ""}


def link_to_outbound(link: str) -> dict:
    """Independent parser for share links -> Xray client outbound (validates the links)."""
    if link.startswith("vmess://"):
        v = json.loads(base64.b64decode(link[8:]))
        stream = {"network": v["net"], "security": "tls" if v["tls"] else "none"}
        if v["net"] == "httpupgrade":
            stream["httpupgradeSettings"] = {"path": v["path"], "host": v["host"]}
        if v["net"] == "ws":
            stream["wsSettings"] = {"path": v["path"], "host": v["host"]}
        return {"protocol": "vmess", "settings": {"vnext": [{"address": v["add"], "port": int(v["port"]), "users": [{"id": v["id"], "security": "auto"}]}]}, "streamSettings": stream}
    u = urlparse(link)
    if u.scheme == "ss":
        userinfo = u.netloc.rsplit("@", 1)[0]
        if ":" in unquote(userinfo) and userinfo.startswith("2022"):
            method, password = unquote(userinfo).split(":", 1)
        else:
            method, password = base64.urlsafe_b64decode(userinfo + "=" * (-len(userinfo) % 4)).decode().split(":", 1)
        return {"protocol": "shadowsocks", "settings": {"servers": [{"address": u.hostname, "port": u.port, "method": method, "password": password}]}}
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    net, sec = q["type"], q["security"]
    stream: dict = {"network": net, "security": sec}
    if net in ("ws", "httpupgrade", "xhttp"):
        stream[f"{net}Settings"] = {"path": q.get("path", "/"), "host": q.get("host", "")}
        if net == "xhttp":
            stream["xhttpSettings"]["mode"] = q.get("mode", "auto")
    if net == "grpc":
        stream["grpcSettings"] = {"serviceName": q["serviceName"]}
    if sec == "tls":
        stream["tlsSettings"] = {"serverName": q.get("sni", ""), "fingerprint": q.get("fp", "chrome"), "pinnedPeerCertSha256": PINNED["sha256"]}
        if q.get("alpn"):
            stream["tlsSettings"]["alpn"] = q["alpn"].split(",")
    if sec == "reality":
        stream["realitySettings"] = {"serverName": q["sni"], "fingerprint": q["fp"], "password": q["pbk"], "shortId": q.get("sid", ""), "spiderX": q.get("spx", "/")}
    if u.scheme == "vless":
        user = {"id": u.username, "encryption": "none"}
        if q.get("flow"):
            user["flow"] = q["flow"]
        return {"protocol": "vless", "settings": {"vnext": [{"address": u.hostname, "port": u.port, "users": [user]}]}, "streamSettings": stream}
    return {"protocol": "trojan", "settings": {"servers": [{"address": u.hostname, "port": u.port, "password": unquote(u.username)}]}, "streamSettings": stream}


class _Hello(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"x" * 50_000
        self.send_response(200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


async def test_traffic_flows_through_every_protocol(admin, anon, operator, tmp_path):
    agent_id, h = await enroll_agent(admin, anon, "node-e2e", tools={"xray": True})
    cert, key = _selfsigned(tmp_path)
    import hashlib
    import ssl as _ssl

    PINNED["sha256"] = hashlib.sha256(_ssl.PEM_cert_to_DER_cert(cert)).hexdigest()
    keys = (await admin.post("/api/v1/vpn/tools/reality-keys")).json()
    ss_key = (await admin.post("/api/v1/vpn/tools/ss2022-key")).json()["key"]

    # Local TLS 1.3 site used as the REALITY target (stands in for e.g. www.microsoft.com).
    target_port = _port()
    (tmp_path / "t.crt").write_text(cert)
    (tmp_path / "t.key").write_text(key)
    target = subprocess.Popen(["openssl", "s_server", "-accept", str(target_port), "-cert", str(tmp_path / "t.crt"), "-key", str(tmp_path / "t.key"),
                               "-tls1_3", "-www", "-quiet"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    reality = {"private_key": keys["private_key"], "public_key": keys["public_key"], "short_ids": [keys["short_id"]],
               "server_names": ["vpn.example.net"], "target": f"127.0.0.1:{target_port}"}
    variants = {
        "vless-reality-vision": dict(protocol="vless", network="tcp", security="reality", settings={**reality, "flow": "xtls-rprx-vision"}),
        "vless-reality-xhttp": dict(protocol="vless", network="xhttp", security="reality", settings=reality),
        "vless-reality-grpc": dict(protocol="vless", network="grpc", security="reality", settings=reality),
        "vless-ws-tls": dict(protocol="vless", network="ws", security="tls", settings={"cert_pem": cert, "key_pem": key, "sni": "vpn.example.net", "path": "/ws"}),
        "vmess-httpupgrade": dict(protocol="vmess", network="httpupgrade", security="none", settings={"path": "/up"}),
        "trojan-tls": dict(protocol="trojan", network="tcp", security="tls", settings={"cert_pem": cert, "key_pem": key, "sni": "vpn.example.net"}),
        "ss-aead": dict(protocol="shadowsocks", settings={"ss_method": "aes-256-gcm"}),
        "ss-2022": dict(protocol="shadowsocks", settings={"ss_method": "2022-blake3-aes-128-gcm", "ss_server_password": ss_key}),
    }
    for name, v in variants.items():
        r = await admin.post("/api/v1/vpn/inbounds", json={"agent_id": agent_id, "remark": name, "port": _port(), "address": "127.0.0.1", **v})
        assert r.status_code == 201, r.text
    user = (await operator.post("/api/v1/vpn/users", json={"username": "tester"})).json()
    links = (await operator.get(f"/api/v1/vpn/users/{user['id']}/links")).json()["links"]
    assert len(links) == len(variants)

    cfg = (await anon.get("/api/agent/v1/xray/config", headers=h)).json()["config"]
    # The test web server lives on 127.0.0.1, which production configs block on purpose.
    cfg["routing"]["rules"] = [r for r in cfg["routing"]["rules"] if "geoip:private" not in r.get("ip", [])]
    api_port = _port()
    cfg["inbounds"][0]["port"] = api_port
    (tmp_path / "server.json").write_text(json.dumps(cfg))
    env = {**os.environ, "XRAY_LOCATION_ASSET": os.path.dirname(XRAY)}
    server = subprocess.Popen([XRAY, "run", "-c", str(tmp_path / "server.json")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)

    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Hello)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    web_url = f"http://127.0.0.1:{web.server_address[1]}/"

    clients = []
    try:
        for i in cfg["inbounds"][1:]:
            _wait(i["port"])
        socks = {}
        for name, link in zip(variants, links):
            sp = _port()
            ccfg = {"log": {"loglevel": "warning"}, "inbounds": [{"listen": "127.0.0.1", "port": sp, "protocol": "socks", "settings": {"udp": False}}],
                    "outbounds": [link_to_outbound(link)]}
            p = tmp_path / f"client-{name}.json"
            p.write_text(json.dumps(ccfg))
            clients.append(subprocess.Popen([XRAY, "run", "-c", str(p)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env))
            socks[name] = sp
        failures = {}
        for name, sp in socks.items():
            _wait(sp)
            try:
                with httpx.Client(proxy=f"socks5://127.0.0.1:{sp}", timeout=15, trust_env=False) as c:
                    r = c.get(web_url)
                assert r.status_code == 200 and len(r.content) == 50_000
            except Exception as e:  # noqa: BLE001
                failures[name] = repr(e)
        assert not failures, failures

        # Per-user statistics exist and are attributed to the user's stable id.
        out = subprocess.run([XRAY, "api", "statsquery", "-s", f"127.0.0.1:{api_port}", "-pattern", "user>>>"], capture_output=True, text=True, timeout=10)
        stats = json.loads(out.stdout)["stat"]
        down = sum(int(s.get("value", 0)) for s in stats if s["name"] == f"user>>>u{user['id']}>>>traffic>>>downlink")
        assert down >= 50_000 * len(variants)
    except BaseException:
        server.kill()
        for p in clients:
            p.kill()
        print("SERVER:", server.stdout.read().decode()[-3000:])
        for p in clients:
            print("CLIENT:", p.stdout.read().decode()[-1500:])
        raise
    finally:
        for p in clients:
            p.kill()
        server.kill()
        target.kill()
        web.shutdown()
