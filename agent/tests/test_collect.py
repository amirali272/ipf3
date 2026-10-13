from ipf3_agent.collect import MetricsCollector, parse_resolv_conf, parse_ss, tcp_retrans_segs, tcp_state_counts, udp_socket_count

TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1 0 100 0 0 10 0
   1: 0200000A:0016 0300000A:D2F0 01 00000000:00000000 02:00000000 00000000     0        0 2 1 0 20 4 30 10 -1
   2: 0200000A:0016 0300000A:D2F1 06 00000000:00000000 03:00000000 00000000     0        0 0 3 0 0 0 0 0 0
"""
SNMP = """Ip: Forwarding DefaultTTL
Ip: 1 64
Tcp: RtoAlgorithm RtoMin RtoMax MaxConn ActiveOpens PassiveOpens AttemptFails EstabResets CurrEstab InSegs OutSegs RetransSegs InErrs OutRsts InCsumErrors
Tcp: 1 200 120000 -1 100 50 3 2 5 10000 9000 42 0 7 0
"""


def test_proc_parsing(tmp_path):
    (tmp_path / "net").mkdir()
    (tmp_path / "net/tcp").write_text(TCP)
    (tmp_path / "net/tcp6").write_text(TCP.splitlines()[0] + "\n")
    (tmp_path / "net/udp").write_text("hdr\n a\n b\n")
    (tmp_path / "net/udp6").write_text("hdr\n")
    (tmp_path / "net/snmp").write_text(SNMP)
    root = str(tmp_path)
    assert tcp_state_counts(root) == {"listen": 1, "established": 1, "time_wait": 1}
    assert udp_socket_count(root) == 2
    assert tcp_retrans_segs(root) == 42


def test_parse_ss():
    out = "tcp   ESTAB  0      0      10.0.0.2:22     10.0.0.3:53999\nudp   UNCONN 0      0      127.0.0.53%lo:53 0.0.0.0:*\n"
    conns = parse_ss(out, 10)
    assert conns[0] == {"proto": "tcp", "state": "ESTAB", "recv_q": 0, "send_q": 0, "local": "10.0.0.2:22", "peer": "10.0.0.3:53999"}
    assert len(parse_ss(out, 1)) == 1


def test_parse_resolv_conf():
    r = parse_resolv_conf("# comment\nnameserver 127.0.0.53\noptions edns0 trust-ad\nsearch corp.example\n")
    assert r == {"nameservers": ["127.0.0.53"], "search": ["corp.example"], "options": ["edns0", "trust-ad"]}


def test_collector_real_sample():
    c = MetricsCollector(["lo"])
    assert c.sample() is None
    s = c.sample()
    assert s is not None
    assert 0 <= s["system"]["cpu_percent"] <= 100
    assert s["system"]["mem_total"] > 0
    for i in s["interfaces"]:
        assert i["rx_bps"] >= 0 and i["iface"] != "lo"


def test_primary_interfaces(tmp_path):
    from ipf3_agent.collect import primary_interfaces

    for n in ("eth0", "ens3"):
        (tmp_path / n / "device").mkdir(parents=True)
    (tmp_path / "docker0").mkdir()
    assert primary_interfaces(["lo", "eth0", "ens3", "docker0", "wg0"], str(tmp_path)) == {"eth0", "ens3"}
    # no device-backed NIC (e.g. OpenVZ venet0): everything but loopback
    assert primary_interfaces(["lo", "venet0"], str(tmp_path)) == {"venet0"}


def test_live_meter_and_bytes():
    from ipf3_agent.collect import NetRateMeter

    m = NetRateMeter()
    assert m.sample() is None
    rates = m.sample()
    assert rates is not None and all(r["rx_bps"] >= 0 and "primary" in r for r in rates)
    c = MetricsCollector([])
    c.sample()
    s = c.sample()
    assert all(i["rx_bytes"] >= 0 and i["tx_bytes"] >= 0 for i in s["interfaces"])
