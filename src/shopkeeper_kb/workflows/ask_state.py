"""
梯队 3.1：AskAgent 全链路 LangGraph state。
节点顺序：extract_features → compliance_fence → 7 专家打分 → 合并全局 sources 并 P0-1 重写 supporting_source_idx → generation 合成最终 answer + 6 数字交易计划 + 最终引用卡。
"""
from __future__ import annotations

from typing import Any, Required, TypedDict

from shopkeeper_kb.workflows.state import (
    FinalTradePlan,
    PerExpertResult,
    SourceCardItem,
    StructuredInput,
)

__all__ = ["AskGraphState", "AskGraphUserInput"]


class AskGraphUserInput(TypedDict, total=False):
    """/api/qa/stream POST body 解析后的最小输入字段。"""

    user_query: Required[str]                    # 用户原始 query（detect_hypothetical_modifiers 用）
    user_id: Required[str]                       # 匿名 UUID（对齐 user_profiles；没有则传 session-xxx）
    request_id: Required[str]                    # X-Request-Id

    # 用户画像 3 字段（不传则走默认值，见 extract_features.build_structured_input）
    user_account_capital: float                  # 总本金（默认 300_000）
    user_risk_r_pct: float                       # 单笔 R 百分比（默认 0.01 = 1%）
    user_single_ticket_max: float                # 单票最大仓位（默认 0.25）
    user_industry_max: float                     # 行业最大仓位（默认 0.30）
    user_risk_score: float                       # 0-100 风险测评分（80 以下禁玩 ST）
    user_current_positions: list[dict]           # 当前持仓快照，用于 RISK_04 行业集中度

    # 可选：直接传覆写字段（P0-8 假设追问内部 override dict；接口用户也可以直接传，不用正则检测）
    override_fields: dict


class AskGraphState(TypedDict, total=False):
    """
    LangGraph 流转的全状态。每个节点只负责写入自己管辖的字段（见每个节点的 docstring）。
    """
    # ---- 输入（路由层填充，不可变） ----
    user_input: Required[AskGraphUserInput]

    # ---- N1 extract_features 节点 ----
    structured: StructuredInput                   # 36 字段 StructuredInput（所有规则打分的唯一数据源）
    is_hypothetical_override: bool                # P0-8：本次是否命中假设模式（detect_hypothetical_modifiers）
    override_applied: dict                        # 实际生效的覆写字段（用于用户追问展示「我按您的假设调整了 xxx」）

    # ---- N2 compliance_fence 节点 ----
    compliance: Any                              # compliance_fence.ComplianceResult（避免 typing.get_type_hints 解析 TYPE_CHECKING 时报 NameError）

    # ---- N3 score_per_expert 节点（7 专家并行，本项目一次 Python 调用 for 循环出 7 条即可） ----
    per_expert_results: Required[list[PerExpertResult]]

    # ---- N4 merge_sources 节点（P0-1 全局下标重写） ----
    sources_global_final: Required[list[SourceCardItem]]  # 合并去重排序后的全局引用卡（模块 6 展示用）
    # 合并辅助：local_chunk_id → (doc_type, global_idx)；generation 节点不用，merge_sources 自己内部用
    _chunk_id_to_global: dict

    # ---- N5 generation 节点（最终 answer + 6 数字交易计划 + 引用卡） ----
    final_answer_markdown: Required[str]          # 最终合成 Markdown（含开场白 + 7 专家摘要 + 6 数字交易计划表格 + 引用提示）
    final_trade_plan: Required[FinalTradePlan]    # 6 数字交易计划（P0-2 clamp 过）
    final_direction: Required[str]                # bull/bear/neutral/refused（与 trade_plan.direction 一致；冗余字段方便前端取）
    final_answer_delta_segments: list[str]        # SSE E4 事件需要的增量片段（骨架阶段 generation 切成 4~6 段发）

    # ---- trace（写 analysis_snapshots 用） ----
    started_at: float
    finished_at: float

    # ---- 书架生效开关：N3/N4/N5 检索与生成都只在 enabled_doc_ids 里做（R5-2/R5-4） ----
    enabled_doc_ids: list[str]
    # 骨架期调试开关：True=不加载 2.2GB embedding 模型；False=真走 Milvus 检索
    _skip_sources: bool
