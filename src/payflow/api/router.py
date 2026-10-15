from fastapi import APIRouter

from payflow.api.routes import accounts, auth

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
