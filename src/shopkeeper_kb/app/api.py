from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from shopkeeper_kb.app.errors import register_exception_handlers
from shopkeeper_kb.app.middleware.request_id import RequestIdMiddleware
from shopkeeper_kb.app.routes import router as api_router
from shopkeeper_kb.logging_config import init_logging
from shopkeeper_kb.settings import get_settings

APP_ROOT = Path(__file__).resolve().parent
STATIC_DIR = APP_ROOT / "static"
STATIC_DIR.mkdir(exist_ok=True)


def create_app() -> FastAPI:
    settings = get_settings()
    init_logging(settings.log_level)

    app = FastAPI(title="智能知识库")
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url="/static/index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        p = STATIC_DIR / "favicon.ico"
        if p.exists():
            return FileResponse(p)
        return RedirectResponse(url="/static/index.html")

    return app


app = create_app()
