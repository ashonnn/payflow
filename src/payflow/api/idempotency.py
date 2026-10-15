import hashlib
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from payflow.api.deps import CurrentUser, SessionDep
from payflow.db.models import IdempotencyKey
from payflow.db.repositories.idempotency import IdempotencyRepository
from payflow.domain.exceptions import (
    IdempotencyKeyInProgressError,
    IdempotencyKeyRequiredError,
    IdempotencyKeyReusedError,
)

REPLAYED_HEADER = "Idempotent-Replayed"


class Idempotency:
    """Runs a write once per key; retries get the stored response back.

    The key and the write's effects commit in the same transaction."""

    def __init__(
        self, request: Request, session: AsyncSession, user_id: UUID, key: str
    ) -> None:
        self.key = key
        self._request = request
        self._session = session
        self._user_id = user_id
        self._keys = IdempotencyRepository(session)

    async def run(
        self,
        payload: BaseModel,
        operation: Callable[[], Awaitable[BaseModel]],
        *,
        status_code: int = status.HTTP_201_CREATED,
    ) -> JSONResponse:
        fingerprint = self._fingerprint(payload)
        previous = await self._keys.claim(self._user_id, self.key, fingerprint)
        if previous is not None:
            return self._replay(previous, fingerprint)
        result = await operation()
        body = result.model_dump(mode="json")
        await self._keys.store_response(self._user_id, self.key, status_code, body)
        await self._session.commit()
        return JSONResponse(body, status_code=status_code)

    def _fingerprint(self, payload: BaseModel) -> str:
        request = f"{self._request.method} {self._request.url.path}\n"
        return hashlib.sha256(
            (request + payload.model_dump_json()).encode()
        ).hexdigest()

    @staticmethod
    def _replay(previous: IdempotencyKey, fingerprint: str) -> JSONResponse:
        if previous.request_fingerprint != fingerprint:
            raise IdempotencyKeyReusedError
        if previous.response_status is None or previous.response_body is None:
            raise IdempotencyKeyInProgressError
        return JSONResponse(
            previous.response_body,
            status_code=previous.response_status,
            headers={REPLAYED_HEADER: "true"},
        )


async def get_idempotency(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", max_length=255)
    ] = None,
) -> Idempotency:
    if not idempotency_key:
        raise IdempotencyKeyRequiredError
    return Idempotency(request, session, user.id, idempotency_key)


IdempotencyDep = Annotated[Idempotency, Depends(get_idempotency)]
