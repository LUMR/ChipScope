from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env，路径与 cwd 无关
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHIPSCOPE_", env_file=_ENV_FILE, extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/chipscope"
    redis_url: str = "redis://localhost:6379/0"

    # 东方财富请求节流：两次请求间最小间隔（秒）
    eastmoney_min_interval: float = 0.5
    eastmoney_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )

    # 自选股默认种子（逗号分隔 secucode），watchlist 表为空时首次写入
    watchlist_default: str = "600519.SH,000001.SZ,000858.SZ,601318.SH,002594.SZ"


@lru_cache
def get_settings() -> Settings:
    return Settings()
