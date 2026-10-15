from fastapi import APIRouter

from payflow.api.routes import (
    accounts,
    auth,
    deposits,
    reviews,
    transactions,
    transfers,
    webhooks,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(deposits.router)
api_router.include_router(transfers.router)
api_router.include_router(transactions.router)
api_router.include_router(reviews.router)
api_router.include_router(webhooks.router)
