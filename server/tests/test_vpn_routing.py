"""Outbounds (share link → Xray outbound) and routing rules, including real traffic
chained through a second Xray node."""

import base64
import http.server
import json
import os
import subprocess
import threading

import httpx
import pytest
from conftest import enroll_agent
from test_vpn import HAVE_XRAY, XRAY
from test_vpn_e2e import _Hello, _port, _wait, link_to_outbound

from ipf3_server.services import outbound as ob

UUID = "0b3c5f5e-2a2b-4c1d-9b55-3c0e9f1a7d11"


def test_parse_vless_reality():
    cfg, name = ob.parse_link(
        f"vless://{UUID}@de.example.com:443?type=tcp&security=reality&sni=www.microsoft.com&fp=chrome&pbk=Abc_-123&sid=ab12&flow=xtls-rprx-vision#DE%201"
    )
    assert name == "DE 1"
    assert cfg["protocol"] == "vless"
    user = cfg["settings"]["vnext"][0]["users"][0]
    assert user == {"id": UUID, "encryption": "none", "flow": "xtls-rprx-vision"}
    st = cfg["streamSettings"]
    assert st["security"] == "reality" and st["realitySettings"]["password"] == "Abc_-123" and st["realitySettings"]["shortId"] == "ab12"
    assert ob.summary(cfg) == {"address": "de.example.com", "port": 443, "network": "tcp", "security": "reality"}


def test_parse_vmess_ws_tls():
    v = {"v": "2", "ps": "nl", "add": "nl.example.com", "port": "8443", "id": UUID, "aid": "0", "net": "ws", "type": "none",
         "host": "cdn.example.com", "path": "/ws", "tls": "tls", "sni": "cdn.example.com"}
    cfg, name = ob.parse_link("vmess://" + base64.b64encode(json.dumps(v).encode()).decode())
    assert name == "nl" and cfg["protocol"] == "vmess"
    assert cfg["settings"]["vnext"][0]["port"] == 8443
    assert cfg["streamSettings"]["wsSettings"] == {"path": "/ws", "host": "cdn.example.com"}
    assert cfg["streamSettings"]["tlsSettings"]["serverName"] == "cdn.example.com"


def test_parse_trojan_defaults_to_tls_and_grpc():
    cfg, _ = ob.parse_link("trojan://p%40ss@t.example.com:443?type=grpc&serviceName=svc&sni=t.example.com")
    assert cfg["settings"]["servers"][0]["password"] == "p@ss"
    assert cfg["streamSettings"]["security"] == "tls"
    assert cfg["streamSettings"]["grpcSettings"]["serviceName"] == "svc"


def test_parse_shadowsocks_formats():
    sip002 = "ss://" + base64.urlsafe_b64encode(b"aes-256-gcm:secret").decode().rstrip("=") + "@1.2.3.4:8388#ss"
    legacy = "ss://" + base64.b64encode(b"chacha20-ietf-poly1305:pw@5.6.7.8:443").decode()
    plain = "ss://2022-blake3-aes-128-gcm:a2V5a2V5a2V5a2V5a2V5aw%3D%3D@9.9.9.9:2053"
    s1 = ob.parse_link(sip002)[0]["settings"]["servers"][0]
    assert (s1["method"], s1["password"], s1["port"]) == ("aes-256-gcm", "secret", 8388)
    s2 = ob.parse_link(legacy)[0]["settings"]["servers"][0]
    assert (s2["address"], s2["method"], s2["password"]) == ("5.6.7.8", "chacha20-ietf-poly1305", "pw")
    s3 = ob.parse_link(plain)[0]["settings"]["servers"][0]
    assert s3["method"] == "2022-blake3-aes-128-gcm" and s3["password"] == "a2V5a2V5a2V5a2V5a2V5aw=="
    with pytest.raises(ob.LinkError):
        ob.parse_link("ss://YWVzLTI1Ni1nY206eA@1.2.3.4:1?plugin=obfs-local")


