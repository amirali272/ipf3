from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from typing import Annotated

from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value can be set with an IPF3_* environment
    variable or in /etc/ipf3/server.env (loaded by systemd)."""

    model_config = SettingsConfigDict(env_prefix="IPF3_", env_file=None, extra="ignore")

    database_url: str = "postgresql+asyncpg://ipf3:ipf3@127.0.0.1:5432/ipf3"
    secret_key: str = Field(default="", description="HMAC key for session tokens (>= 32 chars)")
    session_ttl_minutes: int = 720
    cookie_secure: bool = True
    cors_origins: Annotated[list[str], NoDecode] = []
    trusted_proxies: Annotated[list[str], NoDecode] = ["127.0.0.1", "::1"]

    # Agents
    agent_offline_seconds: int = 90
    job_running_timeout_seconds: int = 900
    job_queued_timeout_seconds: int = 600
    enrollment_token_ttl_hours: int = 24
    max_payload_bytes: int = 4 * 1024 * 1024

    # Retention (days)
    retention_metrics_days: int = 30
    retention_jobs_days: int = 180
    retention_alerts_days: int = 365
    retention_audit_days: int = 365
    retention_usage_days: int = 1095

    # Calendar used for daily/monthly traffic totals (IANA name, e.g. Asia/Tehran).
    usage_timezone: str = "UTC"

    # Login protection
    login_max_failures: int = 5
    login_lockout_minutes: int = 15

    # Background worker intervals (seconds)
    scheduler_interval: int = 5
    alert_interval: int = 30
    retention_interval: int = 3600

    # Notifications
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "ipf3@localhost"
    smtp_starttls: bool = True
    webhook_timeout_seconds: float = 10.0

    # Static web UI (built React app); empty to disable serving from FastAPI.
    web_root: str = ""

    @field_validator("cors_origins", "trusted_proxies", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if len(s.secret_key) < 32:
        raise RuntimeError(
            "IPF3_SECRET_KEY must be set to a random string of at least 32 characters "
            "(generate one with: openssl rand -hex 32)"
        )
    return s
