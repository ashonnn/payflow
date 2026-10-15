from decimal import Decimal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOCK_PROVIDER_", extra="ignore")

    api_key: SecretStr
    webhook_url: str
    webhook_secret: SecretStr
    capture_delay_seconds: float = 2.0
    decline_above: Decimal = Decimal(1_000_000)
    webhook_max_attempts: int = 6
    webhook_retry_base_seconds: float = 1.0
    webhook_timeout_seconds: float = 5.0

    usd_kzt_rate: Decimal = Decimal("505.00")
    rate_swing: Decimal = Decimal("0.004")
    rate_period_seconds: float = 600.0

    log_level: str = "INFO"
    log_json: bool = True
