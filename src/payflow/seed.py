from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import structlog
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import update

from payflow.container import Container
from payflow.core.security import RefreshTokenStore
from payflow.db.models import User
from payflow.db.repositories.users import UserRepository
from payflow.domain.enums import Currency
from payflow.domain.fraud import FraudSignal
from payflow.domain.services.auth import AuthService
from payflow.domain.services.deposits import DepositService
from payflow.domain.services.transfers import TransferCommand, TransferService

logger = structlog.get_logger(__name__)


class SeedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEED_", env_file=".env", extra="ignore"
    )

    admin_password: SecretStr
    user_password: SecretStr


@dataclass(frozen=True, slots=True)
class DemoUser:
    phone: str
    full_name: str
    balances: tuple[tuple[Currency, str], ...]


ADMIN = DemoUser("+77000000000", "PayFlow Admin", ())
CUSTOMERS = (
    DemoUser(
        "+77010000001",
        "Aruzhan Sadykova",
        ((Currency.KZT, "2500000.00"), (Currency.USD, "1200.00")),
    ),
    DemoUser(
        "+77010000002",
        "Daniyar Bekov",
        ((Currency.KZT, "320000.00"), (Currency.USD, "300.00")),
    ),
    DemoUser("+77010000003", "Madina Omarova", ((Currency.KZT, "95000.00"),)),
)
HISTORY = (
    ("+77010000001", "+77010000002", "15000.00", "dinner"),
    ("+77010000002", "+77010000003", "4500.00", "taxi"),
    ("+77010000003", "+77010000001", "2000.00", "coffee"),
    ("+77010000001", "+77010000003", "1200000.00", "car deposit"),
)


async def seed(container: Container, settings: SeedSettings) -> bool:
    """Create demo users with balances and history; False if they already exist."""
    async with container.session_factory.begin() as session:
        if await UserRepository(session).get_by_phone(ADMIN.phone):
            logger.info("seed.skipped", reason="demo data already present")
            return False
        auth = AuthService(
            session,
            container.password_hasher,
            container.token_codec,
            RefreshTokenStore(container.redis),
            access_ttl=timedelta(seconds=container.settings.access_token_ttl_seconds),
            refresh_ttl=timedelta(seconds=container.settings.refresh_token_ttl_seconds),
        )
        admin = await auth.register(
            ADMIN.phone, settings.admin_password.get_secret_value(), ADMIN.full_name
        )
        await session.execute(
            update(User).where(User.id == admin.id).values(is_admin=True)
        )
        deposits = DepositService(session, container.payment_provider, container.clock)
        user_ids: dict[str, UUID] = {}
        for customer in CUSTOMERS:
            user = await auth.register(
                customer.phone,
                settings.user_password.get_secret_value(),
                customer.full_name,
            )
            user_ids[customer.phone] = user.id
            for currency, amount in customer.balances:
                await deposits.credit_settled(
                    user.id,
                    currency,
                    Decimal(amount),
                    external_id=f"seed-{customer.phone}-{currency}",
                )

        # seeded history should not depend on the hour it happens to be generated at
        policy = replace(
            container.fraud_policy,
            weights={**container.fraud_policy.weights, FraudSignal.NIGHT_TIME: 0},
        )
        transfers = TransferService(session, policy, container.clock)
        for sender_phone, recipient_phone, amount, comment in HISTORY:
            await transfers.transfer(
                TransferCommand(
                    sender_id=user_ids[sender_phone],
                    recipient_phone=recipient_phone,
                    amount=Decimal(amount),
                    currency=Currency.KZT,
                    comment=comment,
                )
            )
    logger.info("seed.completed", customers=len(CUSTOMERS), transfers=len(HISTORY))
    return True
