from fastapi import APIRouter, Request

from payflow.api.deps import ContainerDep, DepositServiceDep, SessionDep
from payflow.integrations.payment_provider import SIGNATURE_HEADER, parse_payment_event

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/payment-provider")
async def payment_provider_webhook(
    request: Request,
    container: ContainerDep,
    session: SessionDep,
    deposits: DepositServiceDep,
) -> dict[str, str]:
    payload = await request.body()
    container.webhook_verifier.verify(payload, request.headers.get(SIGNATURE_HEADER))
    await deposits.apply_payment_event(parse_payment_event(payload))
    await session.commit()
    return {"status": "accepted"}
