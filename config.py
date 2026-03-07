"""
config.py — Centralised configuration via Pydantic Settings.
All values are read from environment variables (or .env file).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── AWS ────────────────────────────────────────────────────────
    aws_region: str = Field(default="us-west-2")
    aws_access_key_id: str = Field(default="")
    aws_secret_access_key: str = Field(default="")

    # ── Amazon Bedrock ─────────────────────────────────────────────
    bedrock_model_id: str = Field(
        default="us.anthropic.claude-sonnet-4-20250514-v1:0"
    )

    # ── Tavily Search ──────────────────────────────────────────────
    tavily_api_key: str = Field(default="")

    # ── Database ───────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql://procurement:devpassword@localhost:5432/procurement_db"
    )

    # ── Gmail SMTP / IMAP ──────────────────────────────────────────
    gmail_address: str = Field(default="")
    gmail_app_password: str = Field(default="")
    imap_host: str = Field(default="imap.gmail.com")
    imap_port: int = Field(default=993)
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587)
    email_poll_interval_seconds: int = Field(default=300)

    # ── Application ────────────────────────────────────────────────
    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")


# Singleton — import this everywhere
settings = Settings()
