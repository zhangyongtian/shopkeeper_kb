from __future__ import annotations

from fastapi import APIRouter

from shopkeeper_kb.app.routes.admin import router as admin_router
from shopkeeper_kb.app.routes.health import router as health_router
from shopkeeper_kb.app.routes.ingestion import router as ingestion_router
from shopkeeper_kb.app.routes.mock_chat import router as mock_router
from shopkeeper_kb.app.routes.pdf import router as pdf_router
from shopkeeper_kb.app.routes.qa import router as qa_router

router = APIRouter()
router.include_router(health_router)
router.include_router(mock_router)
router.include_router(pdf_router)
router.include_router(ingestion_router)
router.include_router(admin_router)
router.include_router(qa_router)
