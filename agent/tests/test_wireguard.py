import os
import shutil
import socket
import subprocess

import pytest

from ipf3_agent import wireguard as wg

WG = shutil.which("wg")
WG_QUICK = shutil.which("wg-quick")
HAVE_WG = bool(WG and WG_QUICK) and os.geteuid() == 0


def test_parse_dump_skips_interface_line_and_bad_rows():
    lines = [
        "cHJpdmF0ZQ==\t51820\toff",  # interface line (not 8 fields): ignored
        "pub1\tpsk\t1.2.3.4:51820\t10.0.0.2/32\t1700000000\t100\t200\toff",
        "pub2\tpsk\t(none)\t10.0.0.3/32\t0\t0\t0\toff",
        "pub3\tpsk\tx\tx\tnotanumber\t1\t2\toff",  # bad int -> skipped
        "garbage line",
    ]
    peers = wg.parse_dump(lines)
    assert peers == {
        "pub1": {"handshake": 1700000000, "rx": 100, "tx": 200},
        "pub2": {"handshake": 0, "rx": 0, "tx": 0},
    }


def test_traffic_counter_deltas_and_restart_reset():
    c = wg.TrafficCounter()
    c.update({"p1": {"handshake": 1, "rx": 1000, "tx": 200}})
    assert c.take() == {}  # first sighting: nothing to diff against yet
    c.update({"p1": {"handshake": 2, "rx": 1500, "tx": 250}})
    assert c.take() == {"p1": {"up": 500, "down": 50}}
    # interface restarted: counters reset to 0, must not produce a huge negative delta
    c.update({"p1": {"handshake": 3, "rx": 10, "tx": 5}})
    assert c.take() == {}
    c.update({"p1": {"handshake": 4, "rx": 30, "tx": 15}})
    assert c.take() == {"p1": {"up": 20, "down": 10}}


def test_restore_merges_pending_on_failed_delivery():
    c = wg.TrafficCounter()
    c.update({"p1": {"handshake": 1, "rx": 100, "tx": 50}})
    c.update({"p1": {"handshake": 2, "rx": 300, "tx": 150}})
    pending = c.take()
    c.update({"p1": {"handshake": 3, "rx": 400, "tx": 250}})
    c.restore(pending)
    assert c.take() == {"p1": {"up": 300, "down": 200}}


async def test_not_installed_without_binaries(monkeypatch, tmp_path):
    monkeypatch.setattr(wg.shutil, "which", lambda name: None)
    assert wg.installed() is False


async def test_apply_rejects_truncated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(wg, "CONFIG_PATH", tmp_path / "wireguard" / "wg0.conf")
    monkeypatch.setattr(wg, "HASH_PATH", wg.CONFIG_PATH.with_name("config.hash"))
    (tmp_path / "wireguard").mkdir()
    err = await wg.apply("not a valid config at all {{{", "deadbeef")
    assert err is not None
    assert not wg.CONFIG_PATH.exists()


@pytest.mark.skipif(not HAVE_WG, reason="wg/wg-quick not available or not root")
async def test_apply_installs_valid_config_and_reports_running(tmp_path, monkeypatch):
    monkeypatch.setattr(wg, "CONFIG_PATH", tmp_path / "wireguard" / "wg0.conf")
    monkeypatch.setattr(wg, "HASH_PATH", wg.CONFIG_PATH.with_name("config.hash"))
    (tmp_path / "wireguard").mkdir()
    priv = subprocess.run([WG, "genkey"], capture_output=True, text=True, check=True).stdout.strip()
    port = _free_udp_port()
    text = f"[Interface]\nPrivateKey = {priv}\nAddress = 10.95.0.1/24\nListenPort = {port}\n"

    err = await wg.apply(text, "abc123")
    assert err is None
    assert wg.current_hash() == "abc123"
    assert wg.CONFIG_PATH.read_text() == text

    assert await wg.is_running() is False  # written, but nothing has brought it up
    proc = subprocess.run([WG_QUICK, "up", str(wg.CONFIG_PATH)], capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    try:
        assert await wg.is_running() is True
    finally:
        subprocess.run([WG_QUICK, "down", str(wg.CONFIG_PATH)], capture_output=True, timeout=15)
    assert await wg.is_running() is False


@pytest.mark.skipif(not HAVE_WG, reason="wg/wg-quick not available or not root")
async def test_read_dump_parses_a_real_wg_show_dump(tmp_path, monkeypatch):
    """read_dump() against the literal output of a real `wg show <iface> dump` on a
    real interface with a real configured peer (end-to-end tunnel traffic itself is
    proven in server/tests/test_wireguard.py, which pings across two real nodes —
    this just confirms the agent parses the server's own `wg` output correctly)."""
    monkeypatch.setattr(wg, "STATS_PATH", tmp_path / "stats.dump")
    s_priv = subprocess.run([WG, "genkey"], capture_output=True, text=True, check=True).stdout.strip()
    c_priv = subprocess.run([WG, "genkey"], capture_output=True, text=True, check=True).stdout.strip()
    c_pub = subprocess.run([WG, "pubkey"], input=c_priv, capture_output=True, text=True, check=True).stdout.strip()
    port = _free_udp_port()
    sconf = tmp_path / "ag-test-srv.conf"
    sconf.write_text(f"[Interface]\nPrivateKey = {s_priv}\nAddress = 10.96.0.1/24\nListenPort = {port}\n\n[Peer]\nPublicKey = {c_pub}\nAllowedIPs = 10.96.0.2/32\n")
    subprocess.run([WG_QUICK, "up", str(sconf)], check=True, capture_output=True, timeout=15)
    try:
        dump = subprocess.run([WG, "show", "ag-test-srv", "dump"], capture_output=True, text=True, timeout=10).stdout
        wg.STATS_PATH.write_text(dump)
        peers = wg.read_dump()
        assert peers == {c_pub: {"handshake": 0, "rx": 0, "tx": 0}}  # configured, never connected
    finally:
        subprocess.run([WG_QUICK, "down", str(sconf)], capture_output=True, timeout=15)


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