def test_parse_socks_http_wireguard():
    s = ob.parse_link("socks://dXNlcjpwYXNz@10.0.0.1:1080#s")[0]
    assert s["protocol"] == "socks" and s["settings"]["servers"][0]["users"] == [{"user": "user", "pass": "pass"}]
    h = ob.parse_link("https://u:p@proxy.example.com:8443")[0]
    assert h["protocol"] == "http" and h["streamSettings"]["security"] == "tls"
    w = ob.parse_link("wireguard://cHJpdmF0ZQ%3D%3D@engage.cloudflareclient.com:2408?publickey=cHVibGlj&address=172.16.0.2/32,2606:4700::2/128&reserved=1,2,3&mtu=1280#warp")[0]
    assert w["settings"]["peers"][0]["endpoint"] == "engage.cloudflareclient.com:2408"
    assert w["settings"]["reserved"] == [1, 2, 3] and w["settings"]["mtu"] == 1280
    assert len(w["settings"]["address"]) == 2


@pytest.mark.parametrize("bad", ["", "hello", "vless://@h:1", "vless://id@h:99999", "vless://id@h:443?type=h2", "vless://id@h:443?security=reality"])
def test_parse_rejects(bad):
    with pytest.raises(ob.LinkError):
        ob.parse_link(bad)


def test_from_json_takes_first_proxy_outbound():
    cfg = ob.from_json({"outbounds": [{"protocol": "freedom", "tag": "direct"}, {"protocol": "socks", "tag": "x", "settings": {"servers": [{"address": "1.1.1.1", "port": 1}]}}]})
    assert cfg == {"protocol": "socks", "settings": {"servers": [{"address": "1.1.1.1", "port": 1}]}}
    with pytest.raises(ob.LinkError):
        ob.from_json({"protocol": "dokodemo-door"})


