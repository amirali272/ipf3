import os
import stat

import pytest

from ipf3_agent.config import AgentConfig


def test_save_is_private_and_roundtrips(tmp_path, monkeypatch):
    p = tmp_path / "agent.json"
    AgentConfig(server_url="https://ipf3.example.com", agent_id="a", agent_token="a.secret").save(p)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    cfg = AgentConfig.load(p)
    assert cfg.agent_token == "a.secret"


def test_rejects_plain_http(tmp_path, monkeypatch):
    monkeypatch.delenv("IPF3_AGENT_ALLOW_HTTP", raising=False)
    p = tmp_path / "agent.json"
    AgentConfig(server_url="http://x").save(p)
    with pytest.raises(ValueError):
        AgentConfig.load(p)
