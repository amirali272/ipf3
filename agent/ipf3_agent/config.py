from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("IPF3_AGENT_CONFIG", "/etc/ipf3/agent.json"))


@dataclass
class AgentConfig:
    server_url: str
    agent_id: str = ""
    agent_token: str = ""
    name: str = ""
    ca_file: str | None = None
    metrics_interval: float = 10.0
    inventory_interval: float = 60.0
    heartbeat_interval: float = 60.0
    max_concurrent_jobs: int = 2
    max_connections_reported: int = 2000
    exclude_interfaces: list[str] = field(default_factory=lambda: ["lo"])

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "AgentConfig":
        data = json.loads(path.read_text())
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        cfg = cls(**known)
        if not cfg.server_url.startswith("https://") and not os.environ.get("IPF3_AGENT_ALLOW_HTTP"):
            raise ValueError("server_url must use https:// (set IPF3_AGENT_ALLOW_HTTP=1 only for local testing)")
        return cfg

    def save(self, path: Path = DEFAULT_PATH) -> None:
        """Atomically write the config with mode 0600 (it contains the agent secret)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".agent.", suffix=".json")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(asdict(self), f, indent=2)
                f.write("\n")
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
