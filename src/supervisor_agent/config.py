from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Compaction(Strict):
    output_tokens: int = Field(default=4096, gt=0)
    temperature: float = 0.7
    extra: dict = Field(
        default_factory=lambda: {
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
            "top_p": 0.8,
            "presence_penalty": 1.5,
        }
    )


class Model(Strict):
    base_url: str
    profile: str
    key_file: Path
    context_window: int = 131072
    compact_tokens: int = 98304
    output_tokens: int = 16384
    temperature: float = 1.0
    request_timeout_seconds: float = Field(default=3600, gt=0)
    cache_warning_ratio: float = Field(default=0.8, ge=0, le=1)
    extra: dict = Field(default_factory=dict)
    compaction: Compaction = Field(default_factory=Compaction)

    @model_validator(mode="after")
    def limits(self):
        if not 8192 <= self.compact_tokens < self.context_window - self.output_tokens:
            raise ValueError("compact_tokens must leave generation headroom")
        if self.compaction.output_tokens >= self.context_window // 2:
            raise ValueError("compaction.output_tokens must leave input headroom")
        return self


class Search(Strict):
    url: str = "https://mcp.exa.ai/mcp?tools=web_search_exa,web_fetch_exa"
    key_file: Path
    tools: list[str] = Field(default_factory=lambda: ["web_search_exa", "web_fetch_exa"])


class Settings(Strict):
    state_root: Path = Path("/var/lib/supervisor-agent")
    socket: Path = Path("/var/lib/supervisor-agent/daemon.sock")
    runtime_user: str = "rh-agent"
    operator_group: str = "irh-worker"
    harness_socket: Path = Path("/var/lib/iterative-research-harness/daemon.sock")
    source_root: Path = Path("/home/omega/llms")
    prompt_file: Path
    delegate_prompt_file: Path | None = None
    compaction_prompt_file: Path | None = None
    model: Model
    search: Search | None = None
    hours: list[int] = Field(default_factory=lambda: [0, 4, 8, 12, 16, 20])
    timezone: str = "UTC"
    poll_seconds: float = Field(default=5, gt=0)
    startup_timeout_seconds: float = Field(default=30, ge=0)
    reminder_seconds: float = Field(default=1800, gt=0)
    delegate_seconds: float = Field(default=14400, gt=0)
    request_warning_seconds: float = Field(default=1800, gt=0)
    recent_alert_limit: int = Field(default=10, ge=1, le=100)
    shell_output_bytes: int = Field(default=24000, ge=1024)
    bwrap: Path = Path("/usr/bin/bwrap")
    hidden_paths: list[Path] = Field(default_factory=list)

    @model_validator(mode="after")
    def schedule(self):
        ZoneInfo(self.timezone)
        if (
            not self.hours
            or len(set(self.hours)) != len(self.hours)
            or any(h < 0 or h > 23 for h in self.hours)
        ):
            raise ValueError("hours must contain distinct hours from 0 to 23")
        for name in ("state_root", "socket", "harness_socket", "source_root", "prompt_file", "bwrap"):
            if not getattr(self, name).is_absolute():
                raise ValueError(f"{name} must be absolute")
        return self


def load(path: Path) -> Settings:
    return Settings.model_validate_json(path.read_text())


def secret(path: Path) -> str:
    if path.stat().st_mode & 0o037:
        raise ValueError(f"Secret must have mode 0600 or 0640: {path}")
    value = path.read_text().strip()
    if not value or "\n" in value:
        raise ValueError("Invalid secret file")
    return value


def write_json(path: Path, value):
    import os
    import uuid

    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}-{uuid.uuid4().hex}")
    try:
        with staging.open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staging, path)
        descriptor = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        staging.unlink(missing_ok=True)
