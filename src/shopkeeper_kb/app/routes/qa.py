"""
梯队 3.3：POST /api/qa/stream —— 调用 AskAgentRunner，顺序 emit E1~E5 五类 SSE 事件。
不依赖任何 LLM，纯本地 2.1~2.5 模块 + ask_agent 5 节点；为了保证即使 embedding 模型磁盘不够 / 东财接口全挂，也能稳定不崩地推完 5 类事件。
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from shopkeeper_kb.agents.ask_agent import AskAgentRunner
from shopkeeper_kb.logging_config import get_logger
from shopkeeper_kb.settings import Settings, get_settings
from shopkeeper_kb.tools.mongo import get_db
from shopkeeper_kb.workflows.ask_state import AskGraphUserInput
from shopkeeper_kb.workflows.sse_events import (
    E_ANSWER_DELTA,
    E_COMPLIANCE,
    E_DONE,
    E_EXPERT_RESULT,
    E_SOURCES,
    SSEAnswerDeltaEvent,
    SSEComplianceEvent,
    SSEDoneEvent,
    SSEExpertResultEvent,
    SSESourcesEvent,
    to_sse_lines,
)

logger = get_logger("shopkeeper_kb.api.qa")

router = APIRouter(prefix="/api/qa", tags=["qa"])


# ================================================================
# 路由输入 schema
# ================================================================
class QAStreamBody(BaseModel):
    user_query: str = Field(..., min_length=1, max_length=2000, description="用户原始问题（6 位 A 股代码 + 分析诉求）")
    user_id: str = Field(default="anon-default", max_length=64, description="匿名 UUID；前端首次访问生成并 localStorage 保存")
    user_account_capital: float = Field(default=300_000.0, ge=0, description="用户画像：总本金（元）")
    user_risk_r_pct: float = Field(default=0.01, ge=0.001, le=0.1, description="单笔 R%（默认 1%）")
    user_single_ticket_max: float = Field(default=0.25, ge=0, le=1.0, description="单票最大仓位（0.25=25%）")
    user_industry_max: float = Field(default=0.30, ge=0, le=1.0, description="单行业最大仓位")
    user_risk_score: float = Field(default=80.0, ge=0, le=100, description="风险测评分（80 以下禁玩 ST）")
    user_current_positions: list[dict] = Field(default_factory=list, description="当前持仓快照")
    override_fields: dict[str, Any] = Field(default_factory=dict, description="P0-8 假设模式直接传覆写字段，不用正则匹配")


# ================================================================
# 单例 runner（懒加载，第一次 /qa/stream 时构建 LangGraph，后续复用）
# ================================================================
_runner: AskAgentRunner | None = None


def _get_runner() -> AskAgentRunner:
    global _runner
    if _runner is None:
        _runner = AskAgentRunner()
    return _runner


# ================================================================
# 同步生成器 → 推 E1~E5
# ================================================================
def _get_enabled_doc_ids(settings: Settings) -> list[str]:
    """
    书架 UI 勾选 enabled=true 的 doc_id 列表；用于 Milvus expr 过滤。
    没有任何 enabled 的书 → 返回空列表（QA 走骨架兜底，但 sources_count=0，前端看到 0 条引用）。
    """
    try:
        db = get_db(settings)
        coll = db[getattr(settings, "coll_documents_metadata", "documents_metadata")]
        return [str(d["doc_id"]) for d in coll.find({"enabled": {"$ne": False}}, projection={"doc_id": 1})]
    except Exception as e:
        logger.warning(f"获取 enabled_doc_ids 失败（Mongo 未就绪等），走空列表降级：{e}")
        return []


def _emit_events_sync(body: QAStreamBody, request_id: str) -> list[str]:
    t0 = time.perf_counter()
    runner = _get_runner()
    settings = get_settings()
    enabled_doc_ids = _get_enabled_doc_ids(settings)

    ui: AskGraphUserInput = {  # type: ignore[typeddict-item]
        "user_query": body.user_query,
        "user_id": body.user_id,
        "request_id": request_id,
        "user_account_capital": body.user_account_capital,
        "user_risk_r_pct": body.user_risk_r_pct,
        "user_single_ticket_max": body.user_single_ticket_max,
        "user_industry_max": body.user_industry_max,
        "user_risk_score": body.user_risk_score,
        "user_current_positions": list(body.user_current_positions),
        "override_fields": dict(body.override_fields),
    }
    # enabled 书 0 本：告知前端当前书架为空，先去书架上传/勾选
    state = runner.run(ui, enabled_doc_ids=enabled_doc_ids, _skip_sources=len(enabled_doc_ids) == 0)

    out: list[str] = []

    # E1：合规围栏结果
    cp = state["compliance"]
    out.append(to_sse_lines(E_COMPLIANCE, SSEComplianceEvent(
        request_id=request_id,
        passed=bool(cp.passed),
        refused_reasons=list(getattr(cp, "refused_reasons", []) or []),
        is_hypothetical_override=bool(state.get("is_hypothetical_override")),
        stock_code=state["structured"].get("stock_code", ""),
        stock_name=state["structured"].get("stock_name", ""),
    )))

    # E2：每位专家发言一条（7 条）
    for idx, p in enumerate(state.get("per_expert_results") or []):
        rules = (p.get("reason_rules") or [])[:3]
        rules_dicts = [dict(r) for r in rules]  # TypedDict → plain dict，JSON 可序列化
        out.append(to_sse_lines(E_EXPERT_RESULT, SSEExpertResultEvent(
            request_id=request_id,
            expert_index=idx,
            doc_type=str(p.get("doc_type") or ""),
            display_name=str(p.get("spoken_opening") or str(p.get("doc_type") or ""))[:20],
            direction=str(p.get("direction") or "neutral"),
            score=float(p.get("score") or 0.0),
            weighted_score=float(p.get("weighted_score") or 0.0),
            spoken_opening=str(p.get("spoken_opening") or ""),
            spoken_body=str(p.get("spoken_body") or ""),
            reason_rules=rules_dicts,
            sources_local_count=len(p.get("sources_local_raw") or []),
            color="#8ecae6",
        )))

    # E3：合并后的全局 sources（引用卡）
    src_list = [dict(s) for s in state.get("sources_global_final") or []]
    out.append(to_sse_lines(E_SOURCES, SSESourcesEvent(
        request_id=request_id,
        sources=src_list,
        total=len(src_list),
    )))

    # E4：最终 answer 增量段（4~8 段）
    segments = list(state.get("final_answer_delta_segments") or [])
    if not segments:
        segments = [state.get("final_answer_markdown") or ""]
    for si, seg in enumerate(segments):
        out.append(to_sse_lines(E_ANSWER_DELTA, SSEAnswerDeltaEvent(
            request_id=request_id,
            segment_index=si,
            total_segments=len(segments),
            text=str(seg),
        )))

    # E5：done
    total_ms = int((time.perf_counter() - t0) * 1000)
    plan_dict = dict(state["final_trade_plan"])
    enabled_count = len(enabled_doc_ids)
    out.append(to_sse_lines(E_DONE, SSEDoneEvent(
        request_id=request_id,
        final_direction=str(state.get("final_direction") or "neutral"),
        final_trade_plan=plan_dict,
        total_ms=total_ms,
        full_markdown=str(state.get("final_answer_markdown") or ""),
        per_expert_count=len(state.get("per_expert_results") or []),
        sources_count=len(src_list),
        enabled_book_count=enabled_count,
        debug=None if enabled_count else {
            "empty_shelf_hint": "当前没有任何一本生效的书；请先去「书架」上传文档并勾选启用开关。",
        },
    )))
    return out


async def _emit_events_async(body: QAStreamBody, request_id: str) -> AsyncIterable[str]:
    """FastAPI 要求 async 生成器，直接把同步列表一个一个 yield（中间不 await，也不阻塞其他请求，只是串行推当前这条）。"""
    sse_chunks = _emit_events_sync(body, request_id)
    for line in sse_chunks:
        yield line
        # 小间隔模拟流式体验（20ms/段，7 专家 + 4~8 段 answer_delta，总延迟 ≤ 0.5s）
        await asyncio.sleep(0.02)


@router.post("/stream", summary="老李7专家分析（SSE 流式）", response_class=StreamingResponse)
async def qa_stream(body: QAStreamBody, request: Request) -> StreamingResponse:
    """
    全链路：extract_features → compliance 6条熔断 → 7专家打分 → 合并sources(P0-1 idx重写) → 6数字交易计划 → 推流 5 类 SSE。

    curl 示例（合规通过 case）：
    ```bash
    curl -N -X POST http://127.0.0.1:8000/api/qa/stream \
      -H 'Content-Type: application/json' -H 'X-Request-Id: req-demo-0001' \
      -d '{"user_query":"帮我分析贵州茅台 600519 可以买入吗？","user_id":"u-demo-1","user_account_capital":500000,"user_risk_score":85}'
    ```
    """
    request_id = str(getattr(request.state, "request_id", "") or "req-" + str(int(time.time() * 1000)))
    media_type = "text/event-stream"
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "X-Request-Id": request_id,
    }
    return StreamingResponse(_emit_events_async(body, request_id), media_type=media_type, headers=headers)
