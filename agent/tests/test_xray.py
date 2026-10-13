import json
import os
import shutil

import pytest

from ipf3_agent import xray

XRAY = os.environ.get("XRAY_BIN") or shutil.which("xray")


def test_traffic_counter_keeps_unacknowledged_deltas():
    c = xray.TrafficCounter()
    c.add([
        {"name": "user>>>u1>>>traffic>>>uplink", "value": "100"},
        {"name": "user>>>u1>>>traffic>>>downlink", "value": 400},
        {"name": "inbound>>>in-1>>>traffic>>>downlink", "value": 9},
        {"name": "inbound>>>api>>>traffic>>>downlink", "value": 5},
        {"name": "user>>>u2>>>traffic>>>downlink", "value": "0"},
    ])
    p = c.take()
    assert p == {"u1": {"up": 100, "down": 400}}
    assert c.take_inbounds() == {"in-1": {"up": 0, "down": 9}}
    c.add([{"name": "user>>>u1>>>traffic>>>downlink", "value": 1}])
    c.restore(p)  # delivery failed
    assert c.take() == {"u1": {"up": 100, "down": 401}}


@pytest.mark.skipif(not XRAY, reason="xray not available")
async def test_apply_validates_and_installs(tmp_path, monkeypatch):
    monkeypatch.setattr(xray, "XRAY_BIN", XRAY)
    monkeypatch.setattr(xray, "ASSET_DIR", os.path.dirname(XRAY))
    monkeypatch.setattr(xray, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(xray, "HASH_PATH", tmp_path / "config.hash")
    good = {"inbounds": [{"port": 18080, "protocol": "socks", "settings": {}}], "outbounds": [{"protocol": "freedom"}]}
    assert await xray.apply(good, "h1") is None
    assert json.loads((tmp_path / "config.json").read_text()) == good
    assert xray.current_hash() == "h1"
    bad = {"inbounds": [{"port": 18080, "protocol": "nope"}]}
    err = await xray.apply(bad, "h2")
    assert err and xray.current_hash() == "h1"  # previous config kept
    assert json.loads((tmp_path / "config.json").read_text()) == good
    assert (await xray.version()).count(".") >= 1
