from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+asyncpg://neomarket:neomarket_pass@localhost:5432/neomarket_b2b"
    )
    moderation_service_url: str = "http://localhost:8001"
    debug: bool = True

    class Config:
        env_file = ".env"


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()
