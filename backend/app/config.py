from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Validated application settings, read from the environment and the repo-level .env."""

    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://chat:chat@localhost:5432/chat"
    # Only used by the test suite; it is wiped on every test run.
    test_database_url: str = "postgresql+asyncpg://chat:chat@localhost:5432/chat_test"
    ollama_base_url: str = "http://localhost:11434"
    default_model: str | None = None
    system_prompt: str | None = None
    ollama_timeout: float = Field(default=300.0, gt=0)
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: list[str] = ["http://localhost:5173"]
    # Built frontend served at "/" when present (used by `make start`).
    frontend_dist: Path = REPO_DIR / "frontend" / "dist"

    @field_validator("default_model", "system_prompt", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// driver")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
