from __future__ import annotations

from fastapi import FastAPI

from shopkeeper_kb.app.errors import register_exception_handlers
from shopkeeper_kb.app.middleware.request_id import RequestIdMiddleware
from shopkeeper_kb.app.routes import router as api_router
from shopkeeper_kb.logging_config import init_logging
from shopkeeper_kb.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    init_logging(settings.log_level)

    app = FastAPI(title="shopkeeper-kb")
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
