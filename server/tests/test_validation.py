import pytest
from pydantic import ValidationError

from ipf3_server.models import JobType
from ipf3_server.schemas import validate_host, validate_job_params


@pytest.mark.parametrize("host", ["1.1.1.1", "2606:4700:4700::1111", "example.com", "a-b.example.co.uk", "localhost"])
def test_valid_hosts(host):
    assert validate_host(host)


@pytest.mark.parametrize(
    "host",
    ["", "-oProxyCommand=x", "a;rm -rf /", "$(id)", "foo bar", "a" * 300, "x..y", "1.2.3.999", "--help", "host`id`"],
)
def test_invalid_hosts(host):
    with pytest.raises(ValueError):
        validate_host(host)


def test_iperf_params_defaults_and_limits():
    p = validate_job_params(JobType.iperf3, {"target": "10.0.0.3"})
    assert p["port"] == 5201 and p["protocol"] == "tcp" and p["duration"] == 10
    with pytest.raises(ValidationError):
        validate_job_params(JobType.iperf3, {"target": "10.0.0.3", "duration": 3600})
    with pytest.raises(ValidationError):
        validate_job_params(JobType.iperf3, {"target": "10.0.0.3", "extra_args": "--foo"})
    with pytest.raises(ValidationError):
        validate_job_params(JobType.iperf3, {"target": "10.0.0.3", "reverse": True, "bidir": True})


def test_dns_params():
    p = validate_job_params(JobType.dns, {"name": "_sip._tcp.example.com", "record_type": "SRV", "server": "9.9.9.9"})
    assert p["server"] == "9.9.9.9"
    with pytest.raises(ValidationError):
        validate_job_params(JobType.dns, {"name": "example.com", "server": "not-an-ip"})


def test_ping_interval_floor():
    with pytest.raises(ValidationError):
        validate_job_params(JobType.ping, {"target": "1.1.1.1", "interval": 0.01})
