"""Application configuration loaded from environment variables.

AWS credentials are never read here directly: boto3 resolves them through the
standard AWS credential chain (env vars, AWS_PROFILE, SSO, instance roles).
"""

from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore",
                                      populate_by_name=True)

    app_env: str = "development"
    api_version: str = "0.1.0"
    timezone: str = "Asia/Kolkata"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Planning policy
    max_passengers: int = Field(default=6, ge=1, le=20)
    max_planning_days: int = Field(default=120, ge=1)
    min_transfer_minutes: int = Field(default=30, ge=0)
    session_ttl_minutes: int = Field(default=120, ge=1)
    recommendation_ttl_minutes: int = Field(default=30, ge=1)

    # Request hardening
    max_body_bytes: int = Field(default=16_384, ge=1024)
    max_message_chars: int = Field(default=1000, ge=50)
    rate_limit_per_minute: int = Field(default=60, ge=1)

    # Railway data source: "demo" (bundled simulated data) or "railradar" (live third-party API).
    # Env var RAILWAY_DATA_MODE (preferred) or DATA_PROVIDER.
    data_provider: str = Field(default="demo", validation_alias=AliasChoices("RAILWAY_DATA_MODE", "DATA_PROVIDER",
                                                                           "data_provider"))
    railradar_api_key: SecretStr | None = None
    railradar_base_url: str = "https://api.railradar.in"
    railradar_timeout_seconds: float = Field(default=10.0, gt=0)
    railradar_cache_seconds: int = Field(default=300, ge=0)
    railradar_max_concurrency: int = Field(default=4, ge=1, le=10)
    railradar_requests_per_minute: int = Field(default=10, ge=1)  # observed limit of the current key

    # LLM (optional). "bedrock" or "none".
    llm_provider: str = "none"
    aws_region: str | None = None
    bedrock_model_id: str | None = None
    aws_profile: str | None = None
    bedrock_timeout_seconds: float = Field(default=15.0, gt=0)
    bedrock_max_retries: int = Field(default=2, ge=0, le=5)

    # Logging
    log_message_content: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def railradar_configured(self) -> bool:
        key = self.railradar_api_key.get_secret_value().strip() if self.railradar_api_key else ""
        return self.data_provider.lower() == "railradar" and bool(key)

    @property
    def bedrock_configured(self) -> bool:
        return (
            self.llm_provider.lower() == "bedrock"
            and bool(self.aws_region)
            and bool(self.bedrock_model_id)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
