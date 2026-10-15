from fastapi import APIRouter

from payflow.api.routes import (
    accounts,
    auth,
    deposits,
    exchange,
    notifications,
    reviews,
    transactions,
    transfers,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(deposits.router)
api_router.include_router(transfers.router)
api_router.include_router(exchange.router)
api_router.include_router(transactions.router)
api_router.include_router(notifications.router)
api_router.include_router(reviews.router)
api_router.include_router(webhooks.router)