# ----------------------------------------------------------------------------- API
async def test_outbound_and_rule_api(admin, anon, operator, viewer):
    a_id, ha = await enroll_agent(admin, anon, "node-a", tools={"xray": True})
    b_id, hb = await enroll_agent(admin, anon, "node-b", tools={"xray": True})
    ib = (await admin.post("/api/v1/vpn/inbounds", json={"agent_id": a_id, "remark": "a", "protocol": "vless", "port": 20001, "address": "a.example.com"})).json()

    r = await admin.post("/api/v1/vpn/outbounds", json={"link": f"vless://{UUID}@up.example.com:443?type=tcp&security=tls&sni=up.example.com#Upstream", "agent_ids": [a_id]})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["remark"] == "Upstream" and out["address"] == "up.example.com" and out["nodes"] == ["node-a"]
    assert (await operator.post("/api/v1/vpn/outbounds", json={"link": "socks://h:1"})).status_code == 403
    assert (await admin.post("/api/v1/vpn/outbounds", json={"link": "nope://x"})).status_code == 422
    assert (await admin.post("/api/v1/vpn/outbounds", json={"link": "socks://h:1", "config": {}})).status_code == 422
    assert (await admin.post("/api/v1/vpn/outbounds", json={"link": "socks://h:1", "agent_ids": ["missing"]})).status_code == 404
    # Viewers see the list but not credentials.
    listed = (await viewer.get("/api/v1/vpn/outbounds")).json()
    assert listed[0]["id"] == out["id"] and "link" not in listed[0]
    assert (await viewer.get(f"/api/v1/vpn/outbounds/{out['id']}")).status_code == 403
    assert UUID in (await admin.get(f"/api/v1/vpn/outbounds/{out['id']}")).json()["link"]

    rules = [
        {"remark": "iran direct", "action": "direct", "domains": ["geosite:category-ir", "domain:ir"], "ips": ["geoip:ir"]},
        {"remark": "ads", "action": "block", "domains": ["geosite:category-ads-all"]},
        {"remark": "via upstream", "action": "outbound", "outbound_id": out["id"], "inbound_ids": [ib["id"]], "port": "443, 80", "network": "tcp"},
        {"remark": "everything else", "action": "outbound", "outbound_id": out["id"]},
    ]
    ids = []
    for body in rules:
        r = await admin.post("/api/v1/vpn/routing", json=body)
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    assert (await admin.post("/api/v1/vpn/routing", json={"action": "outbound"})).status_code == 422
    assert (await admin.post("/api/v1/vpn/routing", json={"action": "direct", "ips": ["not-an-ip"]})).status_code == 422
    assert (await admin.post("/api/v1/vpn/routing", json={"action": "direct", "port": "70000"})).status_code == 422
    assert (await admin.post("/api/v1/vpn/routing", json={"action": "outbound", "outbound_id": 9999})).status_code == 404
    if HAVE_XRAY:
        r = await admin.post("/api/v1/vpn/routing", json={"action": "direct", "domains": ["geosite:this-list-does-not-exist"]})
        assert r.status_code == 422 and "Xray rejected" in r.text, r.text

    cfg_a = (await anon.get("/api/agent/v1/xray/config", headers=ha)).json()["config"]
    tags = [o["tag"] for o in cfg_a["outbounds"]]
    assert tags == ["direct", "blocked", f"out-{out['id']}"]
    custom = cfg_a["routing"]["rules"][3:]
    assert custom[0] == {"type": "field", "outboundTag": "direct", "domain": ["geosite:category-ir", "domain:ir"], "ip": ["geoip:ir"]}
    assert custom[1]["outboundTag"] == "blocked"
    assert custom[2] == {"type": "field", "outboundTag": f"out-{out['id']}", "inboundTag": [f"in-{ib['id']}"], "port": "443,80", "network": "tcp"}
    assert custom[3] == {"type": "field", "outboundTag": f"out-{out['id']}", "network": "tcp,udp"}
    # Node B doesn't have the outbound, so rules that use it are left out there.
    cfg_b = (await anon.get("/api/agent/v1/xray/config", headers=hb)).json()["config"]
    assert [o["tag"] for o in cfg_b["outbounds"]] == ["direct", "blocked"]
    assert [r["outboundTag"] for r in cfg_b["routing"]["rules"][3:]] == ["direct", "blocked"]
    if HAVE_XRAY:
        env = {"PATH": "/usr/bin:/bin", "XRAY_LOCATION_ASSET": os.path.dirname(XRAY)}
        for cfg in (cfg_a, cfg_b):
            p = subprocess.run([XRAY, "run", "-test", "-c", "stdin:"], input=json.dumps(cfg).encode(), capture_output=True, env=env, timeout=20)
            assert p.returncode == 0, p.stdout.decode()[-800:]

    # Reorder, toggle, then the outbound can't be deleted while rules use it.
    r = await admin.post("/api/v1/vpn/routing/order", json={"ids": list(reversed(ids))})
    assert [x["id"] for x in r.json()] == list(reversed(ids))
    assert (await admin.post("/api/v1/vpn/routing/order", json={"ids": ids[:2]})).status_code == 422
    cfg_a2 = (await anon.get("/api/agent/v1/xray/config", headers=ha)).json()["config"]
    assert cfg_a2["routing"]["rules"][3]["network"] == "tcp,udp"
    assert (await admin.delete(f"/api/v1/vpn/outbounds/{out['id']}")).status_code == 409
    body = {**rules[3], "enabled": False}
    assert (await admin.put(f"/api/v1/vpn/routing/{ids[3]}", json=body)).json()["enabled"] is False
    for rid in ids:
        assert (await admin.delete(f"/api/v1/vpn/routing/{rid}")).status_code == 204
    assert (await admin.delete(f"/api/v1/vpn/outbounds/{out['id']}")).status_code == 204


async def test_outbound_traffic_stats(admin, anon):
    agent_id, h = await enroll_agent(admin, anon, "node-s", tools={"xray": True})
    out = (await admin.post("/api/v1/vpn/outbounds", json={"link": "socks://10.1.1.1:1080#s"})).json()
    r = await anon.post("/api/agent/v1/xray/stats", headers=h, json={"outbounds": {f"out-{out['id']}": {"up": 10, "down": 2000}, "direct": {"up": 5, "down": 5}}})
    assert r.status_code == 204
    got = (await admin.get("/api/v1/vpn/outbounds")).json()[0]
    assert (got["up"], got["down"]) == (10, 2000)


@pytest.mark.skipif(not HAVE_XRAY, reason="xray binary not available")
async def test_invalid_outbound_rejected_by_xray(admin):
    r = await admin.post("/api/v1/vpn/outbounds", json={"link": "ss://bogus-cipher:pw@1.2.3.4:443"})
    assert r.status_code == 422 and "Xray rejected" in r.text, r.text


