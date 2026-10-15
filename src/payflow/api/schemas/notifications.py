from datetime import datetime

from pydantic import BaseModel, ConfigDict

from payflow.domain.enums import EventType


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: EventType
    message: str
    created_at: datetime
