from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from shopkeeper_kb.settings import get_settings

router = APIRouter(prefix="/api/pdf", tags=["pdf"])


def _safe_resolve(file_name: str) -> Path:
    """防越权：只允许从 settings.doc_dir 读取，防止 ../../../etc/passwd。"""
    if ".." in Path(file_name).parts:
        raise HTTPException(status_code=400, detail="invalid file name")
    settings = get_settings()
    base = Path(settings.doc_dir).resolve()
    target = (base / file_name).resolve()
    try:
        target.relative_to(base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="invalid file path") from e
    if not target.is_file():
        raise HTTPException(status_code=404, detail="pdf file not found")
    return target


@router.get("/{file_name:path}", summary="预览或下载 PDF（支持 PDF.js #page= 锚点）")
async def get_pdf(
    file_name: str,
    request: Request,
    page: int | None = Query(default=None, ge=1, description="可选，预跳转页码（由前端 PDF.js viewer hash 生效）"),
    download: bool = Query(default=False, description="true 时触发下载而非预览"),
):
    target = _safe_resolve(file_name)
    media_type = "application/pdf"
    if download:
        return FileResponse(
            target,
            media_type=media_type,
            filename=target.name,
        )
    return FileResponse(target, media_type=media_type)
