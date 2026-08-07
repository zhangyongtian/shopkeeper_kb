from __future__ import annotations

import os
import time
import traceback
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from shopkeeper_kb.logging_config import get_logger
from shopkeeper_kb.settings import Settings, get_settings
from shopkeeper_kb.tools.ingestion import IngestRequest, run_ingest_with_retry
from shopkeeper_kb.tools.mongo import get_db

logger = get_logger("shopkeeper_kb.routes.ingestion")
router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])

# --------------------- 请求/响应 Pydantic Model ---------------------


class RegisterAndRunReq(BaseModel):
    doc_type: str = Field(..., description="专家书 doc_type（对齐 expert_books.doc_type）", examples=["candlestick"])
    pdf_name: str = Field(..., description="doc/ 下的 pdf 文件名", examples=["日本蜡烛图技术.pdf"])
    md_path: str | None = Field(
        None,
        description="本地 MinerU md 路径；留空 = 用 {output_doc_dir}/{pdf_stem}/{pdf_stem}.md 自动拼",
    )
    pdf_path: str | None = Field(None, description="本地 pdf 路径；留空 = {doc_dir}/{pdf_name} 自动拼")
    force_reingest: bool = Field(False, description="是否先清该 doc_type 旧数据再重跑（reingest 接口传 true）")
    resume_from_stage: str | None = Field(None, description="P1-4 失败续跑：上次失败的 stage，空=从头跑")
    resume_from_position: int = Field(0, description="续跑：上次失败的 chunk position（>=该值的 chunk 跳过）")


class IngestionStatusResp(BaseModel):
    task_id: str
    status: str
    doc_type: str
    pdf_name: str
    progress_pct: int = 0
    stage: str = "queued"
    stage_extra: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    last_err: str | None = None
    last_traceback: str | None = None
    created_at: float = 0
    updated_at: float = 0


# --------------------- 内部：任务 id + 写入 ingestion_tasks ---------------------


def _task_id_prefix(doc_type: str) -> str:
    return f"task_{doc_type}_{int(time.time() * 1000)}"


def _resolve_paths(req: RegisterAndRunReq, s: Settings) -> tuple[str, str]:
    pdf_path = req.pdf_path or os.path.join(s.doc_dir, req.pdf_name)
    if req.md_path:
        md_path = req.md_path
    else:
        stem = os.path.splitext(req.pdf_name)[0]
        md_path = os.path.join(s.output_doc_dir, stem, f"{stem}.md")
    return pdf_path, md_path


# --------------------- POST /register_and_run ---------------------


@router.post("/register_and_run", summary="注册一本专家书并启动后台 ingestion（MinerU 产物→Milvus/Mongo/MinIO）", status_code=202)
def api_register_and_run(req: RegisterAndRunReq, bg: BackgroundTasks) -> IngestionStatusResp:
    s = get_settings()
    db = get_db(s)
    task_id = _task_id_prefix(req.doc_type)
    pdf_path, md_path = _resolve_paths(req, s)
    now = int(time.time())
    task_doc: dict[str, Any] = {
        "task_id": task_id,
        "kind": "ingest_one",
        "doc_type": req.doc_type,
        "pdf_name": req.pdf_name,
        "pdf_path": pdf_path,
        "md_path": md_path,
        "force_reingest": req.force_reingest,
        "resume_from_stage": req.resume_from_stage,
        "resume_from_position": req.resume_from_position,
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
    # 建索引（首次跑）
    try:
        db[s.coll_ingestion_tasks].create_index([("task_id", 1)], unique=True, background=True)
        db[s.coll_ingestion_tasks].create_index([("doc_type", 1), ("status", 1)], background=True)
    except Exception:
        pass
    db[s.coll_ingestion_tasks].update_one({"task_id": task_id}, {"$setOnInsert": task_doc}, upsert=True)

    # 用 BackgroundTasks 跑；如果需要更重型可将来换 Celery，这里对齐路线 E 零成本不引入 Redis Queue
    bg.add_task(_bg_run_ingestion, task_id)
    return IngestionStatusResp(**task_doc)


# --------------------- GET /status/{task_id} ---------------------


@router.get("/status/{task_id}", summary="查询 ingestion 任务进度（进度每 10% 步长更新 + P1-4 traceback 可排查）")
def api_ingestion_status(task_id: str) -> IngestionStatusResp:
    s = get_settings()
    db = get_db(s)
    doc = db[s.coll_ingestion_tasks].find_one({"task_id": task_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    return IngestionStatusResp(**{
        "task_id": doc["task_id"],
        "status": doc.get("status", "unknown"),
        "doc_type": doc.get("doc_type", ""),
        "pdf_name": doc.get("pdf_name", ""),
        "progress_pct": int(doc.get("progress_pct", 0)),
        "stage": doc.get("stage", ""),
        "stage_extra": doc.get("stage_extra"),
        "result": doc.get("result"),
        "last_err": doc.get("last_err"),
        "last_traceback": doc.get("last_traceback"),
        "created_at": float(doc.get("created_at", 0)),
        "updated_at": float(doc.get("updated_at", 0)),
    })


# --------------------- 后台任务：进度回调 + 3 次指数退避 ---------------------


def _bg_run_ingestion(task_id: str) -> None:
    s = get_settings()
    db = get_db(s)

    def set_fields(**fields: Any) -> None:
        fields["updated_at"] = int(time.time())
        db[s.coll_ingestion_tasks].update_one({"task_id": task_id}, {"$set": fields})

    doc = db[s.coll_ingestion_tasks].find_one({"task_id": task_id})
    if not doc:
        logger.error(f"bg task {task_id}: doc gone")
        return
    set_fields(status="running", progress_pct=1, stage="start")
    req = IngestRequest(
        doc_type=doc["doc_type"],
        pdf_name=doc["pdf_name"],
        md_path=doc["md_path"],
        pdf_path=doc["pdf_path"],
        force_reingest=bool(doc.get("force_reingest")),
        resume_from_stage=doc.get("resume_from_stage"),
        resume_from_position=int(doc.get("resume_from_position") or 0),
    )

    def progress_cb(pct: int, stage: str, extra: dict | None):
        set_fields(progress_pct=pct, stage=stage, stage_extra=extra or {})

    try:
        result = run_ingest_with_retry(req, settings=s, progress_cb=progress_cb, max_attempts=3)
        set_fields(status="success", progress_pct=100, stage="done", result=result)
        logger.info(f"ingestion task {task_id} success: chunks={result.get('chunk_count')}")
    except Exception as e:
        tb = traceback.format_exc()
        logger.exception(f"ingestion task {task_id} 最终失败（3 次重试后）: {e}")
        set_fields(
            status="failed",
            last_err=str(e),
            last_traceback=tb,
            progress_pct=max(int(doc.get("progress_pct") or 0), 10),
        )
