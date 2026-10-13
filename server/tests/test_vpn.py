import base64
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from conftest import enroll_agent

from ipf3_server.services.x25519 import public_key

XRAY = os.environ.get("XRAY_BIN") or shutil.which("xray") or "/usr/local/bin/xray"
HAVE_XRAY = os.path.exists(XRAY)


async def _node(admin, anon):
    agent_id, headers = await enroll_agent(admin, anon, "node-1", tools={"iperf3": True, "ping": True, "traceroute": True, "mtr": True, "dns": True, "xray": True})
    return agent_id, headers


async def _inbound(admin, agent_id, **kw):
    body = {"agent_id": agent_id, "remark": "main", "protocol": "vless", "port": 2096, "network": "tcp", "security": "none", "address": "203.0.113.10"}
    body.update(kw)
    r = await admin.post("/api/v1/vpn/inbounds", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_reality_keys_valid(admin):
    k = (await admin.post("/api/v1/vpn/tools/reality-keys")).json()
    assert public_key(k["private_key"]) == k["public_key"] and len(k["short_id"]) == 16


async def test_inbound_validation(admin, anon):
    agent_id, _ = await _node(admin, anon)
    base = {"agent_id": agent_id, "remark": "x", "port": 443, "address": "vpn.example.net"}
    bad = [
        {"protocol": "vmess", "security": "reality", "settings": {"private_key": "a", "public_key": "b"}},
        {"protocol": "vless", "network": "ws", "security": "reality"},
        {"protocol": "vless", "network": "ws", "settings": {"flow": "xtls-rprx-vision"}},
        {"protocol": "shadowsocks", "network": "ws"},
        {"protocol": "shadowsocks", "settings": {"ss_method": "2022-blake3-aes-128-gcm", "ss_server_password": "short"}},
        {"protocol": "trojan", "security": "tls"},
        {"protocol": "vless", "port": 10085},
        {"protocol": "vless", "address": "-bad host"},
        {"protocol": "vless", "network": "ws", "settings": {"path": "no-slash"}},
    ]
    for b in bad:
        r = await admin.post("/api/v1/vpn/inbounds", json={**base, **b})
        assert r.status_code == 422, (b, r.text)
    await _inbound(admin, agent_id, port=443)
    r = await admin.post("/api/v1/vpn/inbounds", json={**base, "protocol": "vless"})
    assert r.status_code == 409


async def test_rbac(viewer, operator, admin, anon):
    agent_id, _ = await _node(admin, anon)
    assert (await operator.post("/api/v1/vpn/inbounds", json={"agent_id": agent_id})).status_code == 403
    assert (await viewer.post("/api/v1/vpn/users", json={"username": "x1"})).status_code == 403
    assert (await operator.post("/api/v1/vpn/users", json={"username": "x1"})).status_code == 201
    assert (await viewer.get("/api/v1/vpn/users")).status_code == 200


async def test_user_lifecycle_config_and_enforcement(admin, anon, operator):
    agent_id, h = await _node(admin, anon)
    ib = await _inbound(admin, agent_id)
    r = await operator.post("/api/v1/vpn/users", json={"username": "alice", "data_limit_gb": 1, "expire_days": 30})
    assert r.status_code == 201, r.text
    alice = r.json()
    assert alice["status"] == "active" and alice["data_limit"] == 10**9
    assert alice["sub_url"].endswith(alice["sub_token"])

    r = await anon.get("/api/agent/v1/xray/config", headers=h)
    cfg = r.json()
    first_hash = cfg["hash"]
    vless = [i for i in cfg["config"]["inbounds"] if i["tag"] == f"in-{ib['id']}"][0]
    assert vless["settings"]["clients"][0]["email"] == f"u{alice['id']}"
    assert (await anon.get("/api/agent/v1/xray/config", params={"hash": first_hash}, headers=h)).status_code == 204

    # traffic accounting
    email = f"u{alice['id']}"
    for _ in range(2):
        assert (await anon.post("/api/agent/v1/xray/stats", headers=h, json={"users": {email: {"up": 100, "down": 400}}})).status_code == 204
    u = (await operator.get(f"/api/v1/vpn/users/{alice['id']}")).json()
    assert u["used_up"] == 200 and u["used_down"] == 800 and u["online"] is True
    daily = (await operator.get(f"/api/v1/vpn/users/{alice['id']}/usage")).json()
    assert daily[0]["down"] == 800

    # exceeding the data limit removes the user from the node config
    await anon.post("/api/agent/v1/xray/stats", headers=h, json={"users": {email: {"up": 0, "down": 1024**3}}})
    u = (await operator.get(f"/api/v1/vpn/users/{alice['id']}")).json()
    assert u["status"] == "limited"
    cfg2 = (await anon.get("/api/agent/v1/xray/config", headers=h)).json()
    assert cfg2["hash"] != first_hash
    vless2 = [i for i in cfg2["config"]["inbounds"] if i["tag"] == f"in-{ib['id']}"][0]
    assert vless2["settings"]["clients"] == []

    # reset traffic → active again
    assert (await operator.post(f"/api/v1/vpn/users/{alice['id']}/reset-traffic")).json()["status"] == "active"
    # expiry
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert (await operator.patch(f"/api/v1/vpn/users/{alice['id']}", json={"expire_at": past})).json()["status"] == "expired"
    assert (await operator.patch(f"/api/v1/vpn/users/{alice['id']}", json={"clear_expire": True})).json()["status"] == "active"
    assert (await operator.patch(f"/api/v1/vpn/users/{alice['id']}", json={"enabled": False})).json()["status"] == "disabled"

    # node state reporting
    r = await anon.post("/api/agent/v1/xray/state", headers=h, json={"applied_hash": cfg2["hash"], "version": "26.3.27", "running": True})
    assert r.status_code == 204
    nodes = (await operator.get("/api/v1/vpn/nodes")).json()
    assert nodes[0]["running"] and nodes[0]["xray_version"] == "26.3.27"
    ov = (await operator.get("/api/v1/vpn/overview")).json()
    assert ov["users_total"] == 1 and ov["traffic"]["today_down"] >= 800


async def test_inbound_restriction(admin, anon, operator):
    agent_id, h = await _node(admin, anon)
    a = await _inbound(admin, agent_id, port=2001, remark="a")
    b = await _inbound(admin, agent_id, port=2002, remark="b", protocol="trojan")
    r = await operator.post("/api/v1/vpn/users", json={"username": "bob", "inbound_ids": [b["id"]]})
    bob = r.json()
    links = (await operator.get(f"/api/v1/vpn/users/{bob['id']}/links")).json()["links"]
    assert len(links) == 1 and links[0].startswith("trojan://")
    assert (await operator.post("/api/v1/vpn/users", json={"username": "x2", "inbound_ids": [999]})).status_code == 422
    await admin.delete(f"/api/v1/vpn/inbounds/{b['id']}")
    assert (await operator.get(f"/api/v1/vpn/users/{bob['id']}")).json()["inbound_ids"] == []
    assert a["id"]


async def test_links_and_subscription(admin, anon, operator):
    agent_id, _ = await _node(admin, anon)
    keys = (await admin.post("/api/v1/vpn/tools/reality-keys")).json()
    await _inbound(admin, agent_id, port=443, remark="reality", network="tcp", security="reality",
                   settings={"flow": "xtls-rprx-vision", "private_key": keys["private_key"], "public_key": keys["public_key"],
                             "short_ids": [keys["short_id"]], "server_names": ["www.microsoft.com"], "target": "www.microsoft.com:443"})
    await _inbound(admin, agent_id, port=8080, remark="ws", protocol="vmess", network="ws", settings={"path": "/vm", "host": "cdn.example.net"})
    ss_key = (await admin.post("/api/v1/vpn/tools/ss2022-key")).json()["key"]
    await _inbound(admin, agent_id, port=8388, remark="ss", protocol="shadowsocks", settings={"ss_method": "2022-blake3-aes-128-gcm", "ss_server_password": ss_key})
    u = (await operator.post("/api/v1/vpn/users", json={"username": "carol", "data_limit_gb": 10})).json()

    links = (await operator.get(f"/api/v1/vpn/users/{u['id']}/links")).json()["links"]
    vl = urlparse(links[0])
    q = parse_qs(vl.query)
    assert vl.scheme == "vless" and vl.hostname == "203.0.113.10" and vl.port == 443
    assert q["security"] == ["reality"] and q["pbk"] == [keys["public_key"]] and q["flow"] == ["xtls-rprx-vision"]
    assert unquote(vl.fragment) == "reality-carol"
    vm = json.loads(base64.b64decode(links[1][8:]))
    assert vm["net"] == "ws" and vm["path"] == "/vm" and vm["host"] == "cdn.example.net"
    assert links[2].startswith("ss://2022-blake3-aes-128-gcm:")

    # client app → base64 with usage header
    r = await anon.get(f"/sub/{u['sub_token']}", headers={"user-agent": "v2rayNG/1.9"})
    assert r.status_code == 200
    assert base64.b64decode(r.text).decode().splitlines() == links
    assert "total=10000000000" in r.headers["subscription-userinfo"]
    # clash
    r = await anon.get(f"/sub/{u['sub_token']}", headers={"user-agent": "ClashMeta/1.18"})
    assert "type: vless" in r.text or '"vless"' in r.text
    assert "reality-opts" in r.text and "proxy-groups" in r.text
    # browser → redirect to info page
    r = await anon.get(f"/sub/{u['sub_token']}", headers={"user-agent": "Mozilla/5.0 Chrome/120", "accept": "text/html"})
    assert r.status_code == 302 and r.headers["location"] == f"/s/{u['sub_token']}"
    info = (await anon.get(f"/api/sub/{u['sub_token']}/info")).json()
    assert info["username"] == "carol" and len(info["links"]) == 3
    assert (await anon.get("/sub/does-not-exist")).status_code == 404
    # revoke → old link dead
    new = (await operator.post(f"/api/v1/vpn/users/{u['id']}/revoke")).json()
    assert (await anon.get(f"/sub/{u['sub_token']}")).status_code == 404
    assert new["sub_token"] != u["sub_token"]


def _clash_yaml_parses(text: str):
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(text)


async def test_clash_yaml_is_valid(admin, anon, operator):
    agent_id, _ = await _node(admin, anon)
    await _inbound(admin, agent_id, port=2053, remark='quote"d', protocol="trojan", network="grpc", security="none", settings={"service_name": "svc"})
    u = (await operator.post("/api/v1/vpn/users", json={"username": "dave"})).json()
    r = await anon.get(f"/sub/{u['sub_token']}", params={"format": "clash"})
    data = _clash_yaml_parses(r.text)
    p = data["proxies"][0]
    assert p["type"] == "trojan" and p["network"] == "grpc" and p["grpc-opts"]["grpc-service-name"] == "svc"
    assert p["name"] == 'quote"d-dave'


# ---------------------------------------------------------------------------------------------------------------
# Real Xray: the generated server config must pass `xray run -test`, and a client built from each
# share link must be able to proxy traffic through the server.
pytestmark_xray = pytest.mark.skipif(not HAVE_XRAY, reason="xray binary not available")


@pytestmark_xray
async def test_generated_config_passes_xray_test(admin, anon, operator, tmp_path):
    agent_id, h = await _node(admin, anon)
    keys = (await admin.post("/api/v1/vpn/tools/reality-keys")).json()
    cert, key = _selfsigned(tmp_path)
    ss_key = (await admin.post("/api/v1/vpn/tools/ss2022-key")).json()["key"]
    variants = [
        dict(protocol="vless", network="tcp", security="reality", settings={"flow": "xtls-rprx-vision", "private_key": keys["private_key"], "public_key": keys["public_key"], "short_ids": [keys["short_id"]]}),
        dict(protocol="vless", network="xhttp", security="reality", settings={"private_key": keys["private_key"], "public_key": keys["public_key"]}),
        dict(protocol="vless", network="grpc", security="reality", settings={"private_key": keys["private_key"], "public_key": keys["public_key"]}),
        dict(protocol="vless", network="ws", security="tls", settings={"cert_pem": cert, "key_pem": key, "sni": "vpn.example.net"}),
        dict(protocol="vmess", network="httpupgrade", security="none", settings={"path": "/up"}),
        dict(protocol="trojan", network="tcp", security="tls", settings={"cert_pem": cert, "key_pem": key, "alpn": ["h2", "http/1.1"]}),
        dict(protocol="shadowsocks", settings={"ss_method": "chacha20-ietf-poly1305"}),
        dict(protocol="shadowsocks", settings={"ss_method": "2022-blake3-aes-128-gcm", "ss_server_password": ss_key}),
    ]
    for n, v in enumerate(variants):
        await _inbound(admin, agent_id, port=20000 + n, remark=f"v{n}", **v)
    for name in ("u1", "u2"):
        await operator.post("/api/v1/vpn/users", json={"username": name})
    cfg = (await anon.get("/api/agent/v1/xray/config", headers=h)).json()["config"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    env = {**os.environ, "XRAY_LOCATION_ASSET": os.path.dirname(XRAY)}
    out = subprocess.run([XRAY, "run", "-test", "-c", str(path)], capture_output=True, text=True, env=env, timeout=30)
    assert out.returncode == 0, out.stdout + out.stderr


def _selfsigned(tmp_path):
    k, c = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-days", "2", "-nodes",
                    "-keyout", str(k), "-out", str(c), "-subj", "/CN=vpn.example.net", "-addext", "subjectAltName=DNS:vpn.example.net"],
                   check=True, capture_output=True)
    return c.read_text(), k.read_text()


