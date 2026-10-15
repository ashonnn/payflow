import re
import time
from uuid import uuid4

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.routing import BaseRoute, Mount, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from payflow.core.metrics import HTTP_LATENCY, HTTP_REQUESTS

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"[\w\-]{1,64}")

logger = structlog.get_logger("payflow.access")


class RequestContextMiddleware:
    """Request ids, one structured log line and latency metrics per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.fullmatch(incoming) else uuid4().hex
        method, path = scope["method"], scope["path"]
        status_code = 500
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            elapsed = time.perf_counter() - started
            route = route_template(scope.get("route"))
            HTTP_REQUESTS.labels(method, route, str(status_code)).inc()
            HTTP_LATENCY.labels(method, route).observe(elapsed)
            logger.info(
                "request.completed",
                method=method,
                path=path,
                route=route,
                status=status_code,
                duration_ms=round(elapsed * 1000, 2),
            )
            structlog.contextvars.clear_contextvars()


def route_template(route: BaseRoute | None) -> str:
    # templates rather than raw paths keep metric label cardinality bounded
    match route:
        case Route(path=path) | Mount(path=path):
            return path
        case _:
            return "unmatched"
