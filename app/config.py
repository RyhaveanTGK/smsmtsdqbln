from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    admin_username: str = Field(default="admin", validation_alias="ADMIN_USERNAME")
    admin_password: str = Field(default="", validation_alias="ADMIN_PASSWORD")
    textbelt_api_key: str = Field(default="", validation_alias="TEXTBELT_API_KEY")
    sms_delay: float = Field(default=1.0, validation_alias="SMS_DELAY", ge=0.1, le=3600)
    database_url: str = Field(
        default="sqlite:///./sms_panel.db", validation_alias="DATABASE_URL"
    )
    session_secret: str = Field(
        default="development-only-change-this-secret",
        validation_alias="SESSION_SECRET",
    )
    cookie_secure: bool = Field(default=False, validation_alias="COOKIE_SECURE")
    textbelt_timeout: float = Field(default=20.0, validation_alias="TEXTBELT_TIMEOUT", ge=3, le=120)
    send_worker_poll: float = Field(default=1.0, validation_alias="SEND_WORKER_POLL", ge=0.2, le=60)
    max_request_bytes: int = 256_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
