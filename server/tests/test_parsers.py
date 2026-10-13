from pathlib import Path

import pytest

from ipf3_server.services.parsers import ParseError, parse_dns, parse_iperf3, parse_mtr, parse_ping, parse_traceroute

FX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FX / name).read_text()


def test_iperf3_tcp():
    p = parse_iperf3(read("iperf3_tcp.json"))
    assert p.bps == pytest.approx(930_150_000.0)
    assert p.retransmits == 4
    assert p.result["sent_bps"] == pytest.approx(941_080_000.0)
    assert p.result["protocol"] == "tcp"
    assert len(p.result["intervals"]) == 5
    assert p.result["remote_host"] == "10.0.0.3"
    assert p.result["cpu_remote_percent"] == pytest.approx(30.1)
    assert p.jitter_ms is None


def test_iperf3_udp_prefers_receiver_stats():
    p = parse_iperf3(read("iperf3_udp.json"))
    assert p.result["protocol"] == "udp"
    assert p.jitter_ms == pytest.approx(0.051)
    assert p.loss_percent == pytest.approx(0.0463)
    assert p.result["lost_packets"] == 12
    assert p.bps == pytest.approx(99_621_000.0)


def test_iperf3_error():
    with pytest.raises(ParseError, match="Connection refused"):
        parse_iperf3(read("iperf3_error.json"))
    with pytest.raises(ParseError):
        parse_iperf3("not json")


def test_ping_with_loss_and_jitter():
    p = parse_ping(read("ping_ok.txt"))
    assert p.loss_percent == 20.0
    assert p.rtt_avg_ms == pytest.approx(11.525)
    assert p.result["transmitted"] == 5 and p.result["received"] == 4
    # |12.4-11.2| + |10.9-12.4| + |11.6-10.9| = 1.2 + 1.5 + 0.7 = 3.4 / 3
    assert p.jitter_ms == pytest.approx(1.133, abs=1e-3)
    assert [r["seq"] for r in p.result["replies"]] == [1, 2, 3, 5]


def test_ping_total_loss():
    p = parse_ping(read("ping_down.txt"))
    assert p.loss_percent == 100.0
    assert p.rtt_avg_ms is None
    assert p.result["errors"] == 1
    assert p.jitter_ms is None


def test_ping_garbage():
    with pytest.raises(ParseError):
        parse_ping("ping: unknown host\n")


def test_traceroute():
    p = parse_traceroute(read("traceroute.txt"))
    hops = p.result["hops"]
    assert len(hops) == 4
    assert hops[0]["addresses"] == ["192.168.1.1"]
    assert hops[1]["loss_percent"] == 100.0 and hops[1]["avg_ms"] is None
    assert hops[2]["addresses"] == ["100.64.0.1", "100.64.0.2"]
    assert hops[3]["probes"][1]["flag"] == "!X"
    assert p.result["reached"] is True
    assert p.rtt_avg_ms == pytest.approx(11.12)


def test_mtr():
    p = parse_mtr(read("mtr.json"))
    assert p.loss_percent == 10.0
    assert p.rtt_avg_ms == 11.4
    assert p.result["hops"][1]["host"] == "???"
    assert p.result["reached"] is True


def test_dns():
    p = parse_dns({"name": "example.com", "record_type": "A", "time_ms": 12.5, "rcode": "NOERROR",
                   "answers": [{"name": "example.com.", "ttl": 300, "type": "A", "value": "93.184.215.14"}]})
    assert p.rtt_avg_ms == 12.5
    assert p.result["answers"][0]["value"] == "93.184.215.14"
    with pytest.raises(ParseError):
        parse_dns({"time_ms": 1})
