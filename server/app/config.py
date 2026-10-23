"""Application settings, loaded from environment variables / the .env file.

Every variable uses the ZZPAY_ prefix (e.g. ZZPAY_JWT_SECRET) — the prefix is kept
from the original deployment so the live Render service keeps working. Settings are
read once at import time and shared via the module-level ``settings`` object.
"""

from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env lives in the server/ folder (two levels up from this file: app/ -> server/).
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # --- Core --------------------------------------------------------------
    app_name: str = "TradeTrack"
    environment: str = "development"  # "development" or "production"
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    token_ttl_hours: int = 24
    # Public URL of the frontend (used for Stripe return URLs). No trailing slash.
    # If empty, the first entry of ZZPAY_CORS_ORIGINS is used.
    frontend_url: str = ""
    # Auth cookie SameSite: "lax" (default; frontend and API share a site / are proxied),
    # or "none" if the frontend and API are on different sites (forces Secure).
    cookie_samesite: str = "lax"

    # --- Database ----------------------------------------------------------
    # ZZPAY_POSTGRES_URL (a full URL, e.g. from Neon) wins over the fields below.
    postgres_url: str = ""
    postgres_host: str = "localhost"
    postgres_port: int = 5434
    postgres_user: str = "zzpay"
    postgres_password: str = "zzpay"
    postgres_db: str = "zzpay"

    # --- CORS (comma-separated list of allowed origins) ---------------------
    cors_origins: str = "http://localhost:5173"

    # --- AI extraction (OpenAI) -------------------------------------------
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 60.0

    # --- Uploads -----------------------------------------------------------
    max_upload_mb: int = 10

    # --- File storage: "database" (default) or S3-compatible when ALL set ----
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = ""

    # --- Email out (SMTP; used for "email to accountant") -------------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "TradeTrack <no-reply@tradetrack.ca>"
    smtp_tls: bool = True

    # --- Inbound email (Mailgun route) -------------------------------------
    mailgun_signing_key: str = ""
    inbound_domain: str = ""  # e.g. receipts.tradetrack.ca
    inbound_max_age_seconds: int = 300

    # --- Billing (Stripe). Demo mode is used unless secret key + price id are set
    stripe_secret_key: str = ""
    stripe_price_id: str = ""
    stripe_webhook_secret: str = ""

    # --- Plans (optional overrides of plans.py defaults) --------------------
    free_monthly_limit: int = 5
    premium_price_cad: str = "5.99"

    # --- Demo seed ---------------------------------------------------------
    seed_demo: bool = False
    demo_password: str = "demo1234"

    # --- Rate limits (per process, in memory) -------------------------------
    login_max_attempts: int = 8
    login_window_seconds: int = 300
    process_max_per_minute: int = 20

    model_config = SettingsConfigDict(
        env_prefix="ZZPAY_",
        env_file=str(_ENV_FILE),
        env_ignore_empty=True,
        extra="ignore",
    )

    # --- derived -----------------------------------------------------------
    @property
    def is_development(self) -> bool:
        return self.environment.lower() == "development"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def frontend_origin(self) -> str:
        """Frontend origin for Stripe return URLs: ZZPAY_FRONTEND_URL, else first CORS origin."""
        url = self.frontend_url.strip() or (self.cors_origin_list[0] if self.cors_origin_list else "http://localhost:5173")
        return url.rstrip("/")

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def ai_configured(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host.strip())

    @property
    def inbound_email_configured(self) -> bool:
        return bool(self.mailgun_signing_key.strip() and self.inbound_domain.strip())

    @property
    def s3_configured(self) -> bool:
        return all(
            v.strip()
            for v in (self.s3_endpoint, self.s3_bucket, self.s3_access_key, self.s3_secret_key)
        )

    @property
    def file_storage(self) -> str:
        return "s3" if self.s3_configured else "database"

    @property
    def stripe_configured(self) -> bool:
        return bool(self.stripe_secret_key.strip() and self.stripe_price_id.strip())

    @property
    def billing_mode(self) -> str:
        return "stripe" if self.stripe_configured else "demo"

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
