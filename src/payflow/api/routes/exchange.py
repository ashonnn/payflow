from fastapi import APIRouter, Response, status

from payflow.api.deps import CurrentUser, ExchangeServiceDep
from payflow.api.idempotency import IdempotencyDep
from payflow.api.schemas.exchange import ExchangeRequest, QuoteResponse
from payflow.api.schemas.transactions import TransactionResponse

router = APIRouter(tags=["exchange"])


@router.get("/exchange/rates")
async def list_rates(exchange: ExchangeServiceDep) -> list[QuoteResponse]:
    return [QuoteResponse.model_validate(quote) for quote in await exchange.quotes()]


@router.post(
    "/exchanges",
    status_code=status.HTTP_201_CREATED,
    response_model=TransactionResponse,
)
async def create_exchange(
    payload: ExchangeRequest,
    user: CurrentUser,
    exchange: ExchangeServiceDep,
    idempotency: IdempotencyDep,
) -> Response:
    async def convert() -> TransactionResponse:
        transaction = await exchange.exchange(
            user.id, payload.from_currency, payload.to_currency, payload.amount
        )
        return TransactionResponse.for_viewer(transaction, user.id)

    return await idempotency.run(payload, convert)
