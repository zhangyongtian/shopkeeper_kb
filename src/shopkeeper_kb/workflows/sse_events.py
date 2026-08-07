"""
梯队 3.2：SSE 事件协议（5 类）。
text/event-stream 规范：每条 "event: X\\ndata: JSON\\n\\n"，客户端 EventSource 按 event 类型分发。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

__all__ = [
    "SSEEventType",
    "SSEComplianceEvent",
    "SSEExpertResultEvent",
    "SSESourcesEvent",
    "SSEAnswerDeltaEvent",
    "SSEDoneEvent",
    "to_sse_lines",
    "sse_json",
]

SSEEventType = str
E_COMPLIANCE: SSEEventType = "compliance"        # E1：合规围栏结果（pass / refuse 原因）
E_EXPERT_RESULT: SSEEventType = "expert_result"  # E2：每位专家发言一条（7 条）
E_SOURCES: SSEEventType = "sources"              # E3：最终全局合并 sources（引用卡）
E_ANSWER_DELTA: SSEEventType = "answer_delta"    # E4：最终回答 Markdown 增量段（多段，对应前端打字机效果）
E_DONE: SSEEventType = "done"                    # E5：结束，携带最终摘要（方向 / 交易计划 / 最终 MD 全文）


@dataclass
class SSEComplianceEvent:
    """E1：合规围栏结果（前端拿到后先在模块 0 顶部横幅显 passed/refused）。"""

    request_id: str
    passed: bool
    refused_reasons: list[str] = field(default_factory=list)
    is_hypothetical_override: bool = False       # P0-8：是否为假设追问模式
    stock_code: str = ""
    stock_name: str = ""
    event: str = E_COMPLIANCE                    # 冗余，方便客户端少判断


@dataclass
class SSEExpertResultEvent:
    """E2：每位专家发言一条（7 位专家 = 7 条事件）。"""

    request_id: str
    expert_index: int                            # 0~6
    doc_type: str
    display_name: str                            # 模块 3 专家卡标题
    direction: str                               # bull/bear/neutral/refused
    score: float                                 # 原始分
    weighted_score: float                        # 加权分
    spoken_opening: str                          # 开场白（含固定口头禅）
    spoken_body: str                             # 详细解释 Markdown
    reason_rules: list[dict] = field(default_factory=list)  # 前 3 条规则的 list[ExpertRuleHit dict]（用于🔍 pop-over）
    sources_local_count: int = 0                 # 该专家召回了多少个自己的 sources（前端展示有 / 无引用 chip）
    color: str = "#8ecae6"
    event: str = E_EXPERT_RESULT


@dataclass
class SSESourcesEvent:
    """E3：最终全局合并 sources（引用卡）一次性全部推过去。"""

    request_id: str
    sources: list[dict]                          # list[SourceCardItem]（骨架阶段 list[dict] 就行，保证 JSON 可序列化）
    total: int = 0
    event: str = E_SOURCES


@dataclass
class SSEAnswerDeltaEvent:
    """E4：最终 answer 的一个增量段（每次推 1 段，客户端 append 到最终 Markdown 容器 = 打字机效果）。"""

    request_id: str
    segment_index: int
    total_segments: int
    text: str                                    # Markdown 片段（可能带换行）
    event: str = E_ANSWER_DELTA


@dataclass
class SSEDoneEvent:
    """E5：结束（最终方向 + 完整 trade_plan dict + 总耗时 ms + 最终 Markdown 全文，方便前端一键复制 / 导出）。"""

    request_id: str
    final_direction: str
    final_trade_plan: dict                       # FinalTradePlan（JSON 可序列化 dict）
    total_ms: int                                # 总耗时
    full_markdown: str                           # 完整 Markdown（最终答案；骨架阶段也传，方便兜底渲染）
    per_expert_count: int = 0
    sources_count: int = 0
    enabled_book_count: int = 0                  # 本次检索用到的生效书数量（对应书架勾选 enabled=true 的数量）
    debug: dict | None = None                    # 调试信息：enabled_doc_ids 长度 / 熔断原因等（前端可渲染成提示条）
    event: str = E_DONE


def sse_json(obj: Any) -> str:
    """把 dataclass / dict 序列化为 JSON，保证中文可读 + 无 NaN/Inf（SSE 不允许非法数字字面量）。"""
    try:
        if hasattr(obj, "__dataclass_fields__"):
            obj = asdict(obj)
        return json.dumps(obj, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        return json.dumps({"error": "unserializable", "type": type(obj).__name__}, ensure_ascii=False)


def to_sse_lines(event_type: SSEEventType, obj: Any) -> str:
    """把一条事件转成 SSE 字符串（末尾带 \\n\\n，客户端 EventSource 以这个为分隔）。"""
    return f"event: {event_type}\ndata: {sse_json(obj)}\n\n"
