from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from payflow.api.deps import AdminUser, ReviewServiceDep, SessionDep
from payflow.api.routes import API_PREFIX
from payflow.api.schemas.reviews import RejectRequest, ReviewResponse

router = APIRouter(prefix=f"{API_PREFIX}/admin/reviews", tags=["admin"])


@router.get("")
async def list_pending_reviews(
    _: AdminUser,
    reviews: ReviewServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ReviewResponse]:
    pending = await reviews.pending(limit)
    return [ReviewResponse.from_transaction(transaction) for transaction in pending]


@router.post("/{transaction_id}/approve")
async def approve_transfer(
    transaction_id: UUID,
    admin: AdminUser,
    reviews: ReviewServiceDep,
    session: SessionDep,
) -> ReviewResponse:
    transaction = await reviews.approve(transaction_id, admin.id)
    await session.commit()
    return ReviewResponse.from_transaction(transaction)


@router.post("/{transaction_id}/reject")
async def reject_transfer(
    transaction_id: UUID,
    payload: RejectRequest,
    admin: AdminUser,
    reviews: ReviewServiceDep,
    session: SessionDep,
) -> ReviewResponse:
    transaction = await reviews.reject(transaction_id, admin.id, payload.reason)
    await session.commit()
    return ReviewResponse.from_transaction(transaction)
