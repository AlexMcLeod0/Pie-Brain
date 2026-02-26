import asyncio
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Cloud brain selection
    default_cloud_brain: str = "claude_code"

    # Ollama
    ollama_model: str = "qwen2.5:1.5b"
    ollama_base_url: str = "http://localhost:11434"
    ollama_timeout: int = 300  # seconds; generous for CPU-bound Pi 4
    ollama_max_retries: int = 3

    # ArXiv
    arxiv_discover_keywords: list[str] = [
        "large language models",
        "reinforcement learning",
        "computer vision",
    ]

    # Paths
    db_path: str = "~/.pie-brain/tasks.db"
    log_dir: str = "~/.pie-brain/logs"
    brain_inbox: str = "~/brain/inbox"
    user_prefs_path: str = "~/brain/profile/user_prefs.md"

    # Semaphore limits
    llm_semaphore_limit: int = 1
    cloud_brain_semaphore_limit: int = 1

    # Telegram
    telegram_bot_token: str = ""
    # Comma-separated list of allowed Telegram user IDs (empty = allow all — not recommended)
    telegram_allowed_user_ids: list[int] = []
    # How often (seconds) the bot polls for completed tasks to deliver results
    telegram_result_poll_interval: int = 5

    @field_validator("db_path", "log_dir", "brain_inbox", "user_prefs_path", mode="before")
    @classmethod
    def expand_path(cls, v: str) -> str:
        return str(Path(v).expanduser())

    @classmethod
    def from_yaml(cls, path: str | Path = "config.yaml") -> "Settings":
        """Load settings, overlaying config.yaml values on top of defaults/env."""
        yaml_path = Path(path)
        overrides: dict = {}
        if yaml_path.exists():
            with yaml_path.open() as f:
                overrides = yaml.safe_load(f) or {}
        return cls(**overrides)

    def build_semaphores(self) -> tuple[asyncio.Semaphore, asyncio.Semaphore]:
        """Return (llm_semaphore, cloud_brain_semaphore)."""
        return (
            asyncio.Semaphore(self.llm_semaphore_limit),
            asyncio.Semaphore(self.cloud_brain_semaphore_limit),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_yaml()
