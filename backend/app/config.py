from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHIPSCOPE_", env_file=".env", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/chipscope"
    redis_url: str = "redis://localhost:6379/0"

    # 东方财富请求节流：两次请求间最小间隔（秒）
    eastmoney_min_interval: float = 0.5
    eastmoney_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
