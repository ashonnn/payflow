from typing import Annotated

from fastapi import APIRouter, Query

from payflow.api.deps import CurrentUser, NotificationServiceDep
from payflow.api.routes import API_PREFIX
from payflow.api.schemas.notifications import NotificationResponse

router = APIRouter(prefix=API_PREFIX, tags=["notifications"])


@router.get("/notifications")
async def list_notifications(
    user: CurrentUser,
    notifications: NotificationServiceDep,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[NotificationResponse]:
    items = await notifications.recent(user.id, before_id=before_id, limit=limit)
    return [NotificationResponse.model_validate(item) for item in items]
