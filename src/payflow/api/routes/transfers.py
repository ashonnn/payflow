from fastapi import APIRouter, Depends, Response, status

from payflow.api.deps import CurrentUser, TransferServiceDep, limit_transfer_rate
from payflow.api.idempotency import IdempotencyDep
from payflow.api.routes import API_PREFIX
from payflow.api.schemas.transactions import TransactionResponse
from payflow.api.schemas.transfers import TransferRequest
from payflow.domain.services.transfers import TransferCommand

router = APIRouter(prefix=API_PREFIX, tags=["transfers"])


@router.post(
    "/transfers",
    status_code=status.HTTP_201_CREATED,
    response_model=TransactionResponse,
    dependencies=[Depends(limit_transfer_rate)],
)
async def create_transfer(
    payload: TransferRequest,
    user: CurrentUser,
    transfers: TransferServiceDep,
    idempotency: IdempotencyDep,
) -> Response:
    async def send() -> TransactionResponse:
        transaction = await transfers.transfer(
            TransferCommand(
                sender_id=user.id,
                recipient_phone=payload.to_phone,
                amount=payload.amount,
                currency=payload.currency,
                comment=payload.comment,
            )
        )
        return TransactionResponse.for_viewer(transaction, user.id)

    return await idempotency.run(payload, send)
