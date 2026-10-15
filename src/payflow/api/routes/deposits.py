from fastapi import APIRouter, Response, status

from payflow.api.deps import CurrentUser, DepositServiceDep
from payflow.api.idempotency import IdempotencyDep
from payflow.api.routes import API_PREFIX
from payflow.api.schemas.deposits import DepositRequest
from payflow.api.schemas.transactions import TransactionResponse

router = APIRouter(prefix=API_PREFIX, tags=["deposits"])


@router.post(
    "/deposits",
    status_code=status.HTTP_201_CREATED,
    response_model=TransactionResponse,
)
async def create_deposit(
    payload: DepositRequest,
    user: CurrentUser,
    deposits: DepositServiceDep,
    idempotency: IdempotencyDep,
) -> Response:
    async def start_deposit() -> TransactionResponse:
        transaction = await deposits.start(
            user.id,
            payload.currency,
            payload.amount,
            idempotency_key=idempotency.key,
        )
        return TransactionResponse.for_viewer(transaction, user.id)

    return await idempotency.run(payload, start_deposit)
