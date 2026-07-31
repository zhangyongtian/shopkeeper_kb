from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health", summary="Health check")
async def health(request: Request) -> dict[str, str]:
    request_id = getattr(request.state, "request_id", "")
    return {"status": "ok", "request_id": request_id}
