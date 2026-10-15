import base64
import binascii
import json
from datetime import datetime
from uuid import UUID

from payflow.domain.exceptions import InvalidCursorError
from payflow.domain.history import FeedPosition


def encode_cursor(position: FeedPosition) -> str:
    raw = json.dumps({"t": position.created_at.isoformat(), "id": str(position.id)})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> FeedPosition:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        return FeedPosition(
            created_at=datetime.fromisoformat(data["t"]), id=UUID(data["id"])
        )
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise InvalidCursorError from exc
