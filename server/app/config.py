"""Application settings, loaded from environment variables / the .env file.

Every variable uses the ZZPAY_ prefix (e.g. ZZPAY_JWT_SECRET). Settings are
read once at import time and shared via the module-level ``settings`` object.
"""

from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives in the server/ folder (two levels up from this file: app/ -> server/).
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # Core
    app_name: str = "ZZPay"
    environment: str = "development"  # "development" or "production"
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    token_ttl_hours: int = 24

    # Database. ZZPAY_POSTGRES_URL (a full URL, e.g. from Neon) wins over the fields below.
    postgres_url: str = ""
    postgres_host: str = "localhost"
    postgres_port: int = 5434
    postgres_user: str = "zzpay"
    postgres_password: str = "zzpay"
    postgres_db: str = "zzpay"

    # CORS — comma-separated list of allowed origins (the Vite dev server).
    cors_origins: str = "http://localhost:5173"

    # Email (SMTP). When smtp_host is empty we log emails instead of sending.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "ZZPay <no-reply@zzpay.nl>"
    smtp_tls: bool = True

    model_config = SettingsConfigDict(
        env_prefix="ZZPAY_",
        env_file=str(_ENV_FILE),
        env_ignore_empty=True,
        extra="ignore",
    )

    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @cached_property
    def database_url(self) -> str:
        """Async SQLAlchemy URL (asyncpg driver)."""
        if self.postgres_url:
            url = self.postgres_url.strip().replace("postgres://", "postgresql://", 1)
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url.split("?")[0]  # drop ?sslmode=... (asyncpg takes ssl via connect_args)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()

# A real secret is required — fail fast rather than signing tokens with "".
if not settings.jwt_secret.strip():
    raise ValueError(
        "ZZPAY_JWT_SECRET is not set. Copy server/.env.example to server/.env "
        "and set a long random value."
    )
