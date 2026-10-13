from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path

from .collect import MetricsCollector, detect_tools, host_inventory, system_info
from .config import DEFAULT_PATH, AgentConfig
from .runner import Agent, FatalAuthError, enroll


def cmd_enroll(args) -> int:
    path = Path(args.config)
    if path.exists() and not args.force:
        print(f"{path} already exists; use --force to re-enroll", file=sys.stderr)
        return 1
    token = args.token or os.environ.get("IPF3_ENROLLMENT_TOKEN", "")
    if not token:
        print("enrollment token required (--token or IPF3_ENROLLMENT_TOKEN)", file=sys.stderr)
        return 1
    if not args.server.startswith("https://") and not os.environ.get("IPF3_AGENT_ALLOW_HTTP"):
        print("server URL must use https://", file=sys.stderr)
        return 1
    name = args.name or socket.gethostname()
    try:
        agent_id, agent_token = asyncio.run(enroll(args.server, token, name, args.ca_file))
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    AgentConfig(
        server_url=args.server, agent_id=agent_id, agent_token=agent_token, name=name, ca_file=args.ca_file
    ).save(path)
    print(f"enrolled as '{name}' ({agent_id}); credentials written to {path}")
    return 0


def cmd_run(args) -> int:
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    cfg = AgentConfig.load(Path(args.config))
    try:
        asyncio.run(Agent(cfg).run())
    except FatalAuthError as e:
        logging.getLogger("ipf3.agent").error("%s", e)
        return 78  # EX_CONFIG: systemd RestartPreventExitStatus
    return 0


def cmd_check(_args) -> int:
    c = MetricsCollector(["lo"])
    c.sample()
    time.sleep(1)
    print(json.dumps({"system": system_info(), "tools": detect_tools(), "sample": c.sample()}, indent=2, default=str))
    return 0


def cmd_inventory(_args) -> int:
    print(json.dumps(host_inventory(200), indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ipf3-agent")
    p.add_argument("--config", default=str(DEFAULT_PATH))
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("enroll", help="register this host with the server")
    e.add_argument("--server", required=True, help="https://ipf3.example.com")
    e.add_argument("--token", help="one-time enrollment token (or IPF3_ENROLLMENT_TOKEN)")
    e.add_argument("--name", help="agent name (default: hostname)")
    e.add_argument("--ca-file", help="CA bundle for a private server certificate")
    e.add_argument("--force", action="store_true")
    e.set_defaults(fn=cmd_enroll)

    r = sub.add_parser("run", help="run the agent")
    r.add_argument("--log-level", default="info")
    r.set_defaults(fn=cmd_run)

    sub.add_parser("check", help="print detected tools and a metrics sample").set_defaults(fn=cmd_check)
    sub.add_parser("inventory", help="print the host inventory").set_defaults(fn=cmd_inventory)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
