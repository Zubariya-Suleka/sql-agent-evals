"""Settings read from the environment and `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The agent's read-only role: gold SQL must be something the agent could run too.
    database_url: SecretStr = SecretStr("postgresql://agent_ro:agent-ro-dev@127.0.0.1:5433/olist")
    data_dir: Path = Path("data")


@lru_cache
def get_settings() -> Settings:
    return Settings()
