from uuid import UUID

from fastapi import APIRouter

from payflow.api.deps import CurrentUser, HistoryServiceDep
from payflow.api.schemas.transactions import TransactionResponse

router = APIRouter(tags=["transactions"])


@router.get("/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: UUID, user: CurrentUser, history: HistoryServiceDep
) -> TransactionResponse:
    transaction = await history.get(user.id, transaction_id)
    return TransactionResponse.for_viewer(transaction, user.id)
