from __future__ import annotations

import time
import uuid
from datetime import UTC
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from shopkeeper_kb.logging_config import get_logger
from shopkeeper_kb.settings import Settings, get_settings
from shopkeeper_kb.tools.mongo import get_db

logger = get_logger("shopkeeper_kb.routes.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])


# ================================================================
# P1-1 Admin 路由保护：X-Admin-Key Header 必须等于 env admin_api_key
# ================================================================


def require_admin(
    request: Request,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if not x_admin_key or x_admin_key != settings.admin_api_key:
        logger.warning(f"admin access denied from {request.client.host if request.client else '?'} header={bool(x_admin_key)}")
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ADMIN_UNAUTHORIZED",
                "message": "X-Admin-Key 不正确或缺失",
            },
        )


# --------------------- Pydantic 输入 ---------------------


class RegisterBookReq(BaseModel):
    doc_type: str = Field(..., description="唯一键，例如 risk_position / 笑傲股市_lmr", max_length=64)
    display_name: str = Field(..., description="前端展示名", examples=["笑傲股市（Mark Minervini）"])
    pdf_name: str = Field(..., description="doc/xxx.pdf 文件名", examples=["笑傲股市.pdf"])
    expert_role: str = Field("内容专家", description="专家角色", examples=["形态大师", "风险官"])
    emoji_tag: str = Field("📘", description="发言前缀 emoji")
    color: str = Field("#8ecae6", description="发言卡主色（CSS）")
    weight: float = Field(1.0, ge=0.0, le=5.0, description="仲裁官加权权重")
    priority: int = Field(50, description="列表排序（越小越靠前）")
    disabled: bool = Field(False, description="默认 false；财报等占位可设 true")
    fixed_mantra: str = Field("", description="14.3 人格化固定口头禅")
    domain_keywords: list[str] = Field(default_factory=list, description="关键词路由优先触发该书")
    auto_trigger_ingestion: bool = Field(True, description="注册成功后立刻后台跑 ingestion")


class ToggleDisabledReq(BaseModel):
    doc_type: str
    disabled: bool


class ReingestReq(BaseModel):
    doc_type: str


class SoftDelReq(BaseModel):
    doc_type: str


class SetBookEnabledReq(BaseModel):
    enabled: bool = Field(..., description="true=生效参与检索；false=暂时不生效（仍保留在书架里，随时可开启）")


# ================================================================
# 1) GET /books （书架：列出所有已导入的书，来自 documents_metadata，前端勾选 enabled）
# ================================================================


