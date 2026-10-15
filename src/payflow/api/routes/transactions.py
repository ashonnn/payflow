from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from payflow.api.deps import CurrentUser, HistoryServiceDep
from payflow.api.pagination import decode_cursor, encode_cursor
from payflow.api.routes import API_PREFIX
from payflow.api.schemas.transactions import (
    HistoryQuery,
    TransactionPage,
    TransactionResponse,
)

router = APIRouter(prefix=API_PREFIX, tags=["transactions"])


@router.get("/transactions")
async def list_transactions(
    user: CurrentUser,
    history: HistoryServiceDep,
    query: Annotated[HistoryQuery, Query()],
) -> TransactionPage:
    page = await history.page(
        user.id,
        query.to_filter(),
        after=decode_cursor(query.cursor) if query.cursor else None,
        limit=query.limit,
    )
    return TransactionPage(
        items=[TransactionResponse.for_viewer(item, user.id) for item in page.items],
        next_cursor=encode_cursor(page.next_position) if page.next_position else None,
    )


@router.get("/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: UUID, user: CurrentUser, history: HistoryServiceDep
) -> TransactionResponse:
    transaction = await history.get(user.id, transaction_id)
    return TransactionResponse.for_viewer(transaction, user.id)