# ----------------------------------------------------------------------------- real traffic through a chained node
@pytest.mark.skipif(not HAVE_XRAY, reason="xray binary not available")
async def test_traffic_is_routed_through_outbound(admin, anon, operator, tmp_path):
    a_id, ha = await enroll_agent(admin, anon, "edge", tools={"xray": True})
    b_id, hb = await enroll_agent(admin, anon, "exit", tools={"xray": True})
    pa, pb = _port(), _port()
    for agent, port in ((a_id, pa), (b_id, pb)):
        r = await admin.post("/api/v1/vpn/inbounds", json={"agent_id": agent, "remark": f"n{port}", "protocol": "vless", "port": port, "address": "127.0.0.1"})
        assert r.status_code == 201, r.text
    user = (await operator.post("/api/v1/vpn/users", json={"username": "chain"})).json()
    links = (await operator.get(f"/api/v1/vpn/users/{user['id']}/links")).json()["links"]
    link_a = next(link for link in links if f":{pa}?" in link)
    link_b = next(link for link in links if f":{pb}?" in link)

    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Hello)
    blocked_web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Hello)
    for w in (web, blocked_web):
        threading.Thread(target=w.serve_forever, daemon=True).start()

    out = (await admin.post("/api/v1/vpn/outbounds", json={"link": link_b, "remark": "exit-node", "agent_ids": [a_id]})).json()
    assert (await admin.post("/api/v1/vpn/routing", json={"action": "block", "port": str(blocked_web.server_address[1])})).status_code == 201
    assert (await admin.post("/api/v1/vpn/routing", json={"action": "outbound", "outbound_id": out["id"]})).status_code == 201

    env = {**os.environ, "XRAY_LOCATION_ASSET": os.path.dirname(XRAY)}
    procs, api = [], {}
    try:
        for name, h in (("edge", ha), ("exit", hb)):
            cfg = (await anon.get("/api/agent/v1/xray/config", headers=h)).json()["config"]
            # Test servers live on 127.0.0.1, which production configs block on purpose.
            cfg["routing"]["rules"] = [r for r in cfg["routing"]["rules"] if "geoip:private" not in r.get("ip", [])]
            api[name] = _port()
            cfg["inbounds"][0]["port"] = api[name]
            (tmp_path / f"{name}.json").write_text(json.dumps(cfg))
            procs.append(subprocess.Popen([XRAY, "run", "-c", str(tmp_path / f"{name}.json")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env))
        sp = _port()
        client = {"log": {"loglevel": "warning"}, "inbounds": [{"listen": "127.0.0.1", "port": sp, "protocol": "socks"}], "outbounds": [link_to_outbound(link_a)]}
        (tmp_path / "client.json").write_text(json.dumps(client))
        procs.append(subprocess.Popen([XRAY, "run", "-c", str(tmp_path / "client.json")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env))
        for port in (pa, pb, sp):
            _wait(port)

        with httpx.Client(proxy=f"socks5://127.0.0.1:{sp}", timeout=15, trust_env=False) as c:
            r = c.get(f"http://127.0.0.1:{web.server_address[1]}/")
            assert r.status_code == 200 and len(r.content) == 50_000
            with pytest.raises(httpx.HTTPError):
                c.get(f"http://127.0.0.1:{blocked_web.server_address[1]}/")

        def stat(name: str, pattern: str) -> int:
            p = subprocess.run([XRAY, "api", "statsquery", "-s", f"127.0.0.1:{api[name]}", "-pattern", pattern], capture_output=True, text=True, timeout=10)
            return sum(int(s.get("value", 0)) for s in json.loads(p.stdout).get("stat", []) if s["name"].endswith("downlink"))

        # The edge node sent the request out through the outbound, and the exit node served it.
        assert stat("edge", f"outbound>>>out-{out['id']}>>>traffic") >= 50_000
        assert stat("exit", f"user>>>u{user['id']}>>>traffic") >= 50_000
        assert stat("edge", "outbound>>>direct>>>traffic") < 50_000
    except BaseException:
        for p in procs:
            p.kill()
            print("XRAY:", p.stdout.read().decode()[-2000:])
        raise
    finally:
        for p in procs:
            p.kill()
        web.shutdown()
        blocked_web.shutdown()