@router.get("/books", summary="书架：列出所有已入库的书（documents_metadata），默认按更新时间倒序")
def api_get_books(
    enabled: bool | None = None,
    doc_type: str | None = None,
    _admin: None = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """
    返回所有 documents_metadata 记录，每条包含：
    - doc_id / doc_type / display_name / file_title / item_name / item_tags
    - chunk_count / page_count / enabled / ingested_at / updated_at / source
    - status / task_id / md_path / pdf_path
    """
    db = get_db(settings)
    coll = db[settings.coll_documents_metadata]
    q: dict[str, Any] = {}
    if enabled is not None:
        q["enabled"] = bool(enabled)
    if doc_type:
        q["doc_type"] = doc_type
    docs = list(coll.find(q, projection={"_id": 0}).sort([("updated_at", -1), ("ingested_at", -1)]))
    enabled_count = sum(1 for d in docs if d.get("enabled", True))
    return {
        "ok": True,
        "total": len(docs),
        "enabled_count": enabled_count,
        "items": [_normalize_doc_meta(d) for d in docs],
    }


# ================================================================
# 2) POST /books/{doc_id}/enabled （单本开关：勾选/取消勾选 enabled）
# ================================================================


@router.post("/books/{doc_id}/enabled", summary="单本书的生效开关：enabled=true 才参与 QA 检索命中")
def api_set_book_enabled(
    doc_id: str,
    req: SetBookEnabledReq,
    _admin: None = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    db = get_db(settings)
    coll = db[settings.coll_documents_metadata]
    res = coll.update_one(
        {"doc_id": doc_id},
        {"$set": {"enabled": bool(req.enabled), "updated_at": _now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"doc_id {doc_id} not found")
    doc = coll.find_one({"doc_id": doc_id}, projection={"_id": 0})
    enabled_count = coll.count_documents({"enabled": {"$ne": False}})
    return {
        "ok": True,
        "doc_id": doc_id,
        "enabled": bool(req.enabled),
        "enabled_count": enabled_count,
        "doc": _normalize_doc_meta(doc) if doc else None,
        "matched": res.matched_count,
        "modified": res.modified_count,
    }


# ================================================================
# 3) POST /register_book （开放扩展：新增一本书进 expert_books，自动跑 ingestion）
# ================================================================


@router.post("/register_book", summary="【开放架构】注册一本新专家书 → 写入 expert_books + 后台启动 ingestion（X-Admin-Key 保护）")
def api_register_book(
    req: RegisterBookReq,
    bg: BackgroundTasks,
    _admin: None = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    db = get_db(settings)
    coll = db[settings.coll_expert_books]
    # 幂等：doc_type 存在则返回已存在但不覆盖（开放架构红线），仅 disabled=false 等字段可通过单独 update
    existed = coll.find_one({"doc_type": req.doc_type})
    now = int(time.time())
    doc_id = f"exp_{uuid.uuid4().hex[:12]}"
    if existed:
        return {
            "ok": True,
            "idle": True,
            "note": f"doc_type {req.doc_type} 已存在，为了保护你之前录入/上传的内容，register_book **不会覆盖已有记录**；请调用 PATCH /toggle_disabled 或 POST /reingest 修改其它字段。",
            "doc": _strip_id(existed),
        }
    insert_doc = {
        "doc_id": doc_id,
        "doc_type": req.doc_type,
        "display_name": req.display_name,
        "pdf_name": req.pdf_name,
        "expert_role": req.expert_role,
        "emoji_tag": req.emoji_tag,
        "color": req.color,
        "weight": float(req.weight),
        "priority": int(req.priority),
        "disabled": bool(req.disabled),
        "fixed_mantra": req.fixed_mantra,
        "domain_keywords": list(req.domain_keywords),
        "historical_accuracy": 0.0,
        "historical_total": 0,
        "historical_correct": 0,
        "ingestion_status": "queued" if req.auto_trigger_ingestion else "idle",
        "soft_deleted": False,
        "created_at": now,
        "updated_at": now,
    }
    coll.insert_one(insert_doc)

    task_id: str | None = None
    if req.auto_trigger_ingestion:
        from shopkeeper_kb.app.routes.ingestion import (
            RegisterAndRunReq,
            _bg_run_ingestion,
            _resolve_paths,
            _task_id_prefix,
        )

        task_id = _task_id_prefix(req.doc_type)
        r = RegisterAndRunReq(
            doc_type=req.doc_type,
            pdf_name=req.pdf_name,
            md_path=None,
            pdf_path=None,
            force_reingest=False,
            resume_from_stage=None,
            resume_from_position=0,
        )
        pdf_path, md_path = _resolve_paths(r, settings)
        db[settings.coll_ingestion_tasks].update_one(
            {"task_id": task_id},
            {
                "$setOnInsert": {
                    "task_id": task_id,
                    "kind": "ingest_one",
                    "doc_type": req.doc_type,
                    "pdf_name": req.pdf_name,
                    "pdf_path": pdf_path,
                    "md_path": md_path,
                    "force_reingest": False,
                    "resume_from_stage": None,
                    "resume_from_position": 0,
                    "status": "queued",
                    "progress_pct": 0,
                    "stage": "queued",
                    "stage_extra": {},
                    "result": None,
                    "last_err": None,
                    "last_traceback": None,
                    "created_at": now,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        bg.add_task(_bg_run_ingestion, task_id)

    return {
        "ok": True,
        "doc": _strip_id(insert_doc),
        "ingestion_task_id": task_id,
    }


# ================================================================
# 2) GET /list_experts （列出所有专家书，含 enabled 过滤参数；admin 可见软删除）
# ================================================================


@router.get("/list_experts", summary="列出所有专家书（X-Admin-Key 保护），返回 ingestion_status / enabled/disabled / weight 排序")
def api_list_experts(
    include_disabled: bool = True,
    include_soft_deleted: bool = False,
    _admin: None = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    db = get_db(settings)
    q: dict[str, Any] = {}
    if not include_disabled:
        q["disabled"] = False
    if not include_soft_deleted:
        q["soft_deleted"] = {"$ne": True}
    docs = list(
        db[settings.coll_expert_books].find(q).sort([("priority", 1), ("doc_type", 1)])
    )
    return {"ok": True, "total": len(docs), "items": [_strip_id(d) for d in docs]}


# ================================================================
# 3) PATCH /toggle_disabled （临时开关某本书；不删数据）
# ================================================================


@router.patch("/toggle_disabled", summary="临时启用/禁用某本专家书（doc_type 精确匹配；X-Admin-Key 保护）")
def api_toggle_disabled(
    req: ToggleDisabledReq,
    _admin: None = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    db = get_db(settings)
    res = db[settings.coll_expert_books].update_one(
        {"doc_type": req.doc_type, "soft_deleted": {"$ne": True}},
        {"$set": {"disabled": bool(req.disabled), "updated_at": int(time.time())}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"doc_type {req.doc_type} not found or soft-deleted")
    return {"ok": True, "matched": res.matched_count, "modified": res.modified_count}


# ================================================================
# 4) POST /reingest （强制重新跑 ingestion：先删旧 chunk 图/向量/meta，再从头跑）
# ================================================================


@router.post("/reingest", summary="强制重新跑某本书 ingestion（先清旧数据；X-Admin-Key 保护）")
def api_reingest(
    req: ReingestReq,
    bg: BackgroundTasks,
    _admin: None = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    db = get_db(settings)
    book = db[settings.coll_expert_books].find_one({"doc_type": req.doc_type, "soft_deleted": {"$ne": True}})
    if not book:
        raise HTTPException(status_code=404, detail=f"doc_type {req.doc_type} not found")
    pdf_name = book.get("pdf_name")
    if not pdf_name:
        raise HTTPException(status_code=400, detail=f"doc_type {req.doc_type} 没有 pdf_name，无法 reingest")

    from shopkeeper_kb.app.routes.ingestion import RegisterAndRunReq, _bg_run_ingestion, _resolve_paths, _task_id_prefix

    task_id = _task_id_prefix(req.doc_type)
    r = RegisterAndRunReq(
        doc_type=req.doc_type,
        pdf_name=pdf_name,
        md_path=None,
        pdf_path=None,
        force_reingest=True,
        resume_from_stage=None,
        resume_from_position=0,
    )
    pdf_path, md_path = _resolve_paths(r, settings)
    now = int(time.time())
    db[settings.coll_ingestion_tasks].update_one(
        {"task_id": task_id},
        {
            "$setOnInsert": {
                "task_id": task_id,
                "kind": "ingest_one",
                "doc_type": req.doc_type,
                "pdf_name": pdf_name,
                "pdf_path": pdf_path,
                "md_path": md_path,
                "force_reingest": True,
                "resume_from_stage": None,
                "resume_from_position": 0,
                "status": "queued",
                "progress_pct": 0,
                "stage": "queued",
                "stage_extra": {},
                "result": None,
                "last_err": None,
                "last_traceback": None,
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    bg.add_task(_bg_run_ingestion, task_id)
    db[settings.coll_expert_books].update_one(
        {"doc_type": req.doc_type},
        {"$set": {"ingestion_status": "queued", "updated_at": now}},
    )
    return {"ok": True, "ingestion_task_id": task_id, "force_reingest": True}


# ================================================================
# 5) PATCH /soft_delete （软删；软删后默认 list_experts 不可见，Milvus/Mongo 元数据保留方便回滚）
# ================================================================


@router.patch("/soft_delete", summary="软删除一本专家书（X-Admin-Key 保护）；保留 chunk/向量，可随时恢复")
def api_soft_delete(
    req: SoftDelReq,
    _admin: None = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    db = get_db(settings)
    res = db[settings.coll_expert_books].update_one(
        {"doc_type": req.doc_type},
        {"$set": {"soft_deleted": True, "disabled": True, "updated_at": int(time.time())}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"doc_type {req.doc_type} not found")
    return {"ok": True, "matched": res.matched_count, "soft_deleted": True}


# ================================================================
# Helper
# ================================================================


def _strip_id(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "_id"}


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_doc_meta(d: dict | None) -> dict:
    if not d:
        return {}
    return {
        "doc_id": d.get("doc_id", ""),
        "task_id": d.get("task_id", ""),
        "doc_type": d.get("doc_type", ""),
        "display_name": d.get("display_name") or d.get("file_title") or "未命名",
        "file_title": d.get("file_title", ""),
        "item_name": d.get("item_name", ""),
        "item_tags": list(d.get("item_tags") or []),
        "chunk_count": int(d.get("chunk_count") or 0),
        "page_count": int(d.get("page_count") or 0),
        "status": d.get("status") or "active",
        "source": d.get("source") or "unknown",
        "enabled": bool(d.get("enabled", True)),
        "md_path": d.get("md_path", ""),
        "pdf_path": d.get("pdf_path", ""),
        "ingested_at": d.get("ingested_at", ""),
        "updated_at": d.get("updated_at", ""),
    }

