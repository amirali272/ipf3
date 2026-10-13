"""Connected IPs (reported by nodes) and client apps (from subscription fetches)."""

import time

import pytest
from conftest import enroll_agent

from ipf3_server.services.clients import parse_user_agent


@pytest.mark.parametrize(
    "ua,expected",
    [
        ("v2rayNG/1.9.16", ("v2rayNG", "1.9.16")),
        ("v2rayN/7.4.2", ("v2rayN", "7.4.2")),
        ("HiddifyNext/2.5.7 (android) like ClashMeta v2ray sing-box", ("Hiddify", "2.5.7")),
        ("Streisand/1.6.30 CFNetwork/1498.700.2 Darwin/23.6.0", ("Streisand", "1.6.30")),
        ("ClashMetaForAndroid/2.11.1.Meta", ("Clash Meta", "2.11.1")),
        ("Happ/1.8.0", ("Happ", "1.8.0")),
        ("SFA/1.10.1 (sing-box 1.10.1)", ("sing-box", "1.10.1")),
        ("okhttp/4.12.0", ("Android app", "4.12.0")),
        ("MyCustomApp/3.1 extra", ("MyCustomApp", "3.1")),
        ("", ("Unknown app", "")),
    ],
)
def test_parse_user_agent(ua, expected):
    assert parse_user_agent(ua) == expected


async def test_apps_and_connected_ips(admin, anon, operator, viewer):
    agent_id, h = await enroll_agent(admin, anon, "node-ip", tools={"xray": True})
    user = (await operator.post("/api/v1/vpn/users", json={"username": "watched"})).json()
    other = (await operator.post("/api/v1/vpn/users", json={"username": "other"})).json()
    token = user["sub_token"]

    for ua in ("v2rayNG/1.9.16", "v2rayNG/1.9.16", "HiddifyNext/2.5.7 (android)"):
        r = await anon.get(f"/sub/{token}", headers={"user-agent": ua})
        assert r.status_code == 200
    # A browser visit is redirected to the status page and is not recorded as an app.
    r = await anon.get(f"/sub/{token}", headers={"user-agent": "Mozilla/5.0 Chrome/126", "accept": "text/html"})
    assert r.status_code == 302

    now = int(time.time())
    r = await anon.post(
        "/api/agent/v1/xray/state",
        headers=h,
        json={
            "running": True,
            "online_users": [f"u{user['id']}"],
            "online_ips": {f"u{user['id']}": {"203.0.113.5": now, "2001:db8::7": now - 5, "not-an-ip": now}, "garbage": {"1.1.1.1": now}},
        },
    )
    assert r.status_code == 204

    info = (await anon.get(f"/api/sub/{token}/info")).json()
    assert [(a["app"], a["version"]) for a in info["apps"]] == [("Hiddify", "2.5.7"), ("v2rayNG", "1.9.16")]
    assert {c["ip"] for c in info["connections"]} == {"203.0.113.5", "2001:db8::7"}
    assert all(c["node"] == "node-ip" for c in info["connections"])

    act = (await viewer.get(f"/api/v1/vpn/users/{user['id']}/activity")).json()
    ng = next(a for a in act["apps"] if a["app"] == "v2rayNG")
    assert ng["fetches"] == 2 and ng["user_agent"] == "v2rayNG/1.9.16" and ng["last_ip"]
    assert len(act["connections"]) == 2
    assert (await viewer.get(f"/api/v1/vpn/users/{other['id']}/activity")).json() == {"connections": [], "apps": [], "last_online_at": None}

    users = {u["username"]: u for u in (await viewer.get("/api/v1/vpn/users")).json()}
    assert users["watched"]["online_ips"] == 2 and users["other"]["online_ips"] == 0


async def test_app_rows_are_capped(admin, anon, operator):
    user = (await operator.post("/api/v1/vpn/users", json={"username": "many"})).json()
    for i in range(25):
        await anon.get(f"/sub/{user['sub_token']}", headers={"user-agent": f"App{i}/1.{i}"})
    from ipf3_server.services.clients import MAX_APPS_PER_USER

    info = (await anon.get(f"/api/sub/{user['sub_token']}/info")).json()
    assert len(info["apps"]) == MAX_APPS_PER_USER
    assert info["apps"][0]["app"] == "App24"
