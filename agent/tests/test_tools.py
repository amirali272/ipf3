import pytest

from ipf3_agent.tools import JobError, build_iperf3, build_mtr, build_ping, build_traceroute, execute


def test_iperf3_argv():
    c = build_iperf3({"target": "10.0.0.3", "protocol": "udp", "duration": 5, "bitrate_bps": 100_000_000, "reverse": True})
    assert c.argv[:3] == ["iperf3", "-c", "10.0.0.3"]
    assert "-u" in c.argv and "-R" in c.argv and "-J" in c.argv
    assert c.argv[c.argv.index("-b") + 1] == "100000000"
    assert c.timeout == 35


@pytest.mark.parametrize("target", ["-oFoo", "a;b", "$(reboot)", "", None, 5, "a b", "x" * 300])
@pytest.mark.parametrize("builder", [build_iperf3, build_ping, build_traceroute, build_mtr])
def test_rejects_injection(builder, target):
    with pytest.raises(JobError):
        builder({"target": target})


def test_rejects_out_of_range():
    with pytest.raises(JobError):
        build_iperf3({"target": "1.1.1.1", "duration": 10_000})
    with pytest.raises(JobError):
        build_ping({"target": "1.1.1.1", "interval": 0.001})
    with pytest.raises(JobError):
        build_ping({"target": "1.1.1.1", "count": True})
    with pytest.raises(JobError):
        build_traceroute({"target": "1.1.1.1", "protocol": "raw"})


def test_ping_argv_target_last():
    c = build_ping({"target": "example.com", "count": 3, "interval": 0.2, "ipv6": True})
    assert c.argv[-1] == "example.com" and "-6" in c.argv and c.argv[c.argv.index("-i") + 1] == "0.2"
    assert 1 in c.ok_codes


def test_mtr_and_traceroute_protocols():
    assert "-T" in build_mtr({"target": "1.1.1.1", "protocol": "tcp"}).argv
    assert "--json" in build_mtr({"target": "1.1.1.1"}).argv
    assert "-I" in build_traceroute({"target": "1.1.1.1", "protocol": "icmp"}).argv


async def test_unknown_type():
    with pytest.raises(JobError):
        await execute("rm", {})


async def test_missing_binary(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    import ipf3_agent.tools as t

    async def boom(cmd):
        raise FileNotFoundError

    monkeypatch.setattr(t, "run_command", boom)
    with pytest.raises(JobError, match="not installed"):
        await execute("ping", {"target": "1.1.1.1"})


async def test_dns_rejects_bad_name():
    with pytest.raises(JobError):
        await execute("dns", {"name": "-x"})
    with pytest.raises(JobError):
        await execute("dns", {"name": "bad name.com", "server": "127.0.0.1"})
