from __future__ import annotations

from .settings import get_settings


def main() -> None:
    settings = get_settings()

    try:
        import uvicorn
    except Exception:
        print("uvicorn is not installed. Run: uv add uvicorn && uv sync")
        return

    uvicorn.run(
        "shopkeeper_kb.app.api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
    )
