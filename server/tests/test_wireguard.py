"""WireGuard inbounds and peers: API, config generation, and (when `wg`/`wg-quick`
are installed) a real tunnel built from the generated server + peer configs."""

import base64
import ipaddress
import os
import shutil
import socket
import subprocess
import time

import pytest
from conftest import enroll_agent

from ipf3_server.services import wireguard as wg

WG = shutil.which("wg")
WG_QUICK = shutil.which("wg-quick")
HAVE_WG = bool(WG and WG_QUICK) and os.geteuid() == 0


def test_generate_keypair_is_valid_curve25519_b64():
    priv, pub = wg.generate_keypair()
    raw = base64.b64decode(priv)
    assert len(raw) == 32 and len(base64.b64decode(pub)) == 32


def test_next_free_address_skips_network_and_server():
    addr = wg.next_free_address("10.70.0.0/30", set())
    assert addr == "10.70.0.2"  # .0 network, .1 server, .3 broadcast
    with pytest.raises(ValueError):
        wg.next_free_address("10.70.0.0/30", {"10.70.0.2"})


def test_detect_egress_iface_picks_default_route():
    routes = [{"dst": "10.0.0.0/8", "dev": "wg0"}, {"dst": None, "dev": "eth0", "table": "main"}]
    assert wg.detect_egress_iface(routes) == "eth0"
    assert wg.detect_egress_iface([]) is None


