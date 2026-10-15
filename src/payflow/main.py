from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI

from payflow.api.errors import register_error_handlers
from payflow.api.router import api_router
from payflow.container import Container, build_container
from payflow.core.config import get_settings
from payflow.core.logging import configure_logging


def create_app(container: Container | None = None) -> FastAPI:
    container = container or build_container(get_settings())
    settings = container.settings
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await container.aclose()

    app = FastAPI(title="PayFlow", version=version("payflow"), lifespan=lifespan)
    app.state.container = container
    register_error_handlers(app)
    app.include_router(api_router)
    return app
