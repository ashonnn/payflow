from datetime import time
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class FraudSettings(BaseModel):
    large_amount_kzt: Decimal = Decimal(1_000_000)
    large_amount_usd: Decimal = Decimal(2_000)
    night_starts_at: time = time(0, 0)
    night_ends_at: time = time(6, 0)
    timezone: str = "Asia/Almaty"
    large_amount_score: int = 100
    new_recipient_score: int = 40
    night_time_score: int = 30
    review_threshold: int = 60


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_nested_delimiter="__", extra="ignore"
    )

    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    redis_url: str

    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 7 * 24 * 60 * 60

    password_hash_time_cost: int = 2
    password_hash_memory_kib: int = 19 * 1024
    password_hash_parallelism: int = 1

    admin_session_secret: SecretStr

    payment_provider_url: str
    payment_provider_api_key: SecretStr
    payment_provider_webhook_secret: SecretStr
    payment_provider_timeout_seconds: float = 5.0
    webhook_tolerance_seconds: int = 300

    fx_provider_url: str
    fx_rates_ttl_seconds: int = 60
    fx_spread: Decimal = Decimal("0.005")

    transfer_rate_limit: int = 10
    transfer_rate_window_seconds: int = 60

    idempotency_key_ttl_hours: int = 24

    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 50
    outbox_max_attempts: int = 8
    outbox_retry_base_seconds: float = 2.0

    reconciliation_run_at: time = time(2, 0)
    worker_metrics_port: int = 9100

    fraud: FraudSettings = Field(default_factory=FraudSettings)


@lru_cache
def get_settings() -> Settings:
    return Settings()
