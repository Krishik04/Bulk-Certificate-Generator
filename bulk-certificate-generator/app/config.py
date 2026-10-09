"""Application configuration loaded from environment variables (and an optional .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root (the folder containing the `app` package). Relative paths in the
# configuration are resolved against this, so the app behaves the same no matter
# which directory Uvicorn is started from.
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Bulk Certificate Generator API"
    database_url: str = f"sqlite:///{BASE_DIR / 'certificates.db'}"
    certificate_output_dir: Path = Path("generated_certificates")
    max_recipients_per_job: int = Field(default=500, ge=1)
    log_level: str = "INFO"
    # Browser pages from these origins may call the API (e.g. the UI opened via VS Code
    # Live Server on another port). Default: any port on localhost / 127.0.0.1.
    cors_allow_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    @field_validator("certificate_output_dir")
    @classmethod
    def resolve_output_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BASE_DIR / value).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