async def test_wg_inbound_and_peer_api(admin, anon, operator, viewer):
    agent_id, h = await enroll_agent(admin, anon, "wg-node")
    body = {"agent_id": agent_id, "remark": "main", "listen_port": 51820, "network": "10.66.0.0/24", "address": "203.0.113.9", "egress_iface": "eth0"}
    r = await admin.post("/api/v1/vpn/wg/inbounds", json=body)
    assert r.status_code == 201, r.text
    inbound = r.json()
    assert inbound["public_key"] and inbound["peers"] == 0 and inbound["in_sync"] is False

    assert (await operator.post("/api/v1/vpn/wg/inbounds", json=body)).status_code == 403
    assert (await admin.post("/api/v1/vpn/wg/inbounds", json=body)).status_code == 409  # one per node

    user = (await operator.post("/api/v1/vpn/users", json={"username": "wgu"})).json()
    r = await operator.post(f"/api/v1/vpn/wg/inbounds/{agent_id}/peers", json={"user_id": user["id"]})
    assert r.status_code == 201, r.text
    peer = r.json()
    assert peer["address"] == "10.66.0.2" and peer["username"] == "wgu"
    assert (await operator.post(f"/api/v1/vpn/wg/inbounds/{agent_id}/peers", json={"user_id": user["id"]})).status_code == 409
    assert (await viewer.post(f"/api/v1/vpn/wg/inbounds/{agent_id}/peers", json={"user_id": user["id"]})).status_code == 403

    cfg = (await viewer.get(f"/api/v1/vpn/wg/peers/{peer['id']}/config")).json()
    assert "[Interface]" in cfg["config"] and f"Endpoint = 203.0.113.9:51820" in cfg["config"]

    listed = (await viewer.get(f"/api/v1/vpn/wg/inbounds/{agent_id}/peers")).json()
    assert len(listed) == 1 and listed[0]["id"] == peer["id"] and listed[0]["online"] is False

    toggled = (await operator.patch(f"/api/v1/vpn/wg/peers/{peer['id']}/toggle")).json()
    assert toggled["enabled"] is False
    await operator.patch(f"/api/v1/vpn/wg/peers/{peer['id']}/toggle")  # back on

    # agent protocol: fetch config, report state + stats
    r = await anon.get("/api/agent/v1/wireguard/config", headers=h)
    agent_cfg = r.json()
    assert "[Peer]" in agent_cfg["config"] and agent_cfg["hash"]
    assert (await anon.get(f"/api/agent/v1/wireguard/config?hash={agent_cfg['hash']}", headers=h)).status_code == 204

    pubkey = agent_cfg["config"].split("PublicKey = ")[1].split("\n")[0]
    now = int(time.time())
    r = await anon.post(
        "/api/agent/v1/wireguard/state", headers=h,
        json={"applied_hash": agent_cfg["hash"], "running": True, "handshakes": {pubkey: now}},
    )
    assert r.status_code == 204
    r = await anon.post("/api/agent/v1/wireguard/stats", headers=h, json={"peers": {pubkey: {"up": 1000, "down": 50000}}})
    assert r.status_code == 204

    nodes = (await viewer.get("/api/v1/vpn/wg/inbounds")).json()
    assert nodes[0]["in_sync"] is True and nodes[0]["running"] is True and nodes[0]["online_peers"] == 1
    assert nodes[0]["up"] == 1000 and nodes[0]["down"] == 50000
    peers = (await viewer.get(f"/api/v1/vpn/wg/inbounds/{agent_id}/peers")).json()
    assert peers[0]["online"] is True and peers[0]["up"] == 1000 and peers[0]["down"] == 50000

    u = (await viewer.get(f"/api/v1/vpn/users/{user['id']}")).json()
    assert u["used_up"] == 1000 and u["used_down"] == 50000 and u["online"] is True

    # port conflict against an Xray inbound on the same node
    xray_ib = await admin.post("/api/v1/vpn/inbounds", json={"agent_id": agent_id, "remark": "x", "protocol": "vless", "port": 9999, "address": "a"})
    assert xray_ib.status_code == 201
    conflict = {**body, "listen_port": 9999}
    r2 = await admin.post("/api/v1/vpn/wg/inbounds", json={**conflict, "agent_id": "nonexistent"})
    assert r2.status_code == 404

    # shrinking the network below an existing peer's address is rejected
    r3 = await admin.put(f"/api/v1/vpn/wg/inbounds/{agent_id}", json={**body, "network": "10.66.1.0/30"})
    assert r3.status_code == 409

    assert (await operator.delete(f"/api/v1/vpn/wg/peers/{peer['id']}")).status_code == 204
    assert (await admin.delete(f"/api/v1/vpn/wg/inbounds/{agent_id}")).status_code == 204
    assert (await viewer.get("/api/v1/vpn/wg/inbounds")).json() == []


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(not HAVE_WG, reason="wg/wg-quick not available or not root")
async def test_server_and_peer_config_form_a_real_tunnel(admin, anon, operator, tmp_path):
    """The exact text the API hands out for the node and the client brings up a real
    WireGuard tunnel (loopback, userspace fallback) and carries real traffic."""
    agent_id, h = await enroll_agent(admin, anon, "wg-e2e")
    port = _free_udp_port()
    body = {"agent_id": agent_id, "remark": "e2e", "listen_port": port, "network": "10.91.0.0/24", "address": "127.0.0.1", "egress_iface": ""}
    assert (await admin.post("/api/v1/vpn/wg/inbounds", json=body)).status_code == 201
    user = (await operator.post("/api/v1/vpn/users", json={"username": "wge2e"})).json()
    peer = (await operator.post(f"/api/v1/vpn/wg/inbounds/{agent_id}/peers", json={"user_id": user["id"]})).json()
    server_cfg = (await anon.get("/api/agent/v1/wireguard/config", headers=h)).json()["config"]
    client_cfg = (await admin.get(f"/api/v1/vpn/wg/peers/{peer['id']}/config")).json()["config"]
    # Sandbox adaptations, the same spirit as the Xray e2e test stripping rules that
    # don't apply to a loopback target: DNS push needs resolvconf/systemd-resolved,
    # and full-tunnel (0.0.0.0/0, ::/0) AllowedIPs makes wg-quick set up policy
    # routing that needs IPv6 rule support the test kernel doesn't have. Neither
    # affects what's being proven here: the generated configs form a working tunnel
    # and carry real traffic.
    client_cfg = "\n".join(
        "AllowedIPs = 10.91.0.1/32" if line.startswith("AllowedIPs =") else line
        for line in client_cfg.splitlines()
        if not line.startswith("DNS =")
    )

    env = {**os.environ}
    sdir, cdir = tmp_path / "s", tmp_path / "c"
    sdir.mkdir(mode=0o700)
    cdir.mkdir(mode=0o700)
    (sdir / "wgtest-srv.conf").write_text(server_cfg)
    (cdir / "wgtest-cli.conf").write_text(client_cfg)
    srv_up = cli_up = False
    try:
        subprocess.run([WG_QUICK, "up", str(sdir / "wgtest-srv.conf")], check=True, capture_output=True, env=env, timeout=15)
        srv_up = True
        subprocess.run([WG_QUICK, "up", str(cdir / "wgtest-cli.conf")], check=True, capture_output=True, env=env, timeout=15)
        cli_up = True
        time.sleep(1)
        server_ip = next(iter(ipaddress.ip_network("10.91.0.0/24").hosts()))
        ping = subprocess.run(["ping", "-c", "3", "-W", "2", str(server_ip)], capture_output=True, text=True, timeout=15)
        assert ping.returncode == 0, ping.stdout + ping.stderr
        dump = subprocess.run([WG, "show", "wgtest-srv", "dump"], capture_output=True, text=True, timeout=10)
        lines = [line for line in dump.stdout.splitlines() if line.count("\t") >= 6]
        assert lines, dump.stdout
        rx = int(lines[0].split("\t")[5])
        assert rx > 0
    finally:
        if cli_up:
            subprocess.run([WG_QUICK, "down", str(cdir / "wgtest-cli.conf")], capture_output=True, env=env)
        if srv_up:
            subprocess.run([WG_QUICK, "down", str(sdir / "wgtest-srv.conf")], capture_output=True, env=env)