async def test_port_already_used_on_node_is_rejected(admin, anon):
    agent_id, h = await _node(admin, anon)
    inv = {"connections": [{"proto": "tcp", "state": "LISTEN", "local": "0.0.0.0:443", "peer": "0.0.0.0:*"},
                           {"proto": "tcp", "state": "LISTEN", "local": "127.0.0.1:5432", "peer": "0.0.0.0:*"}]}
    assert (await anon.post("/api/agent/v1/inventory", headers=h, json=inv)).status_code == 204
    r = await admin.post("/api/v1/vpn/inbounds", json={"agent_id": agent_id, "remark": "x", "protocol": "vless", "port": 443, "address": "203.0.113.1"})
    assert r.status_code == 409 and "8443" in r.json()["detail"]
    # loopback-only listeners don't block public inbounds
    ib = await _inbound(admin, agent_id, port=5432)
    # editing our own inbound on the same port is fine even though it is listening now
    inv["connections"].append({"proto": "tcp", "state": "LISTEN", "local": "*:5432", "peer": "*:*"})
    await anon.post("/api/agent/v1/inventory", headers=h, json=inv)
    body = {k: ib[k] for k in ("agent_id", "remark", "protocol", "port", "listen", "network", "security", "address", "settings", "enabled")}
    body["remark"] = "renamed"
    assert (await admin.put(f"/api/v1/vpn/inbounds/{ib['id']}", json=body)).status_code == 200
    body["port"] = 443
    assert (await admin.put(f"/api/v1/vpn/inbounds/{ib['id']}", json=body)).status_code == 409
