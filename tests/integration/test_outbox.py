import asyncio
from datetime import timedelta
from uuid import uuid7

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.db.models import Notification, OutboxEvent
from payflow.db.repositories.accounts import AccountRepository
from payflow.db.repositories.users import UserRepository
from payflow.domain.enums import EventType, OutboxStatus
from payflow.workers.outbox import EventHandler, OutboxRelay
from payflow.workers.runner import notify
from tests.integration.helpers import Sessions, fund


def relay(
    sessions: Sessions,
    handler: EventHandler = notify,
    *,
    batch_size: int = 50,
    max_attempts: int = 3,
    retry_base: timedelta = timedelta(0),
) -> OutboxRelay:
    return OutboxRelay(
        sessions,
        handler,
        batch_size=batch_size,
        max_attempts=max_attempts,
        retry_base=retry_base,
        poll_interval=timedelta(milliseconds=10),
    )


async def deposit_events(sessions: Sessions, count: int) -> None:
    async with sessions.begin() as session:
        user = await UserRepository(session).create(
            phone="+77010000001", full_name="Alice", password_hash="-"
        )
        assert user is not None
        await AccountRepository(session).open_wallets(user.id)
    for _ in range(count):
        await fund(sessions, user.id, "100.00")


async def events(sessions: Sessions) -> list[OutboxEvent]:
    async with sessions() as session:
        result = await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id))
        return list(result)


async def test_events_are_delivered_once(session_factory: Sessions) -> None:
    await deposit_events(session_factory, 2)

    delivered = await relay(session_factory).run_once()
    again = await relay(session_factory).run_once()

    assert (delivered, again) == (2, 0)
    assert {e.status for e in await events(session_factory)} == {OutboxStatus.PROCESSED}
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Notification.id))) == 2


async def test_failed_delivery_waits_for_backoff(session_factory: Sessions) -> None:
    await deposit_events(session_factory, 1)

    async def broken(_: AsyncSession, __: OutboxEvent) -> None:
        raise RuntimeError("push gateway down")

    await relay(session_factory, broken, retry_base=timedelta(hours=1)).run_once()
    not_due = await relay(session_factory).run_once()

    [event] = await events(session_factory)
    assert not_due == 0
    assert event.status is OutboxStatus.PENDING
    assert event.attempts == 1
    assert event.last_error is not None
    assert "push gateway down" in event.last_error
    assert event.available_at > event.created_at + timedelta(minutes=59)


async def test_event_is_dead_lettered_after_max_attempts(
    session_factory: Sessions,
) -> None:
    await deposit_events(session_factory, 1)

    async def broken(_: AsyncSession, __: OutboxEvent) -> None:
        raise RuntimeError("still down")

    for _ in range(4):
        await relay(session_factory, broken, max_attempts=3).run_once()

    [event] = await events(session_factory)
    assert event.status is OutboxStatus.FAILED
    assert event.attempts == 3


async def test_failing_event_does_not_hold_back_the_batch(
    session_factory: Sessions,
) -> None:
    await deposit_events(session_factory, 3)
    first_id = (await events(session_factory))[0].id

    async def fails_on_first(session: AsyncSession, event: OutboxEvent) -> None:
        await notify(session, event)
        if event.id == first_id:
            raise RuntimeError("bad payload")

    await relay(session_factory, fails_on_first).run_once()

    statuses = [e.status for e in await events(session_factory)]
    assert statuses == [
        OutboxStatus.PENDING,
        OutboxStatus.PROCESSED,
        OutboxStatus.PROCESSED,
    ]
    async with session_factory() as session:
        assert await session.scalar(select(func.count(Notification.id))) == 2


async def test_parallel_relays_never_share_an_event(session_factory: Sessions) -> None:
    await deposit_events(session_factory, 30)
    seen: list[int] = []

    async def slow(_: AsyncSession, event: OutboxEvent) -> None:
        seen.append(event.id)
        await asyncio.sleep(0.01)

    relays = [relay(session_factory, slow, batch_size=5) for _ in range(3)]
    while sum(await asyncio.gather(*(r.run_once() for r in relays))):
        pass

    assert sorted(seen) == [e.id for e in await events(session_factory)]


async def test_notifications_survive_redelivery(session_factory: Sessions) -> None:
    await deposit_events(session_factory, 1)
    [event] = await events(session_factory)

    for _ in range(2):
        async with session_factory.begin() as session:
            await notify(session, event)

    async with session_factory() as session:
        assert await session.scalar(select(func.count(Notification.id))) == 1


async def test_unknown_user_in_event_fails_delivery(session_factory: Sessions) -> None:
    async with session_factory.begin() as session:
        session.add(
            OutboxEvent(
                event_type=EventType.TRANSFER_COMPLETED,
                payload={
                    "initiator_id": str(uuid7()),
                    "counterparty_id": str(uuid7()),
                    "amount": "1.00",
                    "currency": "KZT",
                },
            )
        )

    await relay(session_factory).run_once()

    [event] = await events(session_factory)
    assert event.attempts == 1
    assert event.last_error is not None
    assert "does not exist" in event.last_error
